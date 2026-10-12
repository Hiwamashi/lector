import Foundation
import Observation

/// Zustand der Einrichtungsansicht: Adresse eingeben, beim Dienst prüfen, bei Erfolg speichern.
/// Eine Adresse, die nicht besteht, wird nicht gespeichert.
@MainActor
@Observable
final class EinrichtungsModell {
    var eingabe: String
    private(set) var laeuft = false
    private(set) var fehlermeldung: String?

    private let konfiguration: ServerKonfiguration
    private let transport: any Transport

    /// Die zuletzt bestätigte Adresse ist vorausgefüllt.
    init(konfiguration: ServerKonfiguration, transport: any Transport) {
        self.konfiguration = konfiguration
        self.transport = transport
        self.eingabe = konfiguration.adresse?.absoluteString ?? ""
    }

    /// Prüft die Eingabe und speichert sie. `true`, wenn die Adresse bestätigt und gespeichert wurde.
    func pruefenUndSpeichern() async -> Bool {
        guard !laeuft else { return false }
        laeuft = true
        fehlermeldung = nil
        defer { laeuft = false }
        do {
            let adresse = try ServerAdresse.normalisieren(eingabe)
            let info = try await ServerPruefung.pruefen(adresse: adresse, transport: transport)
            konfiguration.speichern(adresse: adresse, authModus: info.authMode)
            eingabe = adresse.absoluteString
            return true
        } catch let fehler as ServerAdresse.Fehler {
            fehlermeldung = Self.text(fuer: fehler)
        } catch let fehler as ServerPruefung.Fehler {
            fehlermeldung = Self.text(fuer: fehler)
        } catch {
            fehlermeldung = Self.text(fuer: ServerPruefung.Fehler.keinLector)
        }
        return false
    }

    nonisolated static func text(fuer fehler: ServerAdresse.Fehler) -> String {
        switch fehler {
        case .leer: "Bitte gib die Adresse deines Lector-Dienstes ein."
        case .ungueltig: "Diese Adresse ist ungültig. Beispiel: lector.example.de"
        case .unverschluesselt:
            "Diese Adresse nutzt keine verschlüsselte Verbindung. Ohne https:// sind nur Adressen im lokalen Netz erlaubt."
        }
    }

    nonisolated static func text(fuer fehler: ServerPruefung.Fehler) -> String {
        switch fehler {
        case .nichtErreichbar:
            "Unter dieser Adresse wurde kein Lector gefunden: Der Server ist nicht erreichbar. Bitte prüfe Adresse und Verbindung."
        case .keinLector: "Unter dieser Adresse wurde kein Lector gefunden."
        case .andereVersion(let gemeldet):
            "Dieser Lector spricht eine andere Version der Schnittstelle (Version \(gemeldet)). Bitte aktualisiere die App oder den Dienst."
        }
    }
}
