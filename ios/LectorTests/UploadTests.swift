import Foundation
import Synchronization
import Testing
@testable import Lector

@Suite("Upload: Multipart, Ergebnis je Datei, 401, Netzfehler")
struct UploadTests {
    private struct Aufbau {
        let transport: TransportAttrappe
        let store: SpeicherTokenStore
        let client: APIClient
    }

    private func aufbau(schluessel: String? = "k1", _ antworter: @escaping TransportAttrappe.Antworter) -> Aufbau {
        let transport = TransportAttrappe(antworter)
        let store = SpeicherTokenStore(schluessel)
        let konfiguration = testKonfiguration()
        let sitzung = AuthSession(konfiguration: konfiguration, transport: transport, tokenStore: store)
        return Aufbau(transport: transport, store: store,
                      client: APIClient(konfiguration: konfiguration, transport: transport, sitzung: sitzung))
    }

    private func datei(_ name: String, _ inhalt: Data, typ: String = "application/pdf") throws -> (UploadDatei, URL) {
        let ordner = try Testbild.temporaererOrdner()
        let url = ordner.appendingPathComponent("vorbereitet")
        try inhalt.write(to: url)
        return (UploadDatei(url: url, dateiname: name, medientyp: typ), ordner)
    }

    private let angenommen = #"{"results":[{"filename":"Beleg.pdf","accepted":true,"reason":null,"stored_as":"Beleg.pdf"}]}"#

    @Test("Multipart: Feld files, Dateiname, Medientyp, Grenze und unveränderte Bytes; Bearer gesetzt")
    func multipart() async throws {
        let a = aufbau { _ in .json(self.angenommen) }
        let inhalt = Data("%PDF-1.7 \u{0}\u{1}\u{2} Bytes\r\n--fast-grenze".utf8) + Data(0...255)
        let (datei, ordner) = try datei("Beleg.pdf", inhalt)
        defer { try? FileManager.default.removeItem(at: ordner) }

        let ergebnis = try await a.client.hochladen(datei)

        #expect(ergebnis == UploadErgebnisDTO(filename: "Beleg.pdf", accepted: true, reason: nil, storedAs: "Beleg.pdf"))
        let anfrage = try #require(await a.transport.anfragen(pfad: "/api/v1/upload").first)
        #expect(anfrage.httpMethod == "POST")
        #expect(anfrage.bearer == "k1")
        let typ = try #require(anfrage.value(forHTTPHeaderField: "Content-Type"))
        #expect(typ.hasPrefix("multipart/form-data; boundary=Lector-"))
        let grenze = String(typ.dropFirst("multipart/form-data; boundary=".count))

        let rumpf = try #require(anfrage.httpBody)
        let kopf = Data("--\(grenze)\r\nContent-Disposition: form-data; name=\"files\"; filename=\"Beleg.pdf\"\r\nContent-Type: application/pdf\r\n\r\n".utf8)
        let schluss = Data("\r\n--\(grenze)--\r\n".utf8)
        #expect(rumpf == kopf + inhalt + schluss)
    }

    @Test("Anführungszeichen im Dateinamen brechen den Kopf nicht auf")
    func dateinameBereinigt() async throws {
        let a = aufbau { _ in .json(self.angenommen) }
        let (datei, ordner) = try datei("Be\"leg\r\n.pdf", Data("x".utf8))
        defer { try? FileManager.default.removeItem(at: ordner) }
        _ = try await a.client.hochladen(datei)
        let rumpf = try #require(await a.transport.anfragen.first?.httpBody)
        #expect(String(decoding: rumpf, as: UTF8.self).contains("filename=\"Be%22leg.pdf\""))
    }

