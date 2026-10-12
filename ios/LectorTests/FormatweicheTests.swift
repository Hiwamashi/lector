import Foundation
import PDFKit
import Testing
import UniformTypeIdentifiers
@testable import Lector

/// Geteilte Datei aus dem Arbeitsspeicher der Tests: schreibt die Bytes beim „Kopieren“ in den Zielordner.
struct DateiQuelle: TeilenQuelle {
    let dateiname: String
    let typen: [UTType]
    let inhalt: Data
    var kopierfehler = false

    func kopieren(typ: UTType, nach ziel: URL) async throws -> URL {
        if kopierfehler { throw CocoaError(.fileReadUnknown) }
        let url = ziel.appendingPathComponent(dateiname)
        try inhalt.write(to: url)
        return url
    }
}

@Suite("Formatweiche: Entscheidung nach UTType")
struct FormatweicheTests {
    @Test("PDF, XML und TIFF bleiben unverändert")
    func unveraendert() {
        #expect(Formatweiche.entscheiden(typen: [.pdf], dateiname: "a.pdf") == .unveraendert(.pdf))
        #expect(Formatweiche.entscheiden(typen: [.xml], dateiname: "a.xml") == .unveraendert(.xml))
        // TIFF ist auch ein Bild und darf nicht in ein PDF verwandelt werden.
        #expect(Formatweiche.entscheiden(typen: [.tiff, .image], dateiname: "a.tif") == .unveraendert(.tiff))
    }

    @Test("Andere Bilder werden zu PDF")
    func bilder() {
        #expect(Formatweiche.entscheiden(typen: [.jpeg], dateiname: "a.jpg") == .alsPDF(.jpeg))
        #expect(Formatweiche.entscheiden(typen: [.heic], dateiname: "a.heic") == .alsPDF(.heic))
        #expect(Formatweiche.entscheiden(typen: [.png], dateiname: "a.png") == .alsPDF(.png))
    }

    @Test("Alles andere wird abgewiesen")
    func abgewiesen() {
        #expect(Formatweiche.entscheiden(typen: [.plainText], dateiname: "a.txt") == .abgewiesen)
        #expect(Formatweiche.entscheiden(typen: [.zip], dateiname: "a.zip") == .abgewiesen)
        #expect(Formatweiche.entscheiden(typen: [.svg], dateiname: "a.svg") == .abgewiesen)
        #expect(Formatweiche.entscheiden(typen: [], dateiname: "ohne") == .abgewiesen)
    }

    @Test("Ohne angebotene Typen entscheidet die Dateiendung")
    func endung() {
        #expect(Formatweiche.entscheiden(typen: [], dateiname: "Rechnung.PDF") == .unveraendert(.pdf))
    }
}

@Suite("TeilenVorbereitung: unverändert, Umwandlung, Abweisung")
struct TeilenVorbereitungTests {
    @Test("PDF-Bytes bleiben unverändert (Hash)")
    func pdfUnveraendert() async throws {
        let ordner = try Testbild.temporaererOrdner()
        defer { try? FileManager.default.removeItem(at: ordner) }
        // Beliebige Bytes, die kein gültiges PDF sein müssen: die Datei darf nicht angefasst werden.
        let original = Data("%PDF-1.7\nZUGFeRD-Anhang\u{0}\u{1}\u{2}\n%%EOF".utf8) + Data((0..<4096).map { UInt8($0 % 251) })
        let quelle = DateiQuelle(dateiname: "Rechnung", typen: [.pdf], inhalt: original)

        let datei = try await TeilenVorbereitung.vorbereiten(quelle, arbeitsordner: ordner)

        #expect(Testbild.sha256(try Data(contentsOf: datei.url)) == Testbild.sha256(original))
        #expect(datei.dateiname == "Rechnung.pdf")
        #expect(datei.medientyp == "application/pdf")
    }

