import Foundation
import Testing
@testable import Lector

@Suite("Ereignisstrom: Zeilen, Keepalive, Wiederaufbau, Hintergrund")
struct EreignisStromTests {
    private func strom(_ verbindungen: [StromVerbindung], schluessel: String? = "k1",
                       wartezeiten: [Duration] = EreignisStrom.standardWartezeiten)
        -> (EreignisStrom, StromQuelleAttrappe, PausenProtokoll, TransportAttrappe, SpeicherTokenStore) {
        let transport = TransportAttrappe { _ in .leer(204) }
        let store = SpeicherTokenStore(schluessel)
        let konfiguration = testKonfiguration()
        let sitzung = AuthSession(konfiguration: konfiguration, transport: transport, tokenStore: store)
        let client = APIClient(konfiguration: konfiguration, transport: transport, sitzung: sitzung)
        let quelle = StromQuelleAttrappe(verbindungen)
        let pausen = PausenProtokoll()
        return (EreignisStrom(client: client, quelle: quelle, wartezeiten: wartezeiten, pause: pausen.pause),
                quelle, pausen, transport, store)
    }

    /// Liest `anzahl` Meldungen; bricht nach 5 s ab.
    private func lesen(_ strom: EreignisStrom, _ anzahl: Int) async -> [StromMeldung] {
        await withTaskGroup(of: [StromMeldung].self) { gruppe in
            gruppe.addTask {
                var ergebnis: [StromMeldung] = []
                for await meldung in strom.meldungen() {
                    ergebnis.append(meldung)
                    if ergebnis.count == anzahl { break }
                }
                return ergebnis
            }
            gruppe.addTask { try? await Task.sleep(for: .seconds(5)); return [] }
            let erste = await gruppe.next() ?? []
            gruppe.cancelAll()
            return erste
        }
    }

    // MARK: Zeilen

    @Test("Zeilenleser: Vorgang, Keepalive und fremde Präfixe")
    func zeilen() {
        func lesen(_ text: String) -> [ZeilenLeser.Zeile] {
            var leser = ZeilenLeser()
            return text.utf8.compactMap { leser.aufnehmen($0) }
        }
        #expect(lesen("data: doc:42\n\n") == [.dokument(42), .ignoriert])
        #expect(lesen(": keepalive\n\n") == [.kommentar, .ignoriert])
        #expect(lesen("data: inv:7\n") == [.ignoriert])
        #expect(lesen("data: rec:3\n") == [.ignoriert])
        #expect(lesen("data: batch:recipient\n") == [.ignoriert])
        #expect(lesen("data: doc:abc\n") == [.ignoriert])
        #expect(lesen("data:doc:5\r\n") == [.dokument(5)])
        #expect(lesen("data: doc:6\r\n\r\n") == [.dokument(6), .ignoriert])
    }

    @Test("Ereignis, Keepalive und fremde Präfixe: nur Vorgänge werden gemeldet")
    func ereignisUndKeepalive() async {
        let (strom, quelle, _, _, _) = strom([
            StromVerbindung(pakete: [": connected\n\n", "data: doc:7\n\n", ": keepalive\n\n", "data: inv:9\n\n",
                                     "data: batch:recipient\n\n", "data: doc:8\n\n"]),
        ])
        let meldungen = await lesen(strom, 2)
        #expect(meldungen == [.dokument(7), .dokument(8)])
        #expect(quelle.oeffnungen == 1)
        let anfrage = quelle.anfragen.first
        #expect(anfrage?.url?.path == "/events")
        #expect(anfrage?.bearer == "k1")
        #expect(anfrage?.value(forHTTPHeaderField: "Accept") == "text/event-stream")
    }

    @Test("Eine Zeile über mehrere Pakete hinweg wird zusammengesetzt")
    func geteilteZeile() async {
        let (strom, _, _, _, _) = strom([StromVerbindung(pakete: ["da", "ta: do", "c:1", "2\n", "\n"])])
        #expect(await lesen(strom, 1) == [.dokument(12)])
    }

    // MARK: Wiederaufbau

