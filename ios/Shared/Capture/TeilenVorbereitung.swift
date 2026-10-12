import Foundation
import UniformTypeIdentifiers

/// Die vorbereitete Datei samt Name und Medientyp für den Upload.
struct UploadDatei: Equatable, Sendable {
    let url: URL
    let dateiname: String
    let medientyp: String
}

/// Eine geteilte Datei vor der Übergabe. In der Share Extension ist das ein `NSItemProvider`,
/// in Tests eine Attrappe.
protocol TeilenQuelle: Sendable {
    var dateiname: String { get }
    var typen: [UTType] { get }
    /// Legt eine Kopie der Datei im Ordner `ziel` ab (Datei, nicht im Speicher) und liefert deren URL.
    func kopieren(typ: UTType, nach ziel: URL) async throws -> URL
}

enum TeilenFehler: Error, Equatable {
    /// Dateiart wird nicht übergeben (Spec: mit Nennung des Dateinamens zurückweisen).
    case nichtUnterstuetzt
    case nichtLesbar
}

/// Bereitet eine geteilte Datei nach der Formatweiche für den Upload vor: unverändert durchreichen
/// oder als PDF umwandeln. Alles landet in `arbeitsordner`, den der Aufrufer danach löscht.
enum TeilenVorbereitung {
    static func vorbereiten(_ quelle: some TeilenQuelle, arbeitsordner: URL) async throws -> UploadDatei {
        switch Formatweiche.entscheiden(typen: quelle.typen, dateiname: quelle.dateiname) {
        case .abgewiesen:
            throw TeilenFehler.nichtUnterstuetzt

        case .unveraendert(let typ):
            let url = try await kopieren(quelle, typ: typ, arbeitsordner: arbeitsordner)
            return UploadDatei(url: url, dateiname: dateinameMitEndung(maßgeblicherName(quelle, kopie: url, typ: typ), typ: typ),
                               medientyp: typ.preferredMIMEType ?? "application/octet-stream")

        case .alsPDF(let typ):
            let bild = try await kopieren(quelle, typ: typ, arbeitsordner: arbeitsordner)
            let ziel = arbeitsordner.appendingPathComponent(UUID().uuidString).appendingPathExtension("pdf")
            do {
                try PDFErzeuger.erzeugen(seiten: [.datei(bild)], nach: ziel)
            } catch {
                throw TeilenFehler.nichtLesbar
            }
            try? FileManager.default.removeItem(at: bild)
            let original = maßgeblicherName(quelle, kopie: bild, typ: typ)
            // Nur eine zum Bildtyp passende Endung entfällt; „Foto 12.03.2025“ behält sein Datum.
            let basis = hatPassendeEndung(original, typ: typ) ? (original as NSString).deletingPathExtension : original
            let name = (basis.isEmpty ? "Dokument" : basis) + ".pdf"
            return UploadDatei(url: ziel, dateiname: name, medientyp: "application/pdf")
        }
    }

    private static func kopieren(_ quelle: some TeilenQuelle, typ: UTType, arbeitsordner: URL) async throws -> URL {
        // Eigener Unterordner je Datei, damit gleichnamige Dateien sich nicht überschreiben.
        let ordner = arbeitsordner.appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: ordner, withIntermediateDirectories: true)
        do {
            return try await quelle.kopieren(typ: typ, nach: ordner)
        } catch {
            throw TeilenFehler.nichtLesbar
        }
    }

    /// Der Name der kopierten Datei, wenn er eine zum Typ passende Endung trägt (der Provider kennt ihn
    /// vollständig); sonst der vorgeschlagene Name, der oft ohne Endung kommt.
    private static func maßgeblicherName(_ quelle: some TeilenQuelle, kopie: URL, typ: UTType) -> String {
        hatPassendeEndung(kopie.lastPathComponent, typ: typ) ? kopie.lastPathComponent : quelle.dateiname
    }

    /// Ob die Endung des Namens eine Endung des Typs ist („12.03.2025“ ist keine PDF-Endung).
    static func hatPassendeEndung(_ name: String, typ: UTType) -> Bool {
        let endung = (name as NSString).pathExtension.lowercased()
        guard !endung.isEmpty else { return false }
        let bekannt = (typ.tags[.filenameExtension] ?? []) + [typ.preferredFilenameExtension].compactMap { $0 }
        return bekannt.contains { $0.lowercased() == endung }
    }

    /// Ergänzt eine fehlende oder nicht zum Typ passende Endung (der Dienst erkennt das Format an der Endung).
    static func dateinameMitEndung(_ name: String, typ: UTType) -> String {
        let bereinigt = name.trimmingCharacters(in: .whitespacesAndNewlines)
        let basis = bereinigt.isEmpty ? "Dokument" : bereinigt
        if hatPassendeEndung(basis, typ: typ) { return basis }
        guard let endung = typ.preferredFilenameExtension else { return basis }
        return basis + "." + endung
    }
}
