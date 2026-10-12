import CryptoKit
import Foundation
import ImageIO
import PDFKit
import Testing
import UIKit
import UniformTypeIdentifiers
@testable import Lector

/// Hilfen für Tests mit echten Bilddateien.
enum Testbild {
    static func bild(breite: Int, hoehe: Int, farbe: UIColor = .systemTeal) -> UIImage {
        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        format.opaque = true
        return UIGraphicsImageRenderer(size: CGSize(width: breite, height: hoehe), format: format).image { kontext in
            farbe.setFill()
            kontext.fill(CGRect(x: 0, y: 0, width: breite, height: hoehe))
            UIColor.white.setFill()
            kontext.fill(CGRect(x: breite / 4, y: hoehe / 4, width: breite / 2, height: hoehe / 2))
        }
    }

    static func jpeg(breite: Int, hoehe: Int) -> Data {
        bild(breite: breite, hoehe: hoehe).jpegData(compressionQuality: 0.9)!
    }

    /// `nil`, wenn die Umgebung kein HEIC schreiben kann.
    static func heic(breite: Int, hoehe: Int) -> Data? {
        guard let cg = bild(breite: breite, hoehe: hoehe).cgImage else { return nil }
        let daten = NSMutableData()
        guard let ziel = CGImageDestinationCreateWithData(daten, UTType.heic.identifier as CFString, 1, nil) else { return nil }
        CGImageDestinationAddImage(ziel, cg, nil)
        return CGImageDestinationFinalize(ziel) ? daten as Data : nil
    }

    static func temporaererOrdner() throws -> URL {
        let ordner = FileManager.default.temporaryDirectory.appendingPathComponent("test-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: ordner, withIntermediateDirectories: true)
        return ordner
    }

    static func sha256(_ daten: Data) -> String {
        SHA256.hash(data: daten).map { String(format: "%02x", $0) }.joined()
    }
}

@Suite("PDFErzeuger: Seiten, Größe, Verkleinerung, Dateiname")
struct PDFErzeugerTests {
    private func erzeugen(_ seiten: [PDFSeite]) throws -> (PDFDocument, Data) {
        let ordner = try Testbild.temporaererOrdner()
        defer { try? FileManager.default.removeItem(at: ordner) }
        let ziel = ordner.appendingPathComponent("a.pdf")
        try PDFErzeuger.erzeugen(seiten: seiten, nach: ziel)
        let daten = try Data(contentsOf: ziel)
        return (try #require(PDFDocument(data: daten)), daten)
    }

    @Test("Ein Bild je Seite: drei Bilder ergeben drei Seiten")
    func seitenzahl() throws {
        let (pdf, _) = try erzeugen([
            .bild(Testbild.bild(breite: 600, hoehe: 800)),
            .daten(Testbild.jpeg(breite: 800, hoehe: 600)),
            .bild(Testbild.bild(breite: 500, hoehe: 500)),
        ])
        #expect(pdf.pageCount == 3)
    }

    @Test("Die Seitengröße folgt dem Seitenverhältnis des Bildes")
    func seitenverhaeltnis() throws {
        let (pdf, _) = try erzeugen([
            .daten(Testbild.jpeg(breite: 600, hoehe: 900)),
            .daten(Testbild.jpeg(breite: 1200, hoehe: 600)),
        ])
        let hoch = try #require(pdf.page(at: 0)).bounds(for: .mediaBox)
        let quer = try #require(pdf.page(at: 1)).bounds(for: .mediaBox)
        #expect(abs(hoch.width / hoch.height - 600.0 / 900.0) < 0.01)
        #expect(abs(quer.width / quer.height - 2.0) < 0.01)
        #expect(hoch.height > hoch.width && quer.width > quer.height)
    }

    @Test("Eine lange Kante über 3 000 px wird auf 3 000 px verkleinert, kleinere bleiben")
    func verkleinerung() throws {
        let gross = Testbild.jpeg(breite: 4000, hoehe: 2000)
        let (_, datenGross) = try erzeugen([.daten(gross)])
        let klein = Testbild.jpeg(breite: 1000, hoehe: 500)
        let (_, datenKlein) = try erzeugen([.daten(klein)])

        // Die Pixelgröße steht als /Width und /Height des eingebetteten Bildes im PDF.
        let textGross = String(decoding: datenGross, as: UTF8.self)
        #expect(textGross.contains("/Width 3000"))
        #expect(textGross.contains("/Height 1500"))
        let textKlein = String(decoding: datenKlein, as: UTF8.self)
        #expect(textKlein.contains("/Width 1000"))
        #expect(textKlein.contains("/Height 500"))
        // JPEG bleibt JPEG.
        #expect(textGross.contains("/DCTDecode"))
    }

    @Test("Ein UIImage über 3 000 px wird ebenfalls verkleinert")
    func verkleinerungUIImage() throws {
        let (_, daten) = try erzeugen([.bild(Testbild.bild(breite: 3500, hoehe: 1000))])
        let text = String(decoding: daten, as: UTF8.self)
        #expect(text.contains("/Width 3000"))
    }

    @Test("Transparente Bereiche eines PNG werden weiß, nicht schwarz")
    func transparenz() throws {
        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        format.opaque = false
        let png = UIGraphicsImageRenderer(size: CGSize(width: 200, height: 200), format: format).image { kontext in
            UIColor.red.setFill()
            kontext.fill(CGRect(x: 100, y: 0, width: 100, height: 200))
        }.pngData()!
        for seite in [PDFSeite.daten(png), .bild(UIImage(data: png)!)] {
            let (pdf, _) = try erzeugen([seite])
            let vorschau = try #require(pdf.page(at: 0)).thumbnail(of: CGSize(width: 200, height: 200), for: .mediaBox)
            let cg = try #require(vorschau.cgImage)
            var pixel = [UInt8](repeating: 0, count: 4)
            let kontext = try #require(CGContext(
                data: &pixel, width: 1, height: 1, bitsPerComponent: 8, bytesPerRow: 4,
                space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue))
            // Pixel aus dem linken (transparenten) Viertel.
            kontext.draw(cg, in: CGRect(x: -Double(cg.width) / 4, y: -Double(cg.height) / 2, width: Double(cg.width), height: Double(cg.height)))
            #expect(pixel[0] > 230 && pixel[1] > 230 && pixel[2] > 230)
        }
    }

