import Foundation
import Testing
@testable import Lector

@Suite("Serveradresse: Normalisierung und Netzklassifizierung")
struct ServerAdresseTests {
    @Test("Fehlendes Schema wird zu https, Schrägstrich am Ende entfällt", arguments: [
        ("lector.example.de", "https://lector.example.de"),
        ("  lector.example.de/  ", "https://lector.example.de"),
        ("https://lector.example.de//", "https://lector.example.de"),
        ("HTTPS://Lector.Example.de", "https://Lector.Example.de"),
        ("lector.example.de:8443", "https://lector.example.de:8443"),
        ("example.de/lector/", "https://example.de/lector"),
        ("https://lector.example.de/?x=1#a", "https://lector.example.de"),
    ])
    func normalisieren(eingabe: String, erwartet: String) throws {
        #expect(try ServerAdresse.normalisieren(eingabe).absoluteString == erwartet)
    }

    @Test("http ist im lokalen Netz zulässig", arguments: [
        "http://lector.local", "http://nas", "http://192.168.1.20:8080", "http://10.0.0.5",
        "http://172.16.0.1", "http://localhost:8000", "http://127.0.0.1:8000", "http://[::1]:8000",
    ])
    func httpLokal(eingabe: String) throws {
        let url = try ServerAdresse.normalisieren(eingabe)
        #expect(url.scheme == "http")
    }

    @Test("http außerhalb des lokalen Netzes wird abgelehnt", arguments: [
        "http://lector.example.de", "http://8.8.8.8", "http://172.32.0.1", "http://192.169.1.1",
    ])
    func httpOeffentlich(eingabe: String) {
        #expect(throws: ServerAdresse.Fehler.unverschluesselt) { try ServerAdresse.normalisieren(eingabe) }
    }

    @Test("Leere und ungültige Eingaben")
    func ungueltig() {
        #expect(throws: ServerAdresse.Fehler.leer) { try ServerAdresse.normalisieren("   ") }
        #expect(throws: ServerAdresse.Fehler.ungueltig) { try ServerAdresse.normalisieren("ftp://lector.example.de") }
        #expect(throws: ServerAdresse.Fehler.ungueltig) { try ServerAdresse.normalisieren("https://") }
        #expect(throws: ServerAdresse.Fehler.ungueltig) { try ServerAdresse.normalisieren("lector example.de") }
    }

    @Test("Netzklassifizierung: .local, private IPv4, Name ohne Punkt, öffentlicher Host")
    func klassifizierung() {
        #expect(ServerAdresse.istLokalesNetz(host: "drucker.local"))
        #expect(ServerAdresse.istLokalesNetz(host: "Drucker.LOCAL"))
        #expect(ServerAdresse.istLokalesNetz(host: "nas"))
        #expect(ServerAdresse.istLokalesNetz(host: "192.168.178.2"))
        #expect(ServerAdresse.istLokalesNetz(host: "10.1.2.3"))
        #expect(ServerAdresse.istLokalesNetz(host: "172.20.1.1"))
        #expect(ServerAdresse.istLokalesNetz(host: "169.254.1.1"))
        #expect(ServerAdresse.istLokalesNetz(host: "fd12::1"))
        #expect(ServerAdresse.istLokalesNetz(host: "fe80::1"))
        #expect(!ServerAdresse.istLokalesNetz(host: "lector.example.de"))
        #expect(!ServerAdresse.istLokalesNetz(host: "1.1.1.1"))
        #expect(!ServerAdresse.istLokalesNetz(host: "172.15.0.1"))
        #expect(!ServerAdresse.istLokalesNetz(host: "2001:db8::1"))
        #expect(!ServerAdresse.istLokalesNetz(host: "evil.local.example.de"))
    }
}

@Suite("Serverprüfung beim Dienst")
struct ServerPruefungTests {
    private let adresse = URL(string: "https://lector.example.de")!

    private func pruefen(_ antwort: AttrappenAntwort) async throws -> ServerInfo {
        try await ServerPruefung.pruefen(adresse: adresse, transport: TransportAttrappe { _ in antwort })
    }

    @Test("Ein Lector mit Version 1 besteht, der Zugangsmodus kommt mit")
    func erfolg() async throws {
        let info = try await pruefen(.json(#"{"service":"lector","api_version":1,"auth_mode":"none"}"#))
        #expect(info.authMode == AuthModus.none)
    }

    @Test("Die Prüfung ruft GET /api/info ohne Schlüssel")
    func anfrage() async throws {
        let transport = TransportAttrappe { _ in .json(#"{"service":"lector","api_version":1,"auth_mode":"paperless"}"#) }
        _ = try await ServerPruefung.pruefen(adresse: adresse, transport: transport)
        let anfrage = try #require(await transport.anfragen.first)
        #expect(anfrage.httpMethod == "GET")
        #expect(anfrage.url?.absoluteString == "https://lector.example.de/api/info")
        #expect(anfrage.value(forHTTPHeaderField: "Authorization") == nil)
    }

    @Test("Kein Lector: 404, anderer Dienst, kein JSON, anderer Status")
    func keinLector() async {
        let faelle: [AttrappenAntwort] = [
            .json(404, #"{"detail":"Not Found"}"#),
            .json(#"{"service":"paperless","api_version":1,"auth_mode":"none"}"#),
            .json("<html>Willkommen</html>"),
            .json(500, #"{"service":"lector","api_version":1,"auth_mode":"none"}"#),
            .json(#"{"service":"lector","api_version":1}"#),
        ]
        for antwort in faelle {
            await #expect(throws: ServerPruefung.Fehler.keinLector) { _ = try await pruefen(antwort) }
        }
    }

    @Test("Falsche Schnittstellenversion nennt die gemeldete Version")
    func andereVersion() async {
        await #expect(throws: ServerPruefung.Fehler.andereVersion(gemeldet: 2)) {
            _ = try await pruefen(.json(#"{"service":"lector","api_version":2,"auth_mode":"none"}"#))
        }
    }

    @Test("Ohne Netz ist der Dienst nicht erreichbar")
    func nichtErreichbar() async {
        await #expect(throws: ServerPruefung.Fehler.nichtErreichbar) {
            _ = try await ServerPruefung.pruefen(adresse: adresse, transport: TransportOhneNetz())
        }
    }
}
