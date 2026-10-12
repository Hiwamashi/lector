import Foundation
import Observation

/// Listenmodell der Historie: Zähler je Zustand, Vorgänge (neueste zuerst), Filter, Nachladen
/// in Seiten und Live-Aktualisierung über den Ereignisstrom (D11).
///
/// Die Zähler kommen vom Dienst und gelten immer für den ganzen Bestand, nie für die Filter.
/// Eine Änderung am Filter lädt die Liste neu; Antworten veralteter Anfragen werden verworfen.
@MainActor
@Observable
final class HistorieModell {
    enum Ladezustand: Equatable {
        case unbekannt
        case laedt
        case geladen
        case fehler(String)
    }

    /// Vorgänge je Anfrage. Der Dienst erlaubt bis 200.
    static let seitengroesse = 50
    private static let hoechstzahl = 200

    /// Reihenfolge der Zähler wie die Kacheln der Weboberfläche.
    static let zaehlerReihenfolge: [DokumentZustand] = [.processing, .pending, .blocked, .done, .skippedErechnung, .failed]

    private(set) var dokumente: [DokumentDTO] = []
    private(set) var zaehler: [DokumentZustand: Int] = [:]
    private(set) var statusFilter: DokumentZustand?
    private(set) var suche = ""
    private(set) var zeitraum: Zeitraum = .alle
    private(set) var ladezustand: Ladezustand = .unbekannt
    private(set) var weitereVerfuegbar = false
    private(set) var laedtWeitere = false
    /// Meldung zum Nachladen weiterer Seiten; die Liste selbst bleibt stehen.
    private(set) var weitereFehler: String?
    private(set) var liveAktiv = false
    /// Zählt je Vorgang die Meldungen des Stroms; die Detailansicht lädt daran neu.
    private(set) var versionen: [Int: Int] = [:]

    private let client: APIClient
    private let strom: EreignisStrom
    private var generation = 0
    /// Stelle der Liste auf dem Dienst, ab der die nächste Seite beginnt.
    private var naechsterOffset = 0
    private var liveAufgabe: Task<Void, Never>?
    /// Laufende `laden()`-Aufrufe. Währenddessen eingearbeitete Live-Meldungen können von einer
    /// Antwort überschrieben werden, die der Dienst vor der Änderung gebaut hat.
    private var laufendeLadungen = 0
    /// Während einer Ladung gemeldete Vorgänge; nach dem Setzen der Antwort gezielt neu geholt.
    private var vorgemerkt: Set<Int> = []

    init(client: APIClient, strom: EreignisStrom) {
        self.client = client
        self.strom = strom
    }

    var filterAktiv: Bool { statusFilter != nil || !suche.isEmpty || zeitraum != .alle }

    func anzahl(_ zustand: DokumentZustand) -> Int { zaehler[zustand] ?? 0 }

    func version(von id: Int) -> Int { versionen[id] ?? 0 }

    // MARK: - Filter

    /// Wählt den Zustandsfilter; derselbe Zustand ein zweites Mal hebt ihn auf.
    func statusWaehlen(_ zustand: DokumentZustand?) async {
        statusFilter = (zustand == statusFilter) ? nil : zustand
        await laden()
    }

    func sucheSetzen(_ text: String) async {
        let neu = text.trimmingCharacters(in: .whitespaces)
        guard neu != suche else { return }
        suche = neu
        await laden()
    }

    func zeitraumWaehlen(_ neu: Zeitraum) async {
        guard neu != zeitraum else { return }
        zeitraum = neu
        await laden()
    }

    func filterZuruecksetzen() async {
        statusFilter = nil
        suche = ""
        zeitraum = .alle
        await laden()
    }

    // MARK: - Laden

    enum Umfang {
        /// Erste Seite; setzt die Liste zurück (Filterwechsel, Herunterziehen).
        case ersteSeite
        /// So viele Vorgänge, wie schon geladen sind (Wiederaufbau, Rückkehr in den Vordergrund).
        case behalten
    }

