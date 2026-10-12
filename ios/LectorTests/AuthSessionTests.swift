import Foundation
import Testing
@testable import Lector

@Suite("AuthSession: Anmelden, Abmelden")
struct AuthSessionTests {
    private func sitzung(
        schluessel: String? = nil, transport: any Transport
    ) -> (AuthSession, SpeicherTokenStore, ServerKonfiguration) {
        let store = SpeicherTokenStore(schluessel)
        let konfiguration = testKonfiguration()
        return (AuthSession(konfiguration: konfiguration, transport: transport, tokenStore: store), store, konfiguration)
    }

    @Test("Anfangszustand folgt dem Schlüssel")
    func anfangszustand() async {
        #expect(AuthSession.anfangszustand(tokenStore: SpeicherTokenStore("k")) == .angemeldet)
        #expect(AuthSession.anfangszustand(tokenStore: SpeicherTokenStore()) == .anmeldungNoetig)
    }

    @Test("Erfolgreiche Anmeldung speichert den Schlüssel und meldet „angemeldet“")
    func erfolg() async throws {
        let transport = TransportAttrappe { _ in .json(#"{"token":"neu","username":"anna"}"#) }
        let (s, store, _) = sitzung(transport: transport)
        try await s.anmelden(nutzername: "anna", passwort: "geheim", code: "123456")
        #expect(store.lesen() == "neu")
        #expect(await s.zustand == .angemeldet)
        let anfrage = try #require(await transport.anfragen(pfad: "/api/v1/login").first)
        #expect(anfrage.httpMethod == "POST")
        #expect(anfrage.value(forHTTPHeaderField: "Content-Type") == "application/json")
        #expect(anfrage.jsonRumpf?["username"] as? String == "anna")
        #expect(anfrage.jsonRumpf?["code"] as? String == "123456")
        #expect(anfrage.value(forHTTPHeaderField: "Authorization") == nil)
    }

    @Test("Leerer MFA-Code geht als null hinaus")
    func leererCode() async throws {
        let transport = TransportAttrappe { _ in .json(#"{"token":"neu","username":"anna"}"#) }
        let (s, _, _) = sitzung(transport: transport)
        try await s.anmelden(nutzername: "anna", passwort: "geheim", code: "  ")
        #expect(await transport.anfragen.first?.jsonRumpf?["code"] is NSNull)
    }

    @Test("Die vier Ablehnungsgründe sind unterscheidbar und lassen keinen Schlüssel zurück")
    func ablehnungen() async {
        let tabelle: [(AttrappenAntwort, AnmeldeFehler)] = [
            (.fehler(401, "invalid_credentials"), .ungueltigeAnmeldedaten),
            (.fehler(401, "mfa_required"), .mfaErforderlich),
            (.fehler(503, "paperless_unavailable"), .paperlessNichtErreichbar),
            (.fehler(429, "throttled"), .gebremst),
            (.fehler(415, "invalid_request"), .unerwartet(status: 415)),
            (.json(500, "<html>"), .unerwartet(status: 500)),
        ]
        for (antwort, erwartet) in tabelle {
            let transport = TransportAttrappe { _ in antwort }
            let (s, store, _) = sitzung(transport: transport)
            await #expect(throws: erwartet) { try await s.anmelden(nutzername: "a", passwort: "b", code: nil) }
            #expect(store.lesen() == nil)
            #expect(await s.zustand == .anmeldungNoetig)
        }
    }

    @Test("Anmelden ohne Netz meldet keinNetz")
    func ohneNetz() async {
        let (s, _, _) = sitzung(transport: TransportOhneNetz())
        await #expect(throws: AnmeldeFehler.keinNetz) { try await s.anmelden(nutzername: "a", passwort: "b", code: nil) }
    }

    @Test("Abmelden meldet beim Dienst ab, mit Schlüssel, und löscht ihn")
    func abmelden() async throws {
        let transport = TransportAttrappe { _ in .leer(204) }
        let (s, store, _) = sitzung(schluessel: "k1", transport: transport)
        await s.abmelden()
        let anfrage = try #require(await transport.anfragen(pfad: "/api/v1/logout").first)
        #expect(anfrage.bearer == "k1")
        #expect(store.lesen() == nil)
        #expect(await s.zustand == .anmeldungNoetig)
    }

    @Test("Abmelden ohne Netz entfernt den Schlüssel trotzdem")
    func abmeldenOhneNetz() async {
        let (s, store, _) = sitzung(schluessel: "k1", transport: TransportOhneNetz())
        await s.abmelden()
        #expect(store.lesen() == nil)
        #expect(await s.zustand == .anmeldungNoetig)
    }

    @Test("Abmelden bei einem Serverfehler entfernt den Schlüssel ebenso")
    func abmeldenServerfehler() async {
        let (s, store, _) = sitzung(schluessel: "k1", transport: TransportAttrappe { _ in .fehler(500, "x") })
        await s.abmelden()
        #expect(store.lesen() == nil)
    }

    @Test("Die Zustandsfolge liefert den aktuellen Zustand und jede Änderung")
    func zustandsfolge() async {
        let (s, _, _) = sitzung(schluessel: "k1", transport: TransportOhneNetz())
        var folge = await s.zustandsfolge().makeAsyncIterator()
        #expect(await folge.next() == .angemeldet)
        await s.abmelden()
        #expect(await folge.next() == .anmeldungNoetig)
    }
}
