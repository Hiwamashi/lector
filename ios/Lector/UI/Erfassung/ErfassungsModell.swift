import Foundation
import Observation

/// Ablauf einer Übergabe aus Scanner oder Fotoauswahl (D12) ohne Oberfläche: Seiten holen, zu einem
/// PDF zusammenfassen, hochladen, Ergebnis führen. Nichts bleibt über das Schließen hinaus liegen:
/// `aufraeumen()` löscht den Arbeitsordner, sobald das Übergabeblatt geschlossen ist (nicht früher),
/// und es gibt keine Warteschlange, die später nachholt.
@MainActor
@Observable
final class ErfassungsModell: Identifiable {
    enum Zustand: Equatable {
        case bereit
        /// Seiten werden geholt und zum PDF zusammengefasst.
        case vorbereiten
        case senden(Double)
        /// Vom Dienst angenommen; die Verarbeitung läuft dort weiter, darauf wird nicht gewartet.
        case uebergeben
        /// Vom Dienst abgelehnt; ein erneutes Senden hilft nicht.
        case abgewiesen(String)
        /// Technisch gescheitert (kein Netz, Serverfehler); „Erneut senden“ ist möglich.
        case fehlgeschlagen(String)
    }

    nonisolated var id: ObjectIdentifier { ObjectIdentifier(self) }

    private(set) var zustand: Zustand = .bereit
    private(set) var dateiname: String?
    /// Seitenzahl des erzeugten PDFs, sobald es vorliegt.
    private(set) var seitenzahl: Int?

    private let client: APIClient
    private let seitenQuelle: @MainActor (URL) async throws -> [PDFSeite]
    let arbeitsordner: URL
    private var vorbereitet: UploadDatei?
    /// Wohin der Upload seinen Multipart-Rumpf schreibt; nur Tests weichen vom Standard ab.
    private let rumpfOrdner: URL

    /// `seiten` liefert die Seiten erst beim Start (Fotos werden erst dann geladen). Es bekommt den
    /// Arbeitsordner, um Bilddaten als Datei abzulegen statt alle zugleich im Speicher zu halten.
    init(
        client: APIClient, rumpfOrdner: URL = FileManager.default.temporaryDirectory,
        seiten: @escaping @MainActor (URL) async throws -> [PDFSeite]
    ) {
        self.client = client
        self.rumpfOrdner = rumpfOrdner
        seitenQuelle = seiten
        arbeitsordner = FileManager.default.temporaryDirectory
            .appendingPathComponent("erfassung-\(UUID().uuidString)", isDirectory: true)
    }

    /// „Erneut senden“ ist möglich, wenn der letzte Versuch technisch scheiterte.
    var kannErneutSenden: Bool {
        if case .fehlgeschlagen = zustand { return true }
        return false
    }

    var laeuft: Bool {
        switch zustand {
        case .vorbereiten, .senden: true
        default: false
        }
    }

    // MARK: - Ablauf

    /// Holt die Seiten, erzeugt das PDF und lädt es hoch. Läuft nur einmal je Modell.
    func starten() async {
        guard zustand == .bereit else { return }
        zustand = .vorbereiten
        do {
            try FileManager.default.createDirectory(at: arbeitsordner, withIntermediateDirectories: true)
            let seiten = try await seitenQuelle(arbeitsordner)
            let name = PDFErzeuger.dateiname()
            let ziel = arbeitsordner.appendingPathComponent(name)
            try await Self.pdfErzeugen(seiten, ziel)
            // Das Zeichnen ignoriert den Abbruch; danach darf nichts mehr hochgeladen werden.
            try Task.checkCancellation()
            seitenzahl = seiten.count
            dateiname = name
            vorbereitet = UploadDatei(url: ziel, dateiname: name, medientyp: "application/pdf")
        } catch is CancellationError {
            // Zurück auf `bereit`, damit eine erneut präsentierte Ansicht von vorn beginnen kann.
            zustand = .bereit
            return
        } catch {
            zustand = .abgewiesen("Die Bilder konnten nicht zu einem PDF zusammengefasst werden.")
            return
        }
        await senden()
    }

    /// Sendet das vorbereitete PDF noch einmal (die Datei liegt noch vor).
    func erneutSenden() async {
        guard kannErneutSenden, vorbereitet != nil else { return }
        await senden()
    }

    /// Löscht liegengebliebene `erfassung-*`-Ordner in `verzeichnis` außer `ausser` (Reste nach
    /// Absturz oder wenn das Blatt nie geschlossen wurde). Fehler werden still ignoriert.
    static func verwaisteAufraeumen(ausser: URL?, in verzeichnis: URL = FileManager.default.temporaryDirectory) {
        let dateien = FileManager.default
        guard let eintraege = try? dateien.contentsOfDirectory(atPath: verzeichnis.path) else { return }
        let geschuetzt = ausser?.standardizedFileURL.resolvingSymlinksInPath().path
        for name in eintraege where name.hasPrefix("erfassung-") {
            let url = verzeichnis.appendingPathComponent(name, isDirectory: true)
            if url.standardizedFileURL.resolvingSymlinksInPath().path == geschuetzt { continue }
            try? dateien.removeItem(at: url)
        }
    }

    func aufraeumen() {
        try? FileManager.default.removeItem(at: arbeitsordner)
        vorbereitet = nil
    }

    private func senden() async {
        guard let datei = vorbereitet else { return }
        zustand = .senden(0)
        do {
            let ergebnis = try await client.hochladen(datei, fortschritt: { [weak self] anteil in
                Task { @MainActor in self?.fortschritt(anteil) }
            }, rumpfOrdner: rumpfOrdner)
            zustand = ergebnis.accepted ? .uebergeben : .abgewiesen(ergebnis.ablehnungstext)
            // Nach einem Ergebnis des Dienstes wird die Datei nicht mehr gebraucht.
            try? FileManager.default.removeItem(at: datei.url)
            vorbereitet = nil
        } catch UploadFehler.dateiNichtLesbar {
            zustand = .abgewiesen("Der vorbereitete Beleg liegt nicht mehr vor. Bitte neu erfassen.")
            vorbereitet = nil
        } catch UploadFehler.rumpfNichtSchreibbar {
            // Die Datei liegt noch vor (`vorbereitet` bleibt), „Erneut senden“ bleibt möglich.
            zustand = .fehlgeschlagen("Der Beleg konnte nicht zum Senden vorbereitet werden. Ist der Gerätespeicher voll?")
        } catch APIFehler.nichtAngemeldet {
            zustand = .fehlgeschlagen("Bitte neu anmelden.")
        } catch APIFehler.keinNetz {
            zustand = .fehlgeschlagen("Keine Verbindung zu Lector.")
        } catch APIFehler.server(_, _, let meldung) {
            zustand = .fehlgeschlagen(meldung ?? "Der Dienst hat die Datei nicht angenommen.")
        } catch is CancellationError {
            zustand = .fehlgeschlagen("Abgebrochen.")
        } catch {
            zustand = .fehlgeschlagen("Senden fehlgeschlagen.")
        }
    }

    private func fortschritt(_ anteil: Double) {
        guard case .senden = zustand else { return }
        zustand = .senden(anteil)
    }

    /// Das Zeichnen läuft abseits des Hauptthreads, damit die Oberfläche bedienbar bleibt.
    private nonisolated static func pdfErzeugen(_ seiten: [PDFSeite], _ ziel: URL) async throws {
        try await Task.detached(priority: .userInitiated) {
            try PDFErzeuger.erzeugen(seiten: seiten, nach: ziel)
        }.value
    }
}