    /// Lädt die Liste und die Zähler neu. `still`: keine Ladeanzeige, wenn schon etwas zu sehen ist.
    func laden(umfang: Umfang = .ersteSeite, still: Bool = false) async {
        laufendeLadungen += 1
        let angewendet = await ladenKern(umfang: umfang, still: still)
        laufendeLadungen -= 1
        guard angewendet else { return }
        let ids = vorgemerkt.sorted()
        vorgemerkt = []
        for id in ids { await nachladen(id) }
    }

    /// `true`, wenn die Antwort in die Liste übernommen wurde (nicht veraltet, kein Fehler).
    private func ladenKern(umfang: Umfang, still: Bool) async -> Bool {
        generation += 1
        let meine = generation
        weitereFehler = nil
        if !(still && ladezustand == .geladen) { ladezustand = .laedt }
        let limit = switch umfang {
        case .ersteSeite: Self.seitengroesse
        case .behalten: min(Self.hoechstzahl, max(Self.seitengroesse, dokumente.count))
        }
        do {
            let liste = try await seite(offset: 0, limit: limit)
            guard meine == generation else { return false }
            dokumente = Self.eindeutig(liste.documents)
            naechsterOffset = liste.documents.count
            weitereVerfuegbar = liste.documents.count >= limit
            zaehlerUebernehmen(liste.counts)
            ladezustand = .geladen
            return true
        } catch {
            guard meine == generation, !Task.isCancelled else { return false }
            if let text = HistorieFehler.text(fuer: error) {
                ladezustand = .fehler(text)
            } else {
                ladezustand = dokumente.isEmpty && zaehler.isEmpty ? .unbekannt : .geladen
            }
        }
        return false
    }

    /// Hängt die nächste Seite an. Doppelte (durch zwischenzeitlich neue Vorgänge) bleiben draußen.
    func weitereLaden() async {
        guard weitereVerfuegbar, !laedtWeitere, ladezustand == .geladen else { return }
        laedtWeitere = true
        weitereFehler = nil
        defer { laedtWeitere = false }
        let meine = generation
        do {
            let liste = try await seite(offset: naechsterOffset, limit: Self.seitengroesse)
            guard meine == generation else { return }
            let bekannt = Set(dokumente.map(\.id))
            dokumente += Self.eindeutig(liste.documents).filter { !bekannt.contains($0.id) }
            naechsterOffset += liste.documents.count
            weitereVerfuegbar = liste.documents.count >= Self.seitengroesse
            zaehlerUebernehmen(liste.counts)
        } catch {
            guard meine == generation, !Task.isCancelled else { return }
            weitereFehler = HistorieFehler.text(fuer: error)
        }
    }

    private func seite(offset: Int, limit: Int) async throws -> DokumentListeDTO {
        var query = [URLQueryItem(name: "limit", value: String(limit)), URLQueryItem(name: "offset", value: String(offset))]
        if let statusFilter { query.append(URLQueryItem(name: "status", value: statusFilter.rawValue)) }
        if !suche.isEmpty { query.append(URLQueryItem(name: "q", value: suche)) }
        if zeitraum != .alle { query.append(URLQueryItem(name: "period", value: zeitraum.rawValue)) }
        return try await client.anfrage("GET", "/api/v1/documents", query: query)
    }

    private static func eindeutig(_ liste: [DokumentDTO]) -> [DokumentDTO] {
        var gesehen = Set<Int>()
        return liste.filter { gesehen.insert($0.id).inserted }
    }

    private func zaehlerUebernehmen(_ neu: [String: Int]) {
        var ergebnis: [DokumentZustand: Int] = [:]
        for zustand in DokumentZustand.allCases { ergebnis[zustand] = neu[zustand.rawValue] ?? 0 }
        zaehler = ergebnis
    }

    /// Nur die Zähler neu holen (ein Vorgang ist aufgetaucht, dessen alten Zustand wir nicht kennen).
    private func zaehlerNachladen() async {
        do {
            let liste: DokumentListeDTO = try await client.anfrage(
                "GET", "/api/v1/documents", query: [URLQueryItem(name: "limit", value: "1")])
            zaehlerUebernehmen(liste.counts)
        } catch {
            // Beim nächsten Laden stimmen sie wieder.
        }
    }