    @Test("XML und TIFF bleiben byte-genau")
    func xmlTiff() async throws {
        let ordner = try Testbild.temporaererOrdner()
        defer { try? FileManager.default.removeItem(at: ordner) }
        let xml = Data(#"<?xml version="1.0"?><Invoice/>"#.utf8)
        let tiff = Data([0x49, 0x49, 0x2A, 0x00, 1, 2, 3, 4])
        let a = try await TeilenVorbereitung.vorbereiten(DateiQuelle(dateiname: "r.xml", typen: [.xml], inhalt: xml), arbeitsordner: ordner)
        let b = try await TeilenVorbereitung.vorbereiten(DateiQuelle(dateiname: "s.tif", typen: [.tiff], inhalt: tiff), arbeitsordner: ordner)
        #expect(try Data(contentsOf: a.url) == xml)
        #expect(try Data(contentsOf: b.url) == tiff)
        #expect(b.dateiname == "s.tif")
    }

    @Test("JPEG wird zu einem PDF mit einer Seite")
    func jpegWirdPDF() async throws {
        let ordner = try Testbild.temporaererOrdner()
        defer { try? FileManager.default.removeItem(at: ordner) }
        let quelle = DateiQuelle(dateiname: "IMG_0001.jpg", typen: [.jpeg], inhalt: Testbild.jpeg(breite: 800, hoehe: 600))

        let datei = try await TeilenVorbereitung.vorbereiten(quelle, arbeitsordner: ordner)

        #expect(datei.dateiname == "IMG_0001.pdf")
        #expect(datei.medientyp == "application/pdf")
        let pdf = try #require(PDFDocument(url: datei.url))
        #expect(pdf.pageCount == 1)
    }

    @Test("Namen mit Punkten ohne echte Endung bekommen die Endung des Typs")
    func punkteImNamen() async throws {
        let ordner = try Testbild.temporaererOrdner()
        defer { try? FileManager.default.removeItem(at: ordner) }
        let faelle: [(String, UTType, String)] = [
            ("Rechnung 12.03.2025", .pdf, "Rechnung 12.03.2025.pdf"),
            ("RE-2025.0123", .pdf, "RE-2025.0123.pdf"),
            ("Beleg v2.1", .xml, "Beleg v2.1.xml"),
            ("Rechnung.PDF", .pdf, "Rechnung.PDF"),
        ]
        for (name, typ, erwartet) in faelle {
            let quelle = DateiQuelle(dateiname: name, typen: [typ], inhalt: Data("x".utf8))
            let datei = try await TeilenVorbereitung.vorbereiten(quelle, arbeitsordner: ordner)
            #expect(datei.dateiname == erwartet)
        }
        let bild = DateiQuelle(dateiname: "Foto 12.03.2025", typen: [.jpeg], inhalt: Testbild.jpeg(breite: 100, hoehe: 100))
        #expect(try await TeilenVorbereitung.vorbereiten(bild, arbeitsordner: ordner).dateiname == "Foto 12.03.2025.pdf")
        let mit = DateiQuelle(dateiname: "Foto.jpeg", typen: [.jpeg], inhalt: Testbild.jpeg(breite: 100, hoehe: 100))
        #expect(try await TeilenVorbereitung.vorbereiten(mit, arbeitsordner: ordner).dateiname == "Foto.pdf")
    }

    @Test("Der Name der kopierten Datei mit echter Endung ist maßgeblich")
    func kopierterName() async throws {
        struct Quelle: TeilenQuelle {
            let dateiname = "Rechnung 12.03.2025"
            let typen: [UTType] = [.pdf]
            func kopieren(typ: UTType, nach ziel: URL) async throws -> URL {
                let url = ziel.appendingPathComponent("Rechnung 12.03.2025.pdf")
                try Data("x".utf8).write(to: url)
                return url
            }
        }
        let ordner = try Testbild.temporaererOrdner()
        defer { try? FileManager.default.removeItem(at: ordner) }
        let datei = try await TeilenVorbereitung.vorbereiten(Quelle(), arbeitsordner: ordner)
        #expect(datei.dateiname == "Rechnung 12.03.2025.pdf")
    }

    @Test(".txt wird abgewiesen")
    func txtAbgewiesen() async throws {
        let ordner = try Testbild.temporaererOrdner()
        defer { try? FileManager.default.removeItem(at: ordner) }
        let quelle = DateiQuelle(dateiname: "notiz.txt", typen: [.plainText], inhalt: Data("hallo".utf8))
        await #expect(throws: TeilenFehler.nichtUnterstuetzt) {
            try await TeilenVorbereitung.vorbereiten(quelle, arbeitsordner: ordner)
        }
    }

    @Test("Ein unlesbares Bild und ein Kopierfehler werden als nicht lesbar gemeldet")
    func nichtLesbar() async throws {
        let ordner = try Testbild.temporaererOrdner()
        defer { try? FileManager.default.removeItem(at: ordner) }
        let kaputt = DateiQuelle(dateiname: "x.jpg", typen: [.jpeg], inhalt: Data("kein Bild".utf8))
        await #expect(throws: TeilenFehler.nichtLesbar) { try await TeilenVorbereitung.vorbereiten(kaputt, arbeitsordner: ordner) }
        let fehler = DateiQuelle(dateiname: "x.pdf", typen: [.pdf], inhalt: Data(), kopierfehler: true)
        await #expect(throws: TeilenFehler.nichtLesbar) { try await TeilenVorbereitung.vorbereiten(fehler, arbeitsordner: ordner) }
    }
}
