import Foundation
import Observation

/// Ablauf der Share Extension ohne Oberfläche: Voraussetzungen prüfen, jede geteilte Datei nach
/// der Formatweiche vorbereiten und einzeln hochladen, Fortschritt und Ergebnis je Datei führen.
/// Nichts bleibt über das Schließen hinaus liegen: `aufraeumen()` löscht den Arbeitsordner, und es
/// gibt keine Warteschlange, die später nachholt.
@MainActor
@Observable
final class TeilenModell {
    enum Voraussetzung: Equatable {
        case erfuellt
        case nichtEingerichtet
        case nichtAngemeldet
    }

    enum Status: Equatable {
        case wartet
        case vorbereiten
        case senden(Double)
        case angenommen
        /// Vom Dienst oder von der Formatweiche abgewiesen; ein erneutes Senden hilft nicht.
        case abgewiesen(String)
        /// Technisch gescheitert (kein Netz, Serverfehler); „Erneut senden“ ist möglich.
        case fehlgeschlagen(String)
    }

    struct Eintrag: Identifiable {
        let id = UUID()
        let dateiname: String
        fileprivate let quelle: any TeilenQuelle
        fileprivate(set) var status: Status = .wartet
        fileprivate var vorbereitet: UploadDatei?
    }

    private(set) var eintraege: [Eintrag]
    private(set) var laeuft = false
    /// Gesetzt, wenn die Sitzung während des Sendens abgelaufen ist.
    private(set) var anmeldungAbgelaufen = false

    private let client: APIClient
    private let konfiguration: ServerKonfiguration
    private let tokenStore: any TokenStore
    private let arbeitsordner: URL

    init(
        quellen: [any TeilenQuelle], client: APIClient, konfiguration: ServerKonfiguration = ServerKonfiguration(),
        tokenStore: any TokenStore
    ) {
        eintraege = quellen.map { Eintrag(dateiname: $0.dateiname, quelle: $0) }
        self.client = client
        self.konfiguration = konfiguration
        self.tokenStore = tokenStore
        arbeitsordner = FileManager.default.temporaryDirectory
            .appendingPathComponent("teilen-\(UUID().uuidString)", isDirectory: true)
    }

    /// Ohne Adresse oder (im Modus `paperless`) ohne Schlüssel wird nichts übergeben.
    var voraussetzung: Voraussetzung {
        guard konfiguration.adresse != nil else { return .nichtEingerichtet }
        if konfiguration.authModus != AuthModus.none, tokenStore.lesen() == nil { return .nichtAngemeldet }
        return .erfuellt
    }

    /// Alle Einträge sind angenommen oder abgewiesen; nichts läuft, nichts ist erneut sendbar.
    var abgeschlossen: Bool {
        !laeuft && eintraege.allSatisfy {
            switch $0.status {
            case .angenommen, .abgewiesen: true
            default: false
            }
        }
    }

    var kannErneutSenden: Bool {
        !laeuft && voraussetzung == .erfuellt
            && eintraege.contains { if case .fehlgeschlagen = $0.status { true } else { false } }
    }

    // MARK: - Ablauf

    /// Bereitet alle Einträge vor und lädt sie nacheinander hoch. Bei fehlender Einrichtung oder
    /// Anmeldung passiert nichts.
    func starten() async {
        guard voraussetzung == .erfuellt, !laeuft else { return }
        await durchlaufen(nur: { _ in true })
    }

    /// Sendet die technisch gescheiterten Einträge noch einmal (die Dateien liegen noch vor).
    func erneutSenden() async {
        guard kannErneutSenden else { return }
        anmeldungAbgelaufen = false
        await durchlaufen(nur: { if case .fehlgeschlagen = $0.status { true } else { false } })
    }

    func aufraeumen() {
        try? FileManager.default.removeItem(at: arbeitsordner)
    }

    private func durchlaufen(nur auswahl: (Eintrag) -> Bool) async {
        laeuft = true
        defer { laeuft = false }
        try? FileManager.default.createDirectory(at: arbeitsordner, withIntermediateDirectories: true)

        for index in eintraege.indices where auswahl(eintraege[index]) {
            if Task.isCancelled { return }
            if anmeldungAbgelaufen {
                eintraege[index].status = .fehlgeschlagen("Bitte in der Lector-App neu anmelden.")
                continue
            }
            await verarbeiten(index)
        }
    }

    private func verarbeiten(_ index: Int) async {
        if eintraege[index].vorbereitet == nil {
            eintraege[index].status = .vorbereiten
            do {
                eintraege[index].vorbereitet = try await TeilenVorbereitung.vorbereiten(
                    eintraege[index].quelle, arbeitsordner: arbeitsordner)
            } catch TeilenFehler.nichtUnterstuetzt {
                eintraege[index].status = .abgewiesen("Dateityp wird nicht unterstützt")
                return
            } catch {
                eintraege[index].status = .abgewiesen("Datei konnte nicht gelesen werden")
                return
            }
        }
        guard let datei = eintraege[index].vorbereitet else { return }

        eintraege[index].status = .senden(0)
        let id = eintraege[index].id
        do {
            let ergebnis = try await client.hochladen(datei) { [weak self] anteil in
                Task { @MainActor in self?.fortschritt(anteil, fuer: id) }
            }
            eintraege[index].status = ergebnis.accepted ? .angenommen : .abgewiesen(ergebnis.ablehnungstext)
            // Nach einem Ergebnis des Dienstes wird die Datei nicht mehr gebraucht.
            try? FileManager.default.removeItem(at: datei.url)
            eintraege[index].vorbereitet = nil
        } catch APIFehler.nichtAngemeldet {
            anmeldungAbgelaufen = true
            eintraege[index].status = .fehlgeschlagen("Bitte in der Lector-App neu anmelden.")
        } catch APIFehler.keinNetz {
            eintraege[index].status = .fehlgeschlagen("Keine Verbindung zu Lector.")
        } catch APIFehler.server(_, _, let meldung) {
            eintraege[index].status = .fehlgeschlagen(meldung ?? "Der Dienst hat die Datei nicht angenommen.")
        } catch is CancellationError {
            eintraege[index].status = .fehlgeschlagen("Abgebrochen.")
        } catch {
            eintraege[index].status = .fehlgeschlagen("Senden fehlgeschlagen.")
        }
    }

    private func fortschritt(_ anteil: Double, fuer id: UUID) {
        guard let index = eintraege.firstIndex(where: { $0.id == id }),
              case .senden = eintraege[index].status else { return }
        eintraege[index].status = .senden(anteil)
    }
}