    // MARK: - Live

    /// Beginnt die Live-Aktualisierung (App im Vordergrund). Lädt vorher den Stand, damit nichts
    /// aus der Zeit im Hintergrund fehlt. Ohne Wirkung, wenn sie schon läuft.
    func vordergrund() {
        guard liveAufgabe == nil else { return }
        liveAktiv = true
        let schonGeladen = ladezustand == .geladen
        liveAufgabe = Task { [weak self] in
            guard let self else { return }
            if schonGeladen {
                await laden(umfang: .behalten, still: true)
            } else {
                await laden()
            }
            await liveBetreiben()
        }
    }

    /// Beendet die Live-Aktualisierung (App im Hintergrund); die Verbindung wird geschlossen.
    func hintergrund() {
        liveAufgabe?.cancel()
        liveAufgabe = nil
        liveAktiv = false
    }

    /// Verarbeitet die Meldungen des Stroms, bis die Aufgabe abgebrochen wird oder der Strom endet.
    func liveBetreiben() async {
        for await meldung in strom.meldungen() {
            switch meldung {
            case .dokument(let id):
                await nachladen(id)
            case .wiederaufgebaut:
                await laden(umfang: .behalten, still: true)
            }
        }
    }

    /// Lädt genau einen Vorgang nach und fügt ihn ein bzw. aktualisiert ihn.
    func nachladen(_ id: Int) async {
        if laufendeLadungen > 0 { vorgemerkt.insert(id) }
        do {
            let detail: DokumentDetailDTO = try await client.anfrage("GET", "/api/v1/documents/\(id)")
            versionen[id, default: 0] += 1
            await dokumentUebernehmen(detail.document)
        } catch {
            // Eine verpasste Meldung holt der nächste Wiederaufbau bzw. das manuelle Laden nach.
        }
    }

    /// Übernimmt den neuen Stand eines Vorgangs in Liste und Zähler (auch aus der Detailansicht).
    func dokumentUebernehmen(_ neu: DokumentDTO) async {
        if let index = dokumente.firstIndex(where: { $0.id == neu.id }) {
            let alt = dokumente[index]
            if let statusFilter, neu.zustand != statusFilter {
                dokumente.remove(at: index)
                naechsterOffset = max(0, naechsterOffset - 1)
            } else {
                dokumente[index] = neu
            }
            if alt.status != neu.status { zaehlerVerschieben(von: alt.zustand, nach: neu.zustand) }
            return
        }
        guard passt(neu), imFenster(neu) else {
            // Ein Vorgang außerhalb der geladenen Liste: Der alte Zustand ist unbekannt.
            await zaehlerNachladen()
            return
        }
        let stelle = dokumente.firstIndex(where: { $0.id < neu.id }) ?? dokumente.count
        dokumente.insert(neu, at: stelle)
        naechsterOffset += 1
        await zaehlerNachladen()
    }

    private func zaehlerVerschieben(von alt: DokumentZustand?, nach neu: DokumentZustand?) {
        if let alt { zaehler[alt] = max(0, (zaehler[alt] ?? 0) - 1) }
        if let neu { zaehler[neu] = (zaehler[neu] ?? 0) + 1 }
    }

    private func passt(_ dokument: DokumentDTO) -> Bool {
        if let statusFilter, dokument.zustand != statusFilter { return false }
        if let grenze = zeitraum.grenze(), let angelegt = dokument.createdAt, angelegt < grenze { return false }
        if !suche.isEmpty, !dokument.originalFilename.localizedCaseInsensitiveContains(suche) { return false }
        return true
    }

    /// Ein unbekannter Vorgang gehört in die Liste, wenn er in den schon geladenen Bereich fällt:
    /// neuer als der älteste geladene, oder es ist ohnehin alles geladen.
    private func imFenster(_ dokument: DokumentDTO) -> Bool {
        guard let aeltester = dokumente.last else { return true }
        return !weitereVerfuegbar || dokument.id > aeltester.id
    }
}
