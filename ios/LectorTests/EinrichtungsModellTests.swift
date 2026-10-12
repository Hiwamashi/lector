import Foundation
import Testing
@testable import Lector

@MainActor
@Suite("Einrichtung der Serveradresse")
struct EinrichtungsModellTests {
    private let lector = AttrappenAntwort.json(#"{"service":"lector","api_version":1,"auth_mode":"paperless"}"#)

    @Test("Gültige Adresse: übernommen, gespeichert mit Zugangsmodus")
    func erfolg() async {
        let konfiguration = testKonfiguration(adresse: nil)
        let modell = EinrichtungsModell(konfiguration: konfiguration, transport: TransportAttrappe { [lector] _ in lector })
        modell.eingabe = "lector.example.de/"
        #expect(await modell.pruefenUndSpeichern())
        #expect(konfiguration.adresse?.absoluteString == "https://lector.example.de")
        #expect(konfiguration.authModus == .paperless)
        #expect(modell.fehlermeldung == nil)
        #expect(modell.eingabe == "https://lector.example.de")
    }

    @Test("Adresse ohne Lector: nicht gespeichert, Meldung nennt es")
    func keinLector() async {
        let konfiguration = testKonfiguration(adresse: nil)
        let modell = EinrichtungsModell(konfiguration: konfiguration, transport: TransportAttrappe { _ in .json(404, "{}") })
        modell.eingabe = "https://example.de"
        #expect(await modell.pruefenUndSpeichern() == false)
        #expect(konfiguration.adresse == nil)
        #expect(modell.fehlermeldung?.contains("kein Lector gefunden") == true)
    }

    @Test("Falsche api_version: nicht gespeichert, Meldung nennt die Version")
    func falscheVersion() async {
        let konfiguration = testKonfiguration(adresse: nil)
        let modell = EinrichtungsModell(
            konfiguration: konfiguration,
            transport: TransportAttrappe { _ in .json(#"{"service":"lector","api_version":2,"auth_mode":"none"}"#) })
        modell.eingabe = "example.de"
        #expect(await modell.pruefenUndSpeichern() == false)
        #expect(konfiguration.adresse == nil)
        #expect(modell.fehlermeldung?.contains("Version 2") == true)
    }

    @Test("Server nicht erreichbar: nicht gespeichert")
    func nichtErreichbar() async {
        let konfiguration = testKonfiguration(adresse: nil)
        let modell = EinrichtungsModell(konfiguration: konfiguration, transport: TransportOhneNetz())
        modell.eingabe = "example.de"
        #expect(await modell.pruefenUndSpeichern() == false)
        #expect(konfiguration.adresse == nil)
        #expect(modell.fehlermeldung?.contains("nicht erreichbar") == true)
    }

    @Test("http außerhalb des lokalen Netzes: Hinweis auf fehlende Verschlüsselung, kein Netzzugriff")
    func unverschluesselt() async {
        let transport = TransportAttrappe { [lector] _ in lector }
        let modell = EinrichtungsModell(konfiguration: testKonfiguration(adresse: nil), transport: transport)
        modell.eingabe = "http://lector.example.de"
        #expect(await modell.pruefenUndSpeichern() == false)
        #expect(modell.fehlermeldung?.contains("verschlüsselte Verbindung") == true)
        #expect(await transport.anfragen.isEmpty)
    }

    @Test("http im lokalen Netz wird geprüft und gespeichert")
    func httpLokal() async {
        let konfiguration = testKonfiguration(adresse: nil)
        let modell = EinrichtungsModell(konfiguration: konfiguration, transport: TransportAttrappe { [lector] _ in lector })
        modell.eingabe = "http://nas.local:8000"
        #expect(await modell.pruefenUndSpeichern())
        #expect(konfiguration.adresse?.absoluteString == "http://nas.local:8000")
    }

    @Test("Leere Eingabe: Hinweis, kein Netzzugriff")
    func leer() async {
        let transport = TransportAttrappe { [lector] _ in lector }
        let modell = EinrichtungsModell(konfiguration: testKonfiguration(adresse: nil), transport: transport)
        #expect(await modell.pruefenUndSpeichern() == false)
        #expect(modell.fehlermeldung != nil)
        #expect(await transport.anfragen.isEmpty)
    }

    @Test("Die zuletzt bestätigte Adresse ist vorausgefüllt")
    func vorausgefuellt() {
        let konfiguration = testKonfiguration(adresse: "https://lector.example.de")
        #expect(EinrichtungsModell(konfiguration: konfiguration, transport: TransportOhneNetz()).eingabe
                == "https://lector.example.de")
        #expect(EinrichtungsModell(konfiguration: testKonfiguration(adresse: nil), transport: TransportOhneNetz()).eingabe == "")
    }

    @Test("Ein gescheiterter Wechsel lässt die bisherige Adresse stehen")
    func bisherigeAdresseBleibt() async {
        let konfiguration = testKonfiguration(adresse: "https://alt.example.de", modus: .none)
        let modell = EinrichtungsModell(konfiguration: konfiguration, transport: TransportAttrappe { _ in .json(404, "{}") })
        modell.eingabe = "https://neu.example.de"
        #expect(await modell.pruefenUndSpeichern() == false)
        #expect(konfiguration.adresse?.absoluteString == "https://alt.example.de")
        #expect(konfiguration.authModus == AuthModus.none)
    }
}

@Suite("ServerKonfiguration: Ablage in der App Group")
struct ServerKonfigurationTests {
    @Test("Speichern, neu lesen (Neustart), zurücksetzen")
    func neustart() throws {
        let suite = "test.\(UUID().uuidString)"
        ServerKonfiguration(suite: suite).speichern(adresse: try #require(URL(string: "https://lector.example.de")), authModus: .paperless)
        // Eine neue Instanz auf derselben Suite sieht den Wert, wie die App nach einem Neustart.
        let neu = ServerKonfiguration(suite: suite)
        #expect(neu.adresse?.absoluteString == "https://lector.example.de")
        #expect(neu.authModus == .paperless)
        neu.zuruecksetzen()
        #expect(ServerKonfiguration(suite: suite).adresse == nil)
    }

    @Test("Ohne Einrichtung ist nichts gesetzt; fremde Suites stören einander nicht")
    func leer() throws {
        let a = testKonfiguration(adresse: nil), b = testKonfiguration(adresse: "https://b.example.de")
        #expect(a.adresse == nil && a.authModus == nil)
        #expect(b.adresse != nil)
    }
}
