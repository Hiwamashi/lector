import Foundation
import Testing
@testable import Lector

@MainActor
@Suite("Sitzungsmodell: Zustand, Anmeldetexte, Abmelden, Server wechseln")
struct SitzungsModellTests {
    private struct Aufbau {
        let modell: SitzungsModell
        let store: SpeicherTokenStore
        let konfiguration: ServerKonfiguration
        let transport: TransportAttrappe
        let sitzung: AuthSession
    }

    private func aufbau(
        schluessel: String? = nil, modus: AuthModus = .paperless, adresse: String? = "https://lector.example.de",
        _ antworter: @escaping TransportAttrappe.Antworter = { _ in .leer(204) }
    ) -> Aufbau {
        let transport = TransportAttrappe(antworter)
        let store = SpeicherTokenStore(schluessel)
        let konfiguration = testKonfiguration(adresse: adresse, modus: modus)
        let sitzung = AuthSession(konfiguration: konfiguration, transport: transport, tokenStore: store)
        let modell = SitzungsModell(
            sitzung: sitzung, konfiguration: konfiguration, transport: transport,
            anfangszustand: AuthSession.anfangszustand(tokenStore: store))
        return Aufbau(modell: modell, store: store, konfiguration: konfiguration, transport: transport, sitzung: sitzung)
    }

    // MARK: Zustand

    @Test("Ohne Adresse beginnt die App mit der Einrichtung")
    func einrichtung() {
        #expect(aufbau(adresse: nil).modell.einrichtungNoetig)
        #expect(!aufbau().modell.einrichtungNoetig)
    }

    @Test("Modus paperless ohne Schlüssel verlangt die Anmeldung, mit Schlüssel nicht")
    func anmeldungPaperless() {
        #expect(aufbau().modell.anmeldungNoetig)
        #expect(!aufbau(schluessel: "k1").modell.anmeldungNoetig)
    }

    @Test("Modus none verlangt nie eine Anmeldung und bietet kein Abmelden")
    func modusNone() {
        let a = aufbau(modus: .none)
        #expect(!a.modell.anmeldungNoetig)
        #expect(!a.modell.kannAbmelden)
        #expect(aufbau().modell.kannAbmelden)
    }

    @Test("Nach einem 401 wechselt das Modell zu „Anmeldung nötig“, die Adresse bleibt")
    func nach401() async {
        let a = aufbau(schluessel: "k1")
        #expect(!a.modell.anmeldungNoetig)
        let beobachter = Task { await a.modell.beobachten() }
        let client = APIClient(
            konfiguration: a.konfiguration, transport: TransportAttrappe { _ in .fehler(401, "not_authenticated") },
            sitzung: a.sitzung)
        _ = try? await client.senden("GET", "/api/v1/documents")
        for _ in 0..<100 where !a.modell.anmeldungNoetig { try? await Task.sleep(for: .milliseconds(20)) }
        #expect(a.modell.anmeldungNoetig)
        #expect(a.store.lesen() == nil)
        #expect(a.modell.serverAdresse?.absoluteString == "https://lector.example.de")
        #expect(!a.modell.einrichtungNoetig)
        beobachter.cancel()
    }

    // MARK: Anmeldung