    @Test("Abbruch: neue Verbindung nach Wartezeit, danach „wiederaufgebaut“ und weiter")
    func wiederaufbau() async {
        let (strom, quelle, pausen, _, _) = strom([
            StromVerbindung(pakete: ["data: doc:1\n\n"], ende: .fehler),
            StromVerbindung(pakete: ["data: doc:2\n\n"], ende: .offen),
        ])
        let meldungen = await lesen(strom, 3)
        #expect(meldungen == [.dokument(1), .wiederaufgebaut, .dokument(2)])
        #expect(quelle.oeffnungen == 2)
        #expect(pausen.dauern == [.seconds(1)])
    }

    @Test("Auch ein sauberes Ende des Stroms führt zum Wiederaufbau")
    func sauberesEnde() async {
        let (strom, _, _, _, _) = strom([
            StromVerbindung(pakete: [": connected\n\n"], ende: .sauber),
            StromVerbindung(pakete: ["data: doc:5\n\n"]),
        ])
        #expect(await lesen(strom, 2) == [.wiederaufgebaut, .dokument(5)])
    }

    @Test("Die Wartezeit wächst 1, 2, 5, 10, 30 s und bleibt bei 30 s")
    func wartezeiten() async {
        let ausfall = StromVerbindung(status: 503, ende: .sauber)
        let (strom, quelle, pausen, _, _) = strom(Array(repeating: ausfall, count: 7))
        let aufgabe = Task { for await _ in strom.meldungen() {} }
        let erreicht = await Hilfen.warten { quelle.oeffnungen >= 8 }
        aufgabe.cancel()
        #expect(erreicht)
        #expect(Array(pausen.dauern.prefix(7)) == [.seconds(1), .seconds(2), .seconds(5), .seconds(10), .seconds(30), .seconds(30), .seconds(30)])
    }

    @Test("Nach einer Verbindung mit Daten beginnt die Wartezeit wieder bei 1 s")
    func wartezeitZurueck() async {
        let ausfall = StromVerbindung(status: 503, ende: .sauber)
        let (strom, quelle, pausen, _, _) = strom([
            ausfall, ausfall, ausfall,
            StromVerbindung(pakete: [": connected\n\n"], ende: .sauber),
            ausfall,
        ])
        let aufgabe = Task { for await _ in strom.meldungen() {} }
        let erreicht = await Hilfen.warten { quelle.oeffnungen >= 6 }
        aufgabe.cancel()
        #expect(erreicht)
        #expect(Array(pausen.dauern.prefix(5)) == [.seconds(1), .seconds(2), .seconds(5), .seconds(1), .seconds(2)])
    }

    @Test("Netzfehler beim Öffnen wird wie ein Abbruch behandelt; „wiederaufgebaut“ erst nach Erfolg")
    func oeffnenScheitert() async {
        let (strom, _, pausen, _, _) = strom([
            StromVerbindung(status: 502, ende: .sauber),
            StromVerbindung(pakete: ["data: doc:3\n\n"]),
        ])
        #expect(await lesen(strom, 2) == [.wiederaufgebaut, .dokument(3)])
        #expect(pausen.dauern == [.seconds(1)])
    }

    @Test("401 beendet den Strom ohne Wiederaufbau und verwirft den Schlüssel")
    func nichtAngemeldet() async {
        let (strom, quelle, pausen, _, store) = strom([StromVerbindung(status: 401, pakete: [#"{"error":{"code":"not_authenticated","message":"x"}}"#], ende: .sauber)])
        var meldungen: [StromMeldung] = []
        for await meldung in strom.meldungen() { meldungen.append(meldung) }
        #expect(meldungen.isEmpty)
        #expect(quelle.oeffnungen == 1)
        #expect(pausen.dauern.isEmpty)
        #expect(store.lesen() == nil)
    }

    // MARK: Hintergrund

    @Test("Abbrechen des Verbrauchers (Wechsel in den Hintergrund) schließt die Verbindung")
    func abbruch() async {
        let (strom, quelle, _, _, _) = strom([StromVerbindung(pakete: [": connected\n\n"])])
        let aufgabe = Task { for await _ in strom.meldungen() {} }
        #expect(await Hilfen.warten { quelle.oeffnungen == 1 })
        aufgabe.cancel()
        #expect(await Hilfen.warten { quelle.abgebaut == 1 })
        // Danach öffnet sich nichts mehr.
        try? await Task.sleep(for: .milliseconds(100))
        #expect(quelle.oeffnungen == 1)
    }
}
