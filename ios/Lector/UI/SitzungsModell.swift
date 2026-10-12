import Foundation
import Observation

/// Brücke zwischen `AuthSession` (Actor), der Serveradresse und SwiftUI: hält Einrichtung,
/// Zugangsmodus, Sitzungszustand und die Anmelde-Rückmeldung beobachtbar auf dem Main-Actor.
///
/// Die Wurzelansicht entscheidet daran: `einrichtungNoetig` → Einrichtung, `anmeldungNoetig` →
/// Anmeldung, sonst Hauptansicht.
@MainActor
@Observable
final class SitzungsModell {
    private(set) var zustand: Sitzungszustand
    private(set) var serverAdresse: URL?
    /// Zugangsmodus laut letzter Prüfung beim Dienst; `nil` = unbekannt (gilt wie `paperless`).
    private(set) var authModus: AuthModus?
    /// „Server wechseln“ läuft: Die Einrichtung ist offen, obwohl eine Adresse gespeichert ist.
    private(set) var einrichtungAktiv = false
    private(set) var laeuft = false
    /// Meldung für den Anmeldebildschirm; `nil`, wenn nichts anzuzeigen ist.
    private(set) var fehlermeldung: String?
    /// Die letzte Ablehnung war „MFA-Code erforderlich“ (kein Fehler, sondern Aufforderung).
    private(set) var mfaErforderlich = false
    /// Hinweis aus der Prüfung beim Start (falsche Version, kein Lector mehr unter der Adresse).
    private(set) var serverHinweis: String?

    private let sitzung: AuthSession
    private let konfiguration: ServerKonfiguration
    private let transport: any Transport

    init(sitzung: AuthSession, konfiguration: ServerKonfiguration, transport: any Transport, anfangszustand: Sitzungszustand) {
        self.sitzung = sitzung
        self.konfiguration = konfiguration
        self.transport = transport
        self.zustand = anfangszustand
        self.serverAdresse = konfiguration.adresse
        self.authModus = konfiguration.authModus
    }

    var einrichtungNoetig: Bool { serverAdresse == nil || einrichtungAktiv }

    /// Im Modus `none` gibt es keine Anmeldung, auch ohne Schlüssel.
    var anmeldungNoetig: Bool { authModus != AuthModus.none && zustand == .anmeldungNoetig }

    /// Abmelden bietet nur der Modus `paperless`: Ohne Anmeldung gibt es nichts abzumelden.
    var kannAbmelden: Bool { authModus != AuthModus.none }

    /// Folgt dem Zustand der Sitzung, bis das Modell verschwindet.
    func beobachten() async {
        for await neu in await sitzung.zustandsfolge() {
            zustand = neu
        }
    }

    // MARK: - Einrichtung

    /// Nach erfolgreicher Prüfung und Speicherung der Adresse (`EinrichtungsModell`).
    func einrichtungAbgeschlossen() {
        serverAdresse = konfiguration.adresse
        authModus = konfiguration.authModus
        einrichtungAktiv = false
        serverHinweis = nil
        fehlermeldung = nil
        mfaErforderlich = false
    }

    func einrichtungAbbrechen() {
        einrichtungAktiv = false
    }

    /// Prüft beim Start, ob unter der gespeicherten Adresse noch ein passender Lector antwortet,
    /// und übernimmt einen geänderten Zugangsmodus. Ein Netzfehler ist kein Befund.
    func serverPruefen() async {
        guard let adresse = serverAdresse, !einrichtungAktiv else { return }
        do {
            let info = try await ServerPruefung.pruefen(adresse: adresse, transport: transport)
            serverHinweis = nil
            if info.authMode != authModus {
                konfiguration.authModusSetzen(info.authMode)
                authModus = info.authMode
            }
        } catch ServerPruefung.Fehler.nichtErreichbar {
            return
        } catch ServerPruefung.Fehler.andereVersion(let gemeldet) {
            serverHinweis = EinrichtungsModell.text(fuer: .andereVersion(gemeldet: gemeldet))
        } catch {
            serverHinweis = EinrichtungsModell.text(fuer: .keinLector)
        }
    }

    // MARK: - Anmelden und Abmelden

    func anmelden(nutzername: String, passwort: String, code: String) async {
        guard !laeuft else { return }
        laeuft = true
        fehlermeldung = nil
        mfaErforderlich = false
        defer { laeuft = false }
        do {
            try await sitzung.anmelden(
                nutzername: nutzername.trimmingCharacters(in: .whitespaces), passwort: passwort, code: code)
        } catch {
            mfaErforderlich = (error as? AnmeldeFehler) == .mfaErforderlich
            fehlermeldung = Self.text(fuer: error)
        }
    }

    /// Beendet die Sitzung beim Dienst, soweit erreichbar; der Schlüssel ist danach in jedem Fall weg.
    func abmelden() async {
        await sitzung.abmelden()
        zustand = await sitzung.zustand
        fehlermeldung = nil
        mfaErforderlich = false
    }

    /// Beendet die Anmeldung beim bisherigen Server (Schlüssel weg) und öffnet die Einrichtung mit
    /// der zuletzt bestätigten Adresse. Die alte Adresse gilt, bis eine neue bestätigt ist.
    func serverWechseln() async {
        await abmelden()
        einrichtungAktiv = true
    }

    /// Text für jeden Fehler des Anmeldewegs; `nil` = nichts anzeigen (Abbruch durch die Person).
    nonisolated static func text(fuer fehler: Error) -> String? {
        switch fehler {
        case let fehler as AnmeldeFehler: anmeldetext(fuer: fehler)
        case is KeychainFehler: "Die Anmeldung konnte nicht gespeichert werden. Bitte versuche es erneut."
        case APIFehler.ungueltigeAntwort: "Der Dienst hat unerwartet geantwortet. Bitte versuche es später erneut."
        case is CancellationError: nil
        default: "Die Anmeldung ist gerade nicht möglich. Bitte versuche es später erneut."
        }
    }

    /// Die vier Ablehnungsgründe des Dienstes sind unterscheidbar (Spec „Die App meldet sich wie die Weboberfläche an“).
    nonisolated static func anmeldetext(fuer fehler: AnmeldeFehler) -> String {
        switch fehler {
        case .ungueltigeAnmeldedaten: "Anmeldung fehlgeschlagen. Bitte prüfe Nutzername und Passwort."
        case .mfaErforderlich: "MFA-Code erforderlich. Bitte gib den Code deiner Authentifizierungs-App ein."
        case .paperlessNichtErreichbar: "Paperless ist nicht erreichbar. Bitte versuche es später erneut."
        case .gebremst: "Zu viele Anmeldeversuche. Bitte warte einen Moment und versuche es dann erneut."
        case .keinNetz: "Keine Verbindung zum Lector-Dienst. Bitte prüfe das Netz und versuche es erneut."
        case .keineServeradresse: "Es ist noch keine Serveradresse eingerichtet."
        case .unerwartet: "Die Anmeldung ist gerade nicht möglich. Bitte versuche es später erneut."
        }
    }

    nonisolated static func eingabeGueltig(nutzername: String, passwort: String) -> Bool {
        !nutzername.trimmingCharacters(in: .whitespaces).isEmpty && !passwort.isEmpty
    }
}
