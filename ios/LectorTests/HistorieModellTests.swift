import Foundation
import Testing
@testable import Lector

@MainActor
@Suite("Historie: Listenmodell, Filter, Seiten, Live")
struct HistorieModellTests {
    private struct Aufbau {
        let modell: HistorieModell
        let transport: TransportAttrappe
        let quelle: StromQuelleAttrappe
    }

    private func aufbau(
        _ verbindungen: [StromVerbindung] = [StromVerbindung()], _ antworter: @escaping TransportAttrappe.Antworter
    ) -> Aufbau {
        let (client, transport) = Hilfen.client(antworter)
        let quelle = StromQuelleAttrappe(verbindungen)
        let pausen = PausenProtokoll()
        let strom = EreignisStrom(client: client, quelle: quelle, pause: pausen.pause)
        return Aufbau(modell: HistorieModell(client: client, strom: strom), transport: transport, quelle: quelle)
    }

    private func abfrage(_ anfrage: URLRequest) -> [String: String] {
        let items = URLComponents(url: anfrage.url!, resolvingAgainstBaseURL: false)?.queryItems ?? []
        return Dictionary(uniqueKeysWithValues: items.map { ($0.name, $0.value ?? "") })
    }

    // MARK: Laden und Zähler

    @Test("Laden zeigt Vorgänge in der Reihenfolge des Dienstes und die Zähler je Zustand")
    func laden() async throws {
        let a = aufbau { _ in
            Hilfen.liste([Hilfen.dokument(3, status: "processing"), Hilfen.dokument(2), Hilfen.dokument(1, status: "failed")],
                         zaehler: Hilfen.zaehler(processing: 1, done: 5, failed: 2))
        }
        await a.modell.laden()
        #expect(a.modell.dokumente.map(\.id) == [3, 2, 1])
        #expect(a.modell.anzahl(.processing) == 1)
        #expect(a.modell.anzahl(.done) == 5)
        #expect(a.modell.anzahl(.failed) == 2)
        #expect(a.modell.anzahl(.blocked) == 0)
        #expect(a.modell.ladezustand == .geladen)
        let anfrage = try #require(await a.transport.anfragen.first)
        #expect(abfrage(anfrage) == ["limit": "50", "offset": "0"])
        #expect(anfrage.bearer == "k1")
    }

    @Test("Filter nach Zustand: Anfrage mit status, Zähler bleiben der ganze Bestand")
    func filterZustand() async {
        let a = aufbau { anfrage in
            let nurFehler = anfrage.url?.query?.contains("status=failed") == true
            return Hilfen.liste(nurFehler ? [Hilfen.dokument(1, status: "failed")] : [Hilfen.dokument(2), Hilfen.dokument(1, status: "failed")],
                                zaehler: Hilfen.zaehler(done: 4, failed: 1))
        }
        await a.modell.laden()
        await a.modell.statusWaehlen(.failed)
        #expect(a.modell.dokumente.map(\.id) == [1])
        #expect(a.modell.statusFilter == .failed)
        #expect(a.modell.anzahl(.done) == 4)
        #expect(a.modell.filterAktiv)
        // Derselbe Zustand noch einmal hebt den Filter auf.
        await a.modell.statusWaehlen(.failed)
        #expect(a.modell.statusFilter == nil)
        #expect(a.modell.dokumente.count == 2)
    }

    @Test("Suche und Zeitraum gehen als q und period an den Dienst und setzen die Liste zurück")
    func sucheUndZeitraum() async throws {
        let a = aufbau { _ in Hilfen.liste([Hilfen.dokument(1)]) }
        await a.modell.laden()
        await a.modell.sucheSetzen("  Telekom ")
        await a.modell.zeitraumWaehlen(.woche)
        let letzte = try #require(await a.transport.anfragen.last)
        #expect(abfrage(letzte) == ["limit": "50", "offset": "0", "q": "Telekom", "period": "7d"])
        await a.modell.filterZuruecksetzen()
        let danach = try #require(await a.transport.anfragen.last)
        #expect(abfrage(danach) == ["limit": "50", "offset": "0"])
        #expect(!a.modell.filterAktiv)
    }

    @Test("Zeitraumwerte entsprechen den Parametern der Weboberfläche")
    func zeitraumWerte() {
        #expect(Zeitraum.tag.rawValue == "24h")
        #expect(Zeitraum.woche.rawValue == "7d")
        #expect(Zeitraum.monat.rawValue == "30d")
        #expect(Zeitraum.alle.grenze() == nil)
    }

    @Test("Eine veraltete Antwort überschreibt den neueren Filter nicht")
    func veralteteAntwort() async {
        let a = aufbau { anfrage in
            if anfrage.url?.query?.contains("status=failed") == true {
                return Hilfen.liste([Hilfen.dokument(1, status: "failed")])
            }
            try await Task.sleep(for: .milliseconds(150))
            return Hilfen.liste([Hilfen.dokument(9), Hilfen.dokument(8)])
        }
        let langsam = Task { await a.modell.laden() }
        try? await Task.sleep(for: .milliseconds(30))
        await a.modell.statusWaehlen(.failed)
        await langsam.value
        #expect(a.modell.dokumente.map(\.id) == [1])
    }

