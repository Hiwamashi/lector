import Foundation
import Testing
@testable import Lector

@Suite("APIClient: Header, 401 und Fehlerabbildung")
struct APIClientTests {
    private struct Aufbau {
        let transport: TransportAttrappe
        let store: SpeicherTokenStore
        let sitzung: AuthSession
        let client: APIClient
    }

    private func aufbau(
        schluessel: String? = "k1", adresse: String? = "https://lector.example.de",
        _ antworter: @escaping TransportAttrappe.Antworter
    ) -> Aufbau {
        let transport = TransportAttrappe(antworter)
        let store = SpeicherTokenStore(schluessel)
        let konfiguration = testKonfiguration(adresse: adresse)
        let sitzung = AuthSession(konfiguration: konfiguration, transport: transport, tokenStore: store)
        return Aufbau(transport: transport, store: store, sitzung: sitzung,
                      client: APIClient(konfiguration: konfiguration, transport: transport, sitzung: sitzung))
    }

    private struct Leer: Decodable, Sendable { let ok: Bool }

    @Test("Jede Anfrage trägt den Authorization-Header; Pfad und Query stimmen")
    func header() async throws {
        let a = aufbau { _ in .json(#"{"ok": true}"#) }
        let _: Leer = try await a.client.anfrage(
            "GET", "/api/v1/documents", query: [URLQueryItem(name: "status", value: "failed")])
        let anfrage = try #require(await a.transport.anfragen.first)
        #expect(anfrage.bearer == "k1")
        #expect(anfrage.url?.absoluteString == "https://lector.example.de/api/v1/documents?status=failed")
        #expect(anfrage.value(forHTTPHeaderField: "Accept") == "application/json")
    }

    @Test("Ein Unterpfad in der Serveradresse bleibt erhalten")
    func unterpfad() async throws {
        let a = aufbau(adresse: "https://example.de/lector") { _ in .json(#"{"ok": true}"#) }
        let _: Leer = try await a.client.anfrage("GET", "/api/v1/documents")
        #expect(await a.transport.anfragen.first?.url?.absoluteString == "https://example.de/lector/api/v1/documents")
    }

    @Test("Ohne Schlüssel (Modus none) geht die Anfrage ohne Header hinaus")
    func ohneSchluessel() async throws {
        let a = aufbau(schluessel: nil) { _ in .json(#"{"ok": true}"#) }
        let _: Leer = try await a.client.anfrage("GET", "/api/v1/documents")
        #expect(await a.transport.anfragen.first?.value(forHTTPHeaderField: "Authorization") == nil)
    }

    @Test("Ohne eingerichtete Adresse scheitert die Anfrage, ohne ins Netz zu gehen")
    func ohneAdresse() async {
        let a = aufbau(adresse: nil) { _ in .json("{}") }
        await #expect(throws: APIFehler.keineServeradresse) { try await a.client.senden("GET", "/api/v1/documents") }
        #expect(await a.transport.anfragen.isEmpty)
    }

    @Test("401: Schlüssel gelöscht, Zustand „Anmeldung nötig“, Adresse bleibt")
    func unauthorized() async throws {
        let a = aufbau { _ in .fehler(401, "not_authenticated") }
        await #expect(throws: APIFehler.nichtAngemeldet) { try await a.client.senden("GET", "/api/v1/documents") }
        #expect(a.store.lesen() == nil)
        #expect(await a.sitzung.zustand == .anmeldungNoetig)
        #expect(a.client.konfiguration.adresse?.absoluteString == "https://lector.example.de")
    }

    @Test("401 mit leerem Rumpf verwirft den Schlüssel ebenso")
    func unauthorizedOhneRumpf() async {
        let a = aufbau { _ in .leer(401) }
        await #expect(throws: APIFehler.nichtAngemeldet) { try await a.client.senden("GET", "/events") }
        #expect(a.store.lesen() == nil)
    }

    @Test("5xx: Schlüssel bleibt, Zustand bleibt angemeldet")
    func serverfehler() async {
        let a = aufbau { _ in .fehler(500, "discard_failed") }
        await #expect(throws: APIFehler.server(status: 500, code: .verwerfenFehlgeschlagen, meldung: "Meldung")) {
            try await a.client.senden("POST", "/api/v1/documents/1/discard")
        }
        #expect(a.store.lesen() == "k1")
        #expect(await a.sitzung.zustand == .angemeldet)
    }

    @Test("5xx ohne Fehlerformat (etwa Proxy-Seite): unbekannter Code, Schlüssel bleibt")
    func serverfehlerOhneFormat() async {
        let a = aufbau { _ in .json(502, "<html>Bad Gateway</html>") }
        await #expect(throws: APIFehler.server(status: 502, code: .unbekannt, meldung: nil)) {
            try await a.client.senden("GET", "/api/v1/documents")
        }
        #expect(a.store.lesen() == "k1")
    }

    @Test("Netzfehler: Schlüssel bleibt")
    func netzfehler() async {
        let transport = TransportOhneNetz()
        let store = SpeicherTokenStore("k1")
        let konfiguration = testKonfiguration()
        let sitzung = AuthSession(konfiguration: konfiguration, transport: transport, tokenStore: store)
        let client = APIClient(konfiguration: konfiguration, transport: transport, sitzung: sitzung)
        await #expect(throws: APIFehler.keinNetz) { try await client.senden("GET", "/api/v1/documents") }
        #expect(store.lesen() == "k1")
        #expect(await sitzung.zustand == .angemeldet)
    }

    @Test("Ein später gespeicherter neuer Schlüssel überlebt das 401 der alten Anfrage")
    func neuerSchluesselBleibt() async throws {
        let a = aufbau { _ in .leer(401) }
        // Die Anfrage ging mit k1 hinaus; währenddessen meldet sich die Person neu an.
        try a.store.speichern("k2")
        await a.sitzung.sitzungAbgelaufen(abgelehnt: "k1")
        #expect(a.store.lesen() == "k2")
    }

    @Test("Antwort mit unerwartetem JSON wird zu ungueltigeAntwort")
    func ungueltig() async {
        let a = aufbau { _ in .json(#"{"unerwartet": 1}"#) }
        await #expect(throws: APIFehler.ungueltigeAntwort) {
            let _: Leer = try await a.client.anfrage("GET", "/api/v1/documents")
        }
    }

    @Test("Alle Fehlercodes des Vertrags werden abgebildet")
    func fehlercodes() async {
        let tabelle: [(String, FehlerCode)] = [
            ("not_authenticated", .nichtAngemeldet), ("not_found", .nichtGefunden), ("not_blocked", .nichtAngehalten),
            ("discard_failed", .verwerfenFehlgeschlagen), ("no_files", .keineDateien),
            ("invalid_request", .ungueltigeAnfrage), ("invalid_credentials", .ungueltigeAnmeldedaten),
            ("mfa_required", .mfaErforderlich), ("paperless_unavailable", .paperlessNichtErreichbar),
            ("throttled", .gebremst), ("etwas_neues", .unbekannt),
        ]
        for (roh, erwartet) in tabelle {
            let fehler = Anfrage.fehler(status: 400, daten: Data(#"{"error":{"code":"\#(roh)","message":"Text"}}"#.utf8))
            #expect(fehler == .server(status: 400, code: erwartet, meldung: "Text"), "Code \(roh)")
        }
    }

    @Test("Statuscodes aus dem Vertrag erreichen den Aufrufer mit Code: 404, 409")
    func statusUndCode() async {
        let a = aufbau { r in
            r.url?.path.hasSuffix("/release") == true ? .fehler(409, "not_blocked", "Nicht mehr angehalten.") : .fehler(404, "not_found")
        }
        await #expect(throws: APIFehler.server(status: 409, code: .nichtAngehalten, meldung: "Nicht mehr angehalten.")) {
            try await a.client.senden("POST", "/api/v1/documents/3/release")
        }
        await #expect(throws: APIFehler.server(status: 404, code: .nichtGefunden, meldung: "Meldung")) {
            try await a.client.senden("GET", "/api/v1/documents/99")
        }
        #expect(a.store.lesen() == "k1")
    }

    @Test("Eine fertige Anfrage für Ereignisstrom und Upload trägt Adresse und Schlüssel")
    func authentifizierteAnfrage() async throws {
        let a = aufbau { _ in .json("{}") }
        let anfrage = try await a.client.authentifizierteAnfrage("GET", "/events")
        #expect(anfrage.url?.absoluteString == "https://lector.example.de/events")
        #expect(anfrage.bearer == "k1")
    }
}
