import Foundation

/// Werte aus der Info.plist des laufenden Bundles (App oder Share Extension; beide tragen sie).
enum Konfiguration {
    /// Gemeinsame Keychain-Gruppe für den Zugangsschlüssel. `nil`, wenn der Build keine auflösen
    /// konnte (Simulator-Build ohne Team: `$(AppIdentifierPrefix)` bleibt leer) — dann nutzt der
    /// Keychain die Standardgruppe des Bundles.
    static var keychainZugriffsgruppe: String? {
        wert("KeychainAccessGroup")
    }

    private static func wert(_ schluessel: String) -> String? {
        guard let text = Bundle.main.object(forInfoDictionaryKey: schluessel) as? String else { return nil }
        let bereinigt = text.trimmingCharacters(in: .whitespaces)
        // Unaufgelöste Platzhalter ($(…)) und leere Werte zählen als „nicht gesetzt“.
        guard !bereinigt.isEmpty, !bereinigt.contains("$(") else { return nil }
        return bereinigt
    }
}