    @Test("Ein HEIC-Eingangsbild ergibt ein PDF")
    func heic() throws {
        guard let heic = Testbild.heic(breite: 640, hoehe: 480) else {
            Issue.record("HEIC lässt sich in dieser Umgebung nicht erzeugen")
            return
        }
        let (pdf, daten) = try erzeugen([.daten(heic)])
        #expect(pdf.pageCount == 1)
        #expect(String(decoding: daten.prefix(5), as: UTF8.self) == "%PDF-")
    }

    @Test("Ohne Seiten oder mit unlesbarem Bild gibt es einen Fehler und keine Datei")
    func fehler() throws {
        let ordner = try Testbild.temporaererOrdner()
        defer { try? FileManager.default.removeItem(at: ordner) }
        let ziel = ordner.appendingPathComponent("a.pdf")
        #expect(throws: PDFFehler.keineSeiten) { try PDFErzeuger.erzeugen(seiten: [], nach: ziel) }
        #expect(throws: PDFFehler.bildNichtLesbar(seite: 1)) {
            try PDFErzeuger.erzeugen(seiten: [.daten(Testbild.jpeg(breite: 100, hoehe: 100)), .daten(Data("kein Bild".utf8))], nach: ziel)
        }
        #expect(!FileManager.default.fileExists(atPath: ziel.path))
    }

    @Test("Dateiname: Scan JJJJ-MM-TT HHMMSS.pdf in Ortszeit")
    func dateiname() throws {
        // 2026-10-12 12:30:05 UTC; in Berlin (MESZ) 14:30:05.
        let datum = Date(timeIntervalSince1970: 1_791_808_205)
        let berlin = try #require(TimeZone(identifier: "Europe/Berlin"))
        #expect(PDFErzeuger.dateiname(fuer: datum, zeitzone: berlin) == "Scan 2026-10-12 143005.pdf")
        #expect(PDFErzeuger.dateiname(fuer: datum, zeitzone: try #require(TimeZone(secondsFromGMT: 0))) == "Scan 2026-10-12 123005.pdf")
    }
}