    @Test("Eine abgelehnte Datei ist ein Ergebnis mit Grund, kein Fehler")
    func abgelehnt() async throws {
        let a = aufbau { _ in
            .json(#"{"results":[{"filename":"x.txt","accepted":false,"reason":"unsupported_format","stored_as":null}]}"#)
        }
        let (datei, ordner) = try datei("x.txt", Data("x".utf8), typ: "text/plain")
        defer { try? FileManager.default.removeItem(at: ordner) }
        let ergebnis = try await a.client.hochladen(datei)
        #expect(!ergebnis.accepted)
        #expect(ergebnis.reason == "unsupported_format")
        #expect(ergebnis.ablehnungstext == "Dateiformat wird nicht unterstützt")
    }

    @Test("401 verwirft den Schlüssel und wirft nichtAngemeldet")
    func nichtAngemeldet() async throws {
        let a = aufbau { _ in .fehler(401, "not_authenticated") }
        let (datei, ordner) = try datei("Beleg.pdf", Data("x".utf8))
        defer { try? FileManager.default.removeItem(at: ordner) }
        await #expect(throws: APIFehler.nichtAngemeldet) { try await a.client.hochladen(datei) }
        #expect(a.store.lesen() == nil)
    }

    @Test("400 no_files wird als Serverfehler gemeldet; leere Ergebnisliste ist eine ungültige Antwort")
    func serverFehler() async throws {
        let (datei, ordner) = try datei("Beleg.pdf", Data("x".utf8))
        defer { try? FileManager.default.removeItem(at: ordner) }
        let a = aufbau { _ in .fehler(400, "no_files", "Keine Dateien") }
        await #expect(throws: APIFehler.server(status: 400, code: .keineDateien, meldung: "Keine Dateien")) {
            try await a.client.hochladen(datei)
        }
        let b = aufbau { _ in .json(#"{"results":[]}"#) }
        await #expect(throws: APIFehler.ungueltigeAntwort) { try await b.client.hochladen(datei) }
    }

    @Test("Ohne Netz: keinNetz, der Schlüssel bleibt, die Rumpfdatei ist gelöscht")
    func ohneNetz() async throws {
        let konfiguration = testKonfiguration()
        let store = SpeicherTokenStore("k1")
        let sitzung = AuthSession(konfiguration: konfiguration, transport: TransportOhneNetz(), tokenStore: store)
        let client = APIClient(konfiguration: konfiguration, transport: TransportOhneNetz(), sitzung: sitzung)
        let (datei, ordner) = try datei("Beleg.pdf", Data("x".utf8))
        defer { try? FileManager.default.removeItem(at: ordner) }

        let vorher = try FileManager.default.contentsOfDirectory(atPath: FileManager.default.temporaryDirectory.path)
            .filter { $0.hasSuffix(".multipart") }
        await #expect(throws: APIFehler.keinNetz) { try await client.hochladen(datei) }
        let nachher = try FileManager.default.contentsOfDirectory(atPath: FileManager.default.temporaryDirectory.path)
            .filter { $0.hasSuffix(".multipart") }
        #expect(store.lesen() == "k1")
        #expect(Set(nachher).isSubset(of: Set(vorher)))
    }

    @Test("Ohne Serveradresse wird nichts gesendet")
    func ohneAdresse() async throws {
        let transport = TransportAttrappe { _ in .json("{}") }
        let konfiguration = testKonfiguration(adresse: nil)
        let sitzung = AuthSession(konfiguration: konfiguration, transport: transport, tokenStore: SpeicherTokenStore("k"))
        let client = APIClient(konfiguration: konfiguration, transport: transport, sitzung: sitzung)
        let (datei, ordner) = try datei("Beleg.pdf", Data("x".utf8))
        defer { try? FileManager.default.removeItem(at: ordner) }
        await #expect(throws: APIFehler.keineServeradresse) { try await client.hochladen(datei) }
        #expect(await transport.anfragen.isEmpty)
    }
}

@Suite("TeilenModell: Voraussetzungen, Ergebnis je Datei, erneutes Senden")
@MainActor
struct TeilenModellTests {
    private func modell(
        _ quellen: [DateiQuelle], schluessel: String? = "k1", adresse: String? = "https://lector.example.de",
        modus: AuthModus = .paperless, _ antworter: @escaping TransportAttrappe.Antworter
    ) -> (TeilenModell, TransportAttrappe) {
        let transport = TransportAttrappe(antworter)
        let store = SpeicherTokenStore(schluessel)
        let konfiguration = testKonfiguration(adresse: adresse, modus: modus)
        let sitzung = AuthSession(konfiguration: konfiguration, transport: transport, tokenStore: store)
        let client = APIClient(konfiguration: konfiguration, transport: transport, sitzung: sitzung)
        return (TeilenModell(quellen: quellen, client: client, konfiguration: konfiguration, tokenStore: store), transport)
    }

    private let pdf = DateiQuelle(dateiname: "a.pdf", typen: [.pdf], inhalt: Data("pdf".utf8))
    private let txt = DateiQuelle(dateiname: "n.txt", typen: [.plainText], inhalt: Data("t".utf8))

    private nonisolated static func ok(_ name: String) -> String {
        #"{"results":[{"filename":"\#(name)","accepted":true,"reason":null,"stored_as":"\#(name)"}]}"#
    }

    @Test("Ohne Adresse oder Anmeldung wird nichts übergeben")
    func ohneEinrichtung() async {
        let (a, ta) = modell([pdf], adresse: nil) { _ in .json("{}") }
        #expect(a.voraussetzung == .nichtEingerichtet)
        await a.starten()
        let (b, tb) = modell([pdf], schluessel: nil) { _ in .json("{}") }
        #expect(b.voraussetzung == .nichtAngemeldet)
        await b.starten()
        #expect(await ta.anfragen.isEmpty)
        #expect(await tb.anfragen.isEmpty)
        // Im Modus ohne Anmeldung genügt die Adresse.
        let (c, _) = modell([pdf], schluessel: nil, modus: .none) { _ in .json("{}") }
        #expect(c.voraussetzung == .erfuellt)
    }

    @Test("Jede Datei wird einzeln übergeben; .txt wird abgewiesen und nicht gesendet")
    func ergebnisJeDatei() async {
        let (m, t) = modell([pdf, txt]) { _ in .json(Self.ok("a.pdf")) }
        await m.starten()
        #expect(m.eintraege.map(\.status) == [.angenommen, .abgewiesen("Dateityp wird nicht unterstützt")])
        #expect(m.abgeschlossen)
        #expect(await t.anzahl(pfad: "/api/v1/upload") == 1)
        m.aufraeumen()
    }

    @Test("Netzfehler: Eintrag scheitert, erneutes Senden holt ihn nach, ohne die anderen zu wiederholen")
    func erneutSenden() async {
        let zaehler = ZaehlerFuerTests()
        let (m, t) = modell([pdf]) { _ in
            if zaehler.erhoehen() == 1 { throw URLError(.notConnectedToInternet) }
            return .json(Self.ok("a.pdf"))
        }
        await m.starten()
        #expect(m.eintraege[0].status == .fehlgeschlagen("Keine Verbindung zu Lector."))
        #expect(m.kannErneutSenden && !m.abgeschlossen)
        await m.erneutSenden()
        #expect(m.eintraege[0].status == .angenommen)
        #expect(m.abgeschlossen && !m.kannErneutSenden)
        #expect(await t.anzahl(pfad: "/api/v1/upload") == 2)
        m.aufraeumen()
    }

    @Test("401 beendet das Senden: der Rest wird nicht mehr versucht")
    func sitzungAbgelaufen() async {
        let (m, t) = modell([pdf, pdf]) { _ in .fehler(401, "not_authenticated") }
        await m.starten()
        #expect(m.anmeldungAbgelaufen)
        #expect(m.eintraege.allSatisfy { $0.status == .fehlgeschlagen("Bitte in der Lector-App neu anmelden.") })
        #expect(await t.anzahl(pfad: "/api/v1/upload") == 1)
        m.aufraeumen()
    }

    @Test("Vom Dienst abgelehnte Datei gilt als abgewiesen")
    func dienstLehntAb() async {
        let (m, _) = modell([pdf]) { _ in
            .json(#"{"results":[{"filename":"a.pdf","accepted":false,"reason":"store_failed","stored_as":null}]}"#)
        }
        await m.starten()
        #expect(m.eintraege[0].status == .abgewiesen("Der Dienst konnte die Datei nicht speichern"))
        m.aufraeumen()
    }
}

final class ZaehlerFuerTests: Sendable {
    private let wert = Mutex<Int>(0)
    func erhoehen() -> Int { wert.withLock { $0 += 1; return $0 } }
}
