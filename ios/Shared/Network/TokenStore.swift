import Foundation
import Security
import Synchronization

/// Ablage des Zugangsschlüssels. Synchron, weil der Keychain-Zugriff kurz ist und `AuthSession`
/// (Actor) ihn ohnehin serialisiert. Fürs Testen austauschbar.
protocol TokenStore: Sendable {
    /// `nil`, wenn nichts gespeichert ist — oder der Keychain gerade nicht lesbar ist. Beides gilt
    /// als „kein Schlüssel“.
    func lesen() -> String?
    func speichern(_ schluessel: String) throws
    /// Idempotent: Löschen ohne Eintrag ist kein Fehler.
    func loeschen()
}

struct KeychainFehler: Error, Equatable {
    let status: OSStatus
}

/// Keychain-Ablage: ein Passwort-Eintrag mit dem Schlüssel als UTF-8-Text. App und Share
/// Extension lesen denselben Eintrag über die gemeinsame Zugriffsgruppe.
///
/// `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`: lesbar nach dem ersten Entsperren seit dem
/// Start, aber weder in Backups noch auf einem neuen Gerät.
struct KeychainTokenStore: TokenStore {
    let dienst: String
    /// `nil` = Standardgruppe der App (keine `kSecAttrAccessGroup`), siehe `Konfiguration`.
    let zugriffsgruppe: String?

    private static let konto = "zugangsschluessel"

    init(dienst: String = "me.krinke.lector.token", zugriffsgruppe: String? = Konfiguration.keychainZugriffsgruppe) {
        self.dienst = dienst
        self.zugriffsgruppe = zugriffsgruppe
    }

    private var suche: [String: Any] {
        var suche: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: dienst,
            kSecAttrAccount as String: Self.konto,
        ]
        if let zugriffsgruppe { suche[kSecAttrAccessGroup as String] = zugriffsgruppe }
        return suche
    }

    func lesen() -> String? {
        var abfrage = suche
        abfrage[kSecReturnData as String] = true
        abfrage[kSecMatchLimit as String] = kSecMatchLimitOne
        var ergebnis: CFTypeRef?
        guard SecItemCopyMatching(abfrage as CFDictionary, &ergebnis) == errSecSuccess,
              let daten = ergebnis as? Data else { return nil }
        return String(data: daten, encoding: .utf8)
    }

    func speichern(_ schluessel: String) throws {
        let daten = Data(schluessel.utf8)
        let zugaenglichkeit = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        let update = SecItemUpdate(
            suche as CFDictionary,
            [kSecValueData as String: daten, kSecAttrAccessible as String: zugaenglichkeit] as CFDictionary)
        switch update {
        case errSecSuccess:
            return
        case errSecItemNotFound:
            var neu = suche
            neu[kSecValueData as String] = daten
            neu[kSecAttrAccessible as String] = zugaenglichkeit
            let status = SecItemAdd(neu as CFDictionary, nil)
            guard status == errSecSuccess else { throw KeychainFehler(status: status) }
        default:
            throw KeychainFehler(status: update)
        }
    }

    func loeschen() {
        SecItemDelete(suche as CFDictionary)
    }
}

/// Ablage im Arbeitsspeicher — für Tests und die Attrappen-Sitzung der UI-Tests, ohne Keychain.
final class SpeicherTokenStore: TokenStore {
    private let schluessel: Mutex<String?>

    init(_ schluessel: String? = nil) {
        self.schluessel = Mutex(schluessel)
    }

    func lesen() -> String? { schluessel.withLock { $0 } }
    func speichern(_ neu: String) throws { schluessel.withLock { $0 = neu } }
    func loeschen() { schluessel.withLock { $0 = nil } }
}
