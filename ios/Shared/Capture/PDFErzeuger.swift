import Foundation
import ImageIO
import UIKit

/// Eine Seite des zu erzeugenden PDFs. Dateien und Daten werden erst beim Zeichnen gelesen,
/// damit nie mehr als ein Bild im Speicher liegt (Speichergrenze der Share Extension).
enum PDFSeite: @unchecked Sendable {
    case datei(URL)
    case daten(Data)
    case bild(UIImage)
}

enum PDFFehler: Error, Equatable {
    /// Es wurde keine Seite übergeben.
    case keineSeiten
    /// Die Seite (nullbasiert) war kein lesbares Bild.
    case bildNichtLesbar(seite: Int)
    /// Das PDF konnte nicht geschrieben werden.
    case schreibenFehlgeschlagen
}

/// Fasst Bilder zu einem PDF zusammen (D12): ein Bild je Seite, Seitengröße nach dem
/// Seitenverhältnis des Bildes, JPEG mit Qualität 0,85, lange Kante höchstens 3 000 px.
/// Der Dateiname ist `Scan JJJJ-MM-TT HHMMSS.pdf` in Ortszeit.
enum PDFErzeuger {
    static let jpegQualitaet: CGFloat = 0.85
    /// Längste erlaubte Kante des eingebetteten Bildes in Pixeln.
    static let maximaleKante: CGFloat = 3000
    /// Lange Kante einer PDF-Seite in Punkten (A4-Höhe); die kurze folgt dem Seitenverhältnis.
    static let seitenKante: CGFloat = 842

    /// `Scan 2026-10-12 143005.pdf`.
    static func dateiname(
        fuer datum: Date = Date(), zeitzone: TimeZone = .current
    ) -> String {
        let formatierer = DateFormatter()
        formatierer.locale = Locale(identifier: "en_US_POSIX")
        formatierer.calendar = Calendar(identifier: .gregorian)
        formatierer.timeZone = zeitzone
        formatierer.dateFormat = "yyyy-MM-dd HHmmss"
        return "Scan \(formatierer.string(from: datum)).pdf"
    }

    /// Schreibt das PDF nach `ziel` (eine bestehende Datei wird ersetzt).
    static func erzeugen(seiten: [PDFSeite], nach ziel: URL) throws {
        guard !seiten.isEmpty else { throw PDFFehler.keineSeiten }

        var fehler: PDFFehler?
        let renderer = UIGraphicsPDFRenderer(bounds: CGRect(x: 0, y: 0, width: seitenKante, height: seitenKante))
        do {
            try renderer.writePDF(to: ziel) { kontext in
                for (index, seite) in seiten.enumerated() {
                    // Pro Seite ein eigener Pool, damit das dekodierte Bild sofort freigegeben wird.
                    autoreleasepool {
                        guard fehler == nil else { return }
                        guard let jpeg = Self.jpegDaten(seite) else {
                            fehler = .bildNichtLesbar(seite: index)
                            return
                        }
                        let groesse = Self.seitengroesse(pixelBreite: jpeg.breite, pixelHoehe: jpeg.hoehe)
                        kontext.beginPage(withBounds: CGRect(origin: .zero, size: groesse), pageInfo: [:])
                        // Aus JPEG-Daten geladen, bleibt das Bild im PDF ein JPEG (DCTDecode).
                        UIImage(data: jpeg.daten)?.draw(in: CGRect(origin: .zero, size: groesse))
                    }
                }
            }
        } catch {
            try? FileManager.default.removeItem(at: ziel)
            throw PDFFehler.schreibenFehlgeschlagen
        }
        if let fehler {
            try? FileManager.default.removeItem(at: ziel)
            throw fehler
        }
    }

    /// Seitengröße in Punkten: lange Kante `seitenKante`, kurze nach Seitenverhältnis.
    static func seitengroesse(pixelBreite: Int, pixelHoehe: Int) -> CGSize {
        let breite = CGFloat(max(pixelBreite, 1)), hoehe = CGFloat(max(pixelHoehe, 1))
        let faktor = seitenKante / max(breite, hoehe)
        return CGSize(width: breite * faktor, height: hoehe * faktor)
    }

    // MARK: - Bild laden und verkleinern

    private struct JPEG { let daten: Data; let breite: Int; let hoehe: Int }

    private static func jpegDaten(_ seite: PDFSeite) -> JPEG? {
        let cg: CGImage?
        switch seite {
        case .datei(let url):
            cg = quelle(CGImageSourceCreateWithURL(url as CFURL, nil))
        case .daten(let daten):
            cg = quelle(CGImageSourceCreateWithData(daten as CFData, nil))
        case .bild(let bild):
            cg = verkleinert(bild)
        }
        guard var cg else { return nil }
        // JPEG kennt keine Transparenz: Ohne weißen Grund würden transparente Bereiche schwarz.
        if hatAlpha(cg) { guard let flach = aufWeiss(cg) else { return nil }; cg = flach }
        // Über UIImage kodieren: berücksichtigt die Ausrichtung nicht mehr, sie ist schon eingerechnet.
        guard let daten = UIImage(cgImage: cg).jpegData(compressionQuality: jpegQualitaet) else { return nil }
        return JPEG(daten: daten, breite: cg.width, hoehe: cg.height)
    }

    /// Dekodiert über ImageIO direkt in der Zielgröße (spart den Speicher des Vollbildes) und
    /// rechnet die EXIF-Ausrichtung ein.
    private static func quelle(_ quelle: CGImageSource?) -> CGImage? {
        guard let quelle else { return nil }
        let optionen: [CFString: Any] = [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceCreateThumbnailWithTransform: true,
            kCGImageSourceShouldCacheImmediately: true,
            kCGImageSourceThumbnailMaxPixelSize: maximaleKante,
        ]
        return CGImageSourceCreateThumbnailAtIndex(quelle, 0, optionen as CFDictionary)
    }

    private static func hatAlpha(_ bild: CGImage) -> Bool {
        switch bild.alphaInfo {
        case .none, .noneSkipFirst, .noneSkipLast: false
        default: true
        }
    }

    private static func aufWeiss(_ bild: CGImage) -> CGImage? {
        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        format.opaque = true
        let groesse = CGSize(width: bild.width, height: bild.height)
        return UIGraphicsImageRenderer(size: groesse, format: format).image { kontext in
            UIColor.white.setFill()
            kontext.fill(CGRect(origin: .zero, size: groesse))
            UIImage(cgImage: bild).draw(in: CGRect(origin: .zero, size: groesse))
        }.cgImage
    }

    private static func verkleinert(_ bild: UIImage) -> CGImage? {
        let breite = bild.size.width * bild.scale, hoehe = bild.size.height * bild.scale
        guard breite > 0, hoehe > 0 else { return nil }
        let faktor = min(1, maximaleKante / max(breite, hoehe))
        let ziel = CGSize(width: (breite * faktor).rounded(), height: (hoehe * faktor).rounded())
        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        format.opaque = true
        return UIGraphicsImageRenderer(size: ziel, format: format).image { _ in
            bild.draw(in: CGRect(origin: .zero, size: ziel))
        }.cgImage
    }
}