    @Test("Netzfehler beim Laden: Meldung statt Liste, Zähler bleiben bestehen")
    func ladenOhneNetz() async {
        let konfiguration = testKonfiguration()
        let client = APIClient(
            konfiguration: konfiguration, transport: TransportOhneNetz(),
            sitzung: AuthSession(konfiguration: konfiguration, transport: TransportOhneNetz(), tokenStore: SpeicherTokenStore("k1")))
        let modell = HistorieModell(client: client, strom: EreignisStrom(client: client, quelle: StromQuelleAttrappe([])))
        await modell.laden()
        #expect(modell.ladezustand == .fehler("Keine Verbindung zum Lector-Dienst. Bitte prüfe das Netz und versuche es erneut."))
        #expect(modell.dokumente.isEmpty)
    }

    // MARK: Seiten

    private nonisolated static func seite(_ ids: ClosedRange<Int>) -> [String] { ids.reversed().map { Hilfen.dokument($0) } }

    @Test("Weitere laden: nächste Seite ab Offset, ohne Doppelte, Ende bei kurzer Seite")
    func weitereLaden() async throws {
        let a = aufbau { anfrage in
            let offset = Int(URLComponents(url: anfrage.url!, resolvingAgainstBaseURL: false)?.queryItems?
                .first { $0.name == "offset" }?.value ?? "0") ?? 0
            switch offset {
            case 0: return Hilfen.liste(Self.seite(51...100))                // 100 … 51
            // Zwischenzeitlich kam ein neuer Vorgang dazu: Die zweite Seite beginnt mit 51 (Doppelter).
            case 50: return Hilfen.liste(Self.seite(2...51))                 // 51 … 2
            default: return Hilfen.liste([Hilfen.dokument(1)], offset: offset)
            }
        }
        await a.modell.laden()
        #expect(a.modell.dokumente.count == 50)
        #expect(a.modell.weitereVerfuegbar)

        await a.modell.weitereLaden()
        #expect(a.modell.dokumente.count == 99)
        #expect(Set(a.modell.dokumente.map(\.id)).count == 99)
        #expect(a.modell.dokumente.first?.id == 100)
        #expect(a.modell.dokumente.last?.id == 2)
        #expect(a.modell.weitereVerfuegbar)

        await a.modell.weitereLaden()
        #expect(a.modell.dokumente.count == 100)
        #expect(!a.modell.weitereVerfuegbar)
        let offsets = await a.transport.anfragen.map { self.abfrage($0)["offset"] }
        #expect(offsets == ["0", "50", "100"])

        // Ohne weitere Seite geht keine Anfrage mehr hinaus.
        await a.modell.weitereLaden()
        #expect(await a.transport.anfragen.count == 3)
    }

    @Test("Ein eingefügter neuer Vorgang verschiebt den Offset der nächsten Seite mit")
    func offsetNachEinfuegen() async throws {
        let a = aufbau { anfrage in
            if anfrage.url?.path == "/api/v1/documents/101" { return Hilfen.detail(Hilfen.dokument(101, status: "pending")) }
            return Hilfen.liste(Self.seite(51...100))
        }
        await a.modell.laden()
        await a.modell.nachladen(101)
        #expect(a.modell.dokumente.first?.id == 101)
        await a.modell.weitereLaden()
        let letzte = try #require(await a.transport.anfragen.last)
        #expect(abfrage(letzte)["offset"] == "51")
    }

    // MARK: Live

    @Test("Zustandswechsel eines bekannten Vorgangs ersetzt die Zeile und verschiebt die Zähler")
    func zustandswechsel() async {
        let a = aufbau { anfrage in
            if anfrage.url?.path == "/api/v1/documents/2" { return Hilfen.detail(Hilfen.dokument(2, status: "done")) }
            return Hilfen.liste([Hilfen.dokument(2, status: "processing", verarbeitet: 1), Hilfen.dokument(1)],
                                zaehler: Hilfen.zaehler(processing: 1, done: 1))
        }
        await a.modell.laden()
        await a.modell.nachladen(2)
        #expect(a.modell.dokumente.first { $0.id == 2 }?.zustand == .done)
        #expect(a.modell.anzahl(.processing) == 0)
        #expect(a.modell.anzahl(.done) == 2)
        #expect(a.modell.version(von: 2) == 1)
    }

