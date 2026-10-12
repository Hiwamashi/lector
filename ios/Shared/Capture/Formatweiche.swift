import Foundation
import UniformTypeIdentifiers

/// Was mit einer geteilten Datei geschieht (D13).
enum Formatentscheidung: Equatable, Sendable {
    /// PDF, XML und TIFF gehen byte-genau unverändert weiter (E-Rechnungen müssen als solche erkannt werden).
    case unveraendert(UTType)
    /// Andere Bilder werden wie Fotos zu einem PDF (D12).
    case alsPDF(UTType)
    case abgewiesen
}

/// Die Formatentscheidung nach `UTType`, ohne Dateizugriff und damit rein testbar.
enum Formatweiche {
    /// - Parameters:
    ///   - typen: die Typen, die die Datei anbietet (bei `NSItemProvider`: `registeredTypeIdentifiers`),
    ///     in Reihenfolge der Treue. Fehlen sie, entscheidet die Dateiendung von `dateiname`.
    static func entscheiden(typen: [UTType], dateiname: String) -> Formatentscheidung {
        var kandidaten = typen
        if kandidaten.isEmpty, let typ = UTType(filenameExtension: (dateiname as NSString).pathExtension) {
            kandidaten = [typ]
        }
        // Reihenfolge ist wichtig: TIFF ist auch ein Bild und bleibt unverändert.
        if let typ = kandidaten.first(where: { $0.conforms(to: .pdf) }) { return .unveraendert(typ) }
        if let typ = kandidaten.first(where: { $0.conforms(to: .tiff) }) { return .unveraendert(typ) }
        // SVG ist XML und ein Bild zugleich, lässt sich aber weder als E-Rechnung noch als Foto übergeben.
        if kandidaten.contains(where: { $0.conforms(to: .svg) }) { return .abgewiesen }
        if let typ = kandidaten.first(where: { $0.conforms(to: .xml) }) { return .unveraendert(typ) }
        if let typ = kandidaten.first(where: { $0.conforms(to: .image) && !$0.conforms(to: .svg) }) {
            return .alsPDF(typ)
        }
        return .abgewiesen
    }
}