    @Test("Erfolgreiche Anmeldung speichert den Schlüssel und lässt keine Meldung stehen")
    func anmeldenErfolg() async {
        let a = aufbau { _ in .json(#"{"token":"neu","username":"anna"}"#) }
        await a.modell.anmelden(nutzername: " anna ", passwort: "geheim", code: "")
        #expect(a.store.lesen() == "neu")
        #expect(a.modell.fehlermeldung == nil)
        let rumpf = await a.transport.anfragen.first?.jsonRumpf
        #expect(rumpf?["username"] as? String == "anna")
    }

    @Test("MFA-Pflicht: eigene Meldung, mfaErforderlich gesetzt; erneuter Versuch räumt ab")
    func mfa() async {
        let a = aufbau { r in
            r.jsonRumpf?["code"] is NSNull ? .fehler(401, "mfa_required") : .json(#"{"token":"neu","username":"anna"}"#)
        }
        await a.modell.anmelden(nutzername: "anna", passwort: "geheim", code: "")
        #expect(a.modell.mfaErforderlich)
        #expect(a.modell.fehlermeldung?.contains("MFA-Code") == true)
        #expect(a.store.lesen() == nil)
        await a.modell.anmelden(nutzername: "anna", passwort: "geheim", code: "123456")
        #expect(!a.modell.mfaErforderlich)
        #expect(a.modell.fehlermeldung == nil)
        #expect(a.store.lesen() == "neu")
    }

    @Test("Die vier Ablehnungsgründe haben vier verschiedene Texte")
    func vierTexte() {
        let texte = [
            SitzungsModell.anmeldetext(fuer: .ungueltigeAnmeldedaten),
            SitzungsModell.anmeldetext(fuer: .mfaErforderlich),
            SitzungsModell.anmeldetext(fuer: .paperlessNichtErreichbar),
            SitzungsModell.anmeldetext(fuer: .gebremst),
        ]
        #expect(Set(texte).count == 4)
        #expect(texte[0].contains("fehlgeschlagen"))
        #expect(texte[1].contains("MFA-Code erforderlich"))
        #expect(texte[2].contains("Paperless ist nicht erreichbar"))
        #expect(texte[3].contains("Zu viele"))
    }

    @Test("Paperless nicht erreichbar wird nicht als falsche Anmeldedaten gemeldet")
    func paperlessNichtErreichbar() async {
        let a = aufbau { _ in .fehler(503, "paperless_unavailable") }
        await a.modell.anmelden(nutzername: "anna", passwort: "geheim", code: "")
        #expect(a.modell.fehlermeldung == SitzungsModell.anmeldetext(fuer: .paperlessNichtErreichbar))
        #expect(!a.modell.mfaErforderlich)
    }

    @Test("Übrige Fehlertexte: Netz, Keychain, ungültige Antwort, Abbruch")
    func uebrige() throws {
        #expect(try #require(SitzungsModell.text(fuer: AnmeldeFehler.keinNetz)).contains("Keine Verbindung"))
        #expect(try #require(SitzungsModell.text(fuer: KeychainFehler(status: -34018))).contains("nicht gespeichert"))
        #expect(try #require(SitzungsModell.text(fuer: APIFehler.ungueltigeAntwort)).contains("unerwartet"))
        #expect(SitzungsModell.text(fuer: CancellationError()) == nil)
    }

    @Test("Vorprüfung: Nutzername und Passwort nicht leer")
    func vorpruefung() {
        #expect(SitzungsModell.eingabeGueltig(nutzername: "anna", passwort: "x"))
        #expect(!SitzungsModell.eingabeGueltig(nutzername: "  ", passwort: "x"))
        #expect(!SitzungsModell.eingabeGueltig(nutzername: "anna", passwort: ""))
    }

    // MARK: Abmelden und Server wechseln

    @Test("Abmelden ohne Netz entfernt den Schlüssel")
    func abmeldenOhneNetz() async {
        let store = SpeicherTokenStore("k1")
        let konfiguration = testKonfiguration()
        let sitzung = AuthSession(konfiguration: konfiguration, transport: TransportOhneNetz(), tokenStore: store)
        let modell = SitzungsModell(
            sitzung: sitzung, konfiguration: konfiguration, transport: TransportOhneNetz(), anfangszustand: .angemeldet)
        await modell.abmelden()
        #expect(store.lesen() == nil)
        #expect(await sitzung.zustand == .anmeldungNoetig)
    }

    @Test("Abmelden meldet beim Dienst ab und lässt die Adresse stehen")
    func abmelden() async {
        let a = aufbau(schluessel: "k1")
        await a.modell.abmelden()
        #expect(await a.transport.anzahl(pfad: "/api/v1/logout") == 1)
        #expect(a.store.lesen() == nil)
        #expect(a.konfiguration.adresse != nil)
    }

    @Test("Server wechseln beendet die Anmeldung beim bisherigen Server und öffnet die Einrichtung")
    func serverWechseln() async {
        let a = aufbau(schluessel: "k1")
        await a.modell.serverWechseln()
        #expect(a.store.lesen() == nil)
        #expect(await a.transport.anzahl(pfad: "/api/v1/logout") == 1)
        #expect(a.modell.einrichtungNoetig)
        // Die bisherige Adresse gilt bis zur Bestätigung einer neuen; Abbrechen führt zurück.
        #expect(a.modell.serverAdresse?.absoluteString == "https://lector.example.de")
        a.modell.einrichtungAbbrechen()
        #expect(!a.modell.einrichtungNoetig)
        #expect(a.modell.anmeldungNoetig)
    }

    @Test("Nach bestätigter neuer Adresse übernimmt das Modell Adresse und Zugangsmodus")
    func einrichtungAbgeschlossen() async {
        let a = aufbau(schluessel: "k1")
        await a.modell.serverWechseln()
        a.konfiguration.speichern(adresse: URL(string: "https://neu.example.de")!, authModus: .none)
        a.modell.einrichtungAbgeschlossen()
        #expect(a.modell.serverAdresse?.absoluteString == "https://neu.example.de")
        #expect(!a.modell.einrichtungNoetig)
        #expect(!a.modell.anmeldungNoetig, "Modus none braucht keine Anmeldung")
    }

    // MARK: Prüfung beim Start

    @Test("Prüfung beim Start übernimmt einen geänderten Zugangsmodus")
    func startpruefungModus() async {
        let a = aufbau(modus: .paperless) { _ in .json(#"{"service":"lector","api_version":1,"auth_mode":"none"}"#) }
        await a.modell.serverPruefen()
        #expect(a.modell.authModus == AuthModus.none)
        #expect(a.konfiguration.authModus == AuthModus.none)
        #expect(a.modell.serverHinweis == nil)
    }

    @Test("Prüfung beim Start: falsche Version und fehlender Lector ergeben einen Hinweis, ein Netzfehler nicht")
    func startpruefungHinweise() async {
        let version = aufbau { _ in .json(#"{"service":"lector","api_version":2,"auth_mode":"none"}"#) }
        await version.modell.serverPruefen()
        #expect(version.modell.serverHinweis?.contains("Version 2") == true)

        let keiner = aufbau { _ in .json(404, "{}") }
        await keiner.modell.serverPruefen()
        #expect(keiner.modell.serverHinweis?.contains("kein Lector") == true)

        let netz = SitzungsModell(
            sitzung: AuthSession(konfiguration: testKonfiguration(), transport: TransportOhneNetz(), tokenStore: SpeicherTokenStore()),
            konfiguration: testKonfiguration(), transport: TransportOhneNetz(), anfangszustand: .anmeldungNoetig)
        await netz.serverPruefen()
        #expect(netz.serverHinweis == nil)
    }
}
