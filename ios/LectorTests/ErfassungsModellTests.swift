import Foundation
import PDFKit
import Synchronization
import Testing
import UIKit
@testable import Lector

@MainActor
@Suite("Erfassung: Bilder zu einem PDF, Upload, Zustand, Aufräumen")
struct ErfassungsModellTests {
    private let angenommen = #"{"results":[{"filename":"Scan.pdf","accepted":true,"reason":null,"stored_as":"Scan.pdf"}]}"#
    private let abgelehnt = #"{"results":[{"filename":"Scan.pdf","accepted":false,"reason":"unsupported_format","stored_as":null}]}"#

    private func client(_ transport: TransportAttrappe) -> APIClient {
        let store = SpeicherTokenStore("k1")
        let konfiguration = testKonfiguration()
        let sitzung = AuthSession(konfiguration: konfiguration, transport: transport, tokenStore: store)
        return APIClient(konfiguration: konfiguration, transport: transport, sitzung: sitzung)
    }

    private func dreiBilder() -> @MainActor (URL) async throws -> [PDFSeite] {
        { _ in [.bild(Testbild.bild(breite: 600, hoehe: 800)), .daten(Testbild.jpeg(breite: 800, hoehe: 600)),
                .bild(Testbild.bild(breite: 500, hoehe: 500))] }
    }

    /// Das PDF aus dem Multipart-Rumpf einer Anfrage.
    private func pdf(aus anfrage: URLRequest) throws -> PDFDocument {
        let rumpf = try #require(anfrage.httpBody)
        let anfang = try #require(rumpf.range(of: Data("%PDF".utf8)))
        let ende = try #require(rumpf.range(of: Data("%%EOF".utf8), options: .backwards))
        return try #require(PDFDocument(data: Data(rumpf[anfang.lowerBound..<ende.upperBound])))
    }

    @Test("Drei Bilder ergeben genau eine Upload-Datei mit drei Seiten, Name Scan JJJJ-MM-TT HHMMSS.pdf")
    func dreiBilderEinPDF() async throws {
        let transport = TransportAttrappe { _ in .json(self.angenommen) }
        let modell = ErfassungsModell(client: client(transport), seiten: dreiBilder())
        defer { modell.aufraeumen() }

        await modell.starten()

        #expect(modell.zustand == .uebergeben)
        #expect(modell.seitenzahl == 3)
        let anfragen = await transport.anfragen(pfad: "/api/v1/upload")
        #expect(anfragen.count == 1)
        let anfrage = try #require(anfragen.first)
        let rumpf = try #require(anfrage.httpBody)
        let text = String(decoding: rumpf, as: UTF8.self)
        #expect(text.components(separatedBy: "name=\"files\"").count == 2, "genau eine Datei")
        #expect(text.contains("Content-Type: application/pdf"))
        #expect(text.range(of: #"filename="Scan \d{4}-\d{2}-\d{2} \d{6}\.pdf""#, options: .regularExpression) != nil)
        #expect(try pdf(aus: anfrage).pageCount == 3)
    }

    @Test("Nach der Annahme bleibt keine PDF-Datei liegen")
    func erfolgRaeumtDateiWeg() async throws {
        let transport = TransportAttrappe { _ in .json(self.angenommen) }
        let modell = ErfassungsModell(client: client(transport), seiten: dreiBilder())
        defer { modell.aufraeumen() }
        #expect(modell.zustand == .bereit)

        await modell.starten()

        #expect(modell.zustand == .uebergeben)
        #expect(modell.kannErneutSenden == false)
        let inhalt = (try? FileManager.default.contentsOfDirectory(atPath: modell.arbeitsordner.path)) ?? []
        #expect(inhalt.isEmpty)
    }