    @Test("Ein unbekannter Vorgang erscheint oben; die Zähler kommen frisch vom Dienst")
    func unbekannterVorgang() async {
        let a = aufbau { anfrage in
            switch anfrage.url?.path {
            case "/api/v1/documents/5": return Hilfen.detail(Hilfen.dokument(5, status: "pending"))
            default:
                let neu = anfrage.url?.query?.contains("limit=1&") == true || anfrage.url?.query == "limit=1"
                return Hilfen.liste([Hilfen.dokument(4), Hilfen.dokument(3)],
                                    zaehler: neu ? Hilfen.zaehler(pending: 1, done: 2) : Hilfen.zaehler(done: 2))
            }
        }
        await a.modell.laden()
        await a.modell.nachladen(5)
        #expect(a.modell.dokumente.map(\.id) == [5, 4, 3])
        #expect(a.modell.anzahl(.pending) == 1)
    }

    @Test("Bei aktivem Zustandsfilter fällt ein Vorgang heraus, der nicht mehr passt")
    func fallRausBeiFilter() async {
        let a = aufbau { anfrage in
            if anfrage.url?.path == "/api/v1/documents/2" { return Hilfen.detail(Hilfen.dokument(2, status: "done")) }
            return Hilfen.liste([Hilfen.dokument(2, status: "processing")], zaehler: Hilfen.zaehler(processing: 1))
        }
        await a.modell.statusWaehlen(.processing)
        await a.modell.nachladen(2)
        #expect(a.modell.dokumente.isEmpty)
        #expect(a.modell.anzahl(.processing) == 0)
    }

    @Test("Live: Meldung des Stroms lädt gezielt nach, Wiederaufbau lädt die ganze Liste neu")
    func liveSchleife() async throws {
        let a = aufbau([
            StromVerbindung(pakete: ["data: doc:2\n\n"], ende: .fehler),
            StromVerbindung(),
        ]) { anfrage in
            switch anfrage.url?.path {
            case "/api/v1/documents/2": return Hilfen.detail(Hilfen.dokument(2, status: "done"))
            default: return Hilfen.liste([Hilfen.dokument(2, status: "processing")], zaehler: Hilfen.zaehler(processing: 1))
            }
        }
        await a.modell.laden()
        let aufgabe = Task { await a.modell.liveBetreiben() }
        // Nachladen (Detail) und danach nach dem Wiederaufbau die vollständige Liste.
        #expect(await Hilfen.warten { await a.transport.anzahl(pfad: "/api/v1/documents/2") == 1 })
        #expect(await Hilfen.warten { await a.transport.anzahl(pfad: "/api/v1/documents") == 2 })
        aufgabe.cancel()
        // Die Liste kommt im Wiederaufbau mit dem Stand des Dienstes (hier „processing“).
        #expect(a.modell.dokumente.first?.zustand == .processing)
    }

    @Test("Vordergrund öffnet den Strom, Hintergrund schließt ihn; Rückkehr lädt neu und öffnet erneut")
    func vordergrundUndHintergrund() async {
        let a = aufbau { anfrage in
            Hilfen.liste([Hilfen.dokument(1)], zaehler: Hilfen.zaehler(done: 1))
        }
        a.modell.vordergrund()
        #expect(a.modell.liveAktiv)
        #expect(await Hilfen.warten { a.quelle.oeffnungen == 1 })
        #expect(a.modell.ladezustand == .geladen)
        let ladungen = await a.transport.anzahl(pfad: "/api/v1/documents")
        #expect(ladungen == 1)

        a.modell.hintergrund()
        #expect(!a.modell.liveAktiv)
        #expect(await Hilfen.warten { a.quelle.abgebaut == 1 })

        a.modell.vordergrund()
        #expect(await Hilfen.warten { a.quelle.oeffnungen == 2 })
        #expect(await a.transport.anzahl(pfad: "/api/v1/documents") == 2)
        a.modell.hintergrund()
        #expect(await Hilfen.warten { a.quelle.abgebaut == 2 })
    }

    @Test("Eine Live-Änderung während einer Ladung geht nicht an deren älterer Antwort verloren")
    func aenderungWaehrendLadung() async {
        let a = aufbau { anfrage in
            if anfrage.url?.path == "/api/v1/documents/7" { return Hilfen.detail(Hilfen.dokument(7, status: "done")) }
            let alt = Hilfen.liste([Hilfen.dokument(7, status: "processing")], zaehler: Hilfen.zaehler(processing: 1))
            if anfrage.url?.query?.contains("period=") == true { try await Task.sleep(for: .milliseconds(200)) }
            return alt
        }
        await a.modell.laden()
        let ladung = Task { await a.modell.zeitraumWaehlen(.woche) }
        #expect(await Hilfen.warten { await a.transport.anzahl(pfad: "/api/v1/documents") == 2 })
        // Der Dienst hat die Liste schon gebaut (Stand „processing“), da trifft die Meldung ein.
        await a.modell.nachladen(7)
        await ladung.value
        #expect(a.modell.dokumente.first { $0.id == 7 }?.zustand == .done)
        #expect(a.modell.anzahl(.processing) == 0)
        #expect(a.modell.anzahl(.done) == 1)
        #expect(await a.transport.anzahl(pfad: "/api/v1/documents/7") == 2)
    }
}
