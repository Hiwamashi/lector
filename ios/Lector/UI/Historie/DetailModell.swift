import Foundation
import Observation

/// Modell der Detailansicht eines Vorgangs: Angaben, Verlauf und die Entscheidung über einen
/// angehaltenen Vorgang (Freigeben/Verwerfen).
@MainActor
@Observable
final class DetailModell {
    enum Entscheidung: Equatable {
        case freigeben
        case verwerfen

        var pfad: String {
            switch self {
            case .freigeben: "release"
            case .verwerfen: "discard"
            }
        }
    }

    private(set) var dokument: DokumentDTO
    /// Verlauf in zeitlicher Reihenfolge (älteste zuerst).
    private(set) var ereignisse: [EreignisDTO] = []
    private(set) var seitenGrenze: Int?
    private(set) var versuchsGrenze: Int?
    private(set) var geladen = false
    private(set) var laedt = false
    /// Fehler beim Laden oder Entscheiden; nicht der 409-Fall.
    private(set) var fehler: String?
    /// Der Vorgang war nicht mehr angehalten (409). Der Stand wurde nachgeladen.
    private(set) var hinweis: String?
    private(set) var entscheidetGerade = false

    private let client: APIClient
    /// Meldet jeden frischen Stand an die Historie (Liste und Zähler).
    private let aktualisiert: @MainActor (DokumentDTO) async -> Void

    init(dokument: DokumentDTO, client: APIClient, aktualisiert: @escaping @MainActor (DokumentDTO) async -> Void = { _ in }) {
        self.dokument = dokument
        self.client = client
        self.aktualisiert = aktualisiert
    }

    var istAngehalten: Bool { dokument.zustand == .blocked }

    func laden() async {
        laedt = true
        defer { laedt = false }
        do {
            let detail: DokumentDetailDTO = try await client.anfrage("GET", "/api/v1/documents/\(dokument.id)")
            guard !Task.isCancelled else { return }
            uebernehmen(detail)
            fehler = nil
            await aktualisiert(detail.document)
        } catch {
            guard !Task.isCancelled else { return }
            fehler = HistorieFehler.text(fuer: error)
        }
    }

    private func uebernehmen(_ detail: DokumentDetailDTO) {
        dokument = detail.document
        ereignisse = detail.events.sorted { ($0.timestamp, $0.id) < ($1.timestamp, $1.id) }
        seitenGrenze = detail.pageLimit
        versuchsGrenze = detail.retryMax
        geladen = true
    }

    /// Sendet die bestätigte Entscheidung. Bei 409 („nicht angehalten“) erscheint ein Hinweis und
    /// der Stand wird nachgeladen.
    func entscheiden(_ entscheidung: Entscheidung) async {
        guard !entscheidetGerade else { return }
        entscheidetGerade = true
        fehler = nil
        hinweis = nil
        defer { entscheidetGerade = false }
        do {
            let antwort: DokumentAntwortDTO = try await client.anfrage(
                "POST", "/api/v1/documents/\(dokument.id)/\(entscheidung.pfad)")
            dokument = antwort.document
            await aktualisiert(antwort.document)
            await laden()
        } catch APIFehler.server(_, .nichtAngehalten, _) {
            hinweis = "Der Vorgang ist nicht mehr angehalten. Er wurde inzwischen anderweitig entschieden."
            await laden()
        } catch {
            guard !Task.isCancelled else { return }
            fehler = HistorieFehler.text(fuer: error)
        }
    }

    func hinweisSchliessen() { hinweis = nil }
}