    @Test("Netzfehler: Fehlschlag mit „Erneut senden“; erneutes Senden schickt dasselbe PDF und gelingt")
    func netzfehlerDannErneut() async throws {
        let versuch = Mutex(0)
        let transport = TransportAttrappe { _ in
            if versuch.withLock({ $0 += 1; return $0 }) == 1 { throw URLError(.notConnectedToInternet) }
            return .json(self.angenommen)
        }
        let modell = ErfassungsModell(client: client(transport), seiten: dreiBilder())
        defer { modell.aufraeumen() }

        await modell.starten()
        #expect(modell.zustand == .fehlgeschlagen("Keine Verbindung zu Lector."))
        #expect(modell.kannErneutSenden)

        await modell.erneutSenden()
        #expect(modell.zustand == .uebergeben)
        let anfragen = await transport.anfragen(pfad: "/api/v1/upload")
        #expect(anfragen.count == 2)
        #expect(try pdf(aus: anfragen[0]).pageCount == 3)
        #expect(try pdf(aus: anfragen[1]).pageCount == 3)
    }

    @Test("Serverfehler zeigt die Meldung des Dienstes und erlaubt erneutes Senden")
    func serverfehler() async throws {
        let transport = TransportAttrappe { _ in .fehler(500, "internal", "Speicher voll") }
        let modell = ErfassungsModell(client: client(transport), seiten: dreiBilder())
        defer { modell.aufraeumen() }

        await modell.starten()

        #expect(modell.zustand == .fehlgeschlagen("Speicher voll"))
        #expect(modell.kannErneutSenden)
    }

    @Test("Ablehnung durch den Dienst wird angezeigt; erneutes Senden wird nicht angeboten")
    func ablehnung() async throws {
        let transport = TransportAttrappe { _ in .json(self.abgelehnt) }
        let modell = ErfassungsModell(client: client(transport), seiten: dreiBilder())
        defer { modell.aufraeumen() }

        await modell.starten()

        #expect(modell.zustand == .abgewiesen("Dateiformat wird nicht unterstützt"))
        #expect(modell.kannErneutSenden == false)
        await modell.erneutSenden()
        #expect(await transport.anzahl(pfad: "/api/v1/upload") == 1)
    }

    @Test("Aufräumen beim Schließen löscht den Arbeitsordner samt nicht übergebenem PDF; nichts wird nachgeholt")
    func aufraeumen() async throws {
        let transport = TransportAttrappe { _ in throw URLError(.notConnectedToInternet) }
        let modell = ErfassungsModell(client: client(transport), seiten: dreiBilder())

        await modell.starten()
        #expect(modell.kannErneutSenden)
        #expect(FileManager.default.fileExists(atPath: modell.arbeitsordner.path))

        modell.aufraeumen()

        #expect(!FileManager.default.fileExists(atPath: modell.arbeitsordner.path))
        await modell.erneutSenden()
        #expect(await transport.anzahl(pfad: "/api/v1/upload") == 1)
    }

    @Test("Seiten als Dateien im Arbeitsordner (Fotos) ergeben ebenfalls ein PDF")
    func seitenAlsDateien() async throws {
        let transport = TransportAttrappe { _ in .json(self.angenommen) }
        let modell = ErfassungsModell(client: client(transport)) { ordner in
            try (0..<2).map { index in
                let url = ordner.appendingPathComponent("foto-\(index)")
                try Testbild.jpeg(breite: 400, hoehe: 300).write(to: url)
                return PDFSeite.datei(url)
            }
        }
        defer { modell.aufraeumen() }

        await modell.starten()

        #expect(modell.zustand == .uebergeben)
        let anfrage = try #require(await transport.anfragen(pfad: "/api/v1/upload").first)
        #expect(try pdf(aus: anfrage).pageCount == 2)
    }

    @Test("Keine Seiten: nichts wird hochgeladen")
    func keineSeiten() async throws {
        let transport = TransportAttrappe { _ in .json(self.angenommen) }
        let modell = ErfassungsModell(client: client(transport)) { _ in [] }
        defer { modell.aufraeumen() }

        await modell.starten()

        guard case .abgewiesen = modell.zustand else { Issue.record("erwartet: abgewiesen, ist \(modell.zustand)"); return }
        #expect(await transport.anzahl(pfad: "/api/v1/upload") == 0)
    }
}
