import Foundation
import Testing
@testable import Lector

/// Echter Keychain (Simulator): die Tests laufen im gehosteten App-Prozess und tragen dessen Entitlements.
/// Jeder Test nutzt einen eigenen Dienstnamen und räumt am Ende auf.
@Suite("TokenStore (Keychain)", .serialized)
struct TokenStoreTests {
    private func store(gruppe: String? = nil) -> KeychainTokenStore {
        KeychainTokenStore(dienst: "test.\(UUID().uuidString)", zugriffsgruppe: gruppe)
    }

    @Test("Ohne Eintrag liefert Lesen nichts")
    func leer() {
        #expect(store().lesen() == nil)
    }

    @Test("Speichern und Lesen ergibt denselben Schlüssel")
    func speichernLesen() throws {
        let store = store()
        defer { store.loeschen() }
        try store.speichern("a1.b2")
        #expect(store.lesen() == "a1.b2")
    }

    @Test("Erneutes Speichern ersetzt den Schlüssel")
    func ueberschreiben() throws {
        let store = store()
        defer { store.loeschen() }
        try store.speichern("a1")
        try store.speichern("a2")
        #expect(store.lesen() == "a2")
    }

    @Test("Löschen entfernt den Schlüssel, auch ein zweites Mal ohne Fehler")
    func loeschen() throws {
        let store = store()
        try store.speichern("a1")
        store.loeschen()
        store.loeschen()
        #expect(store.lesen() == nil)
    }

    @Test("Zwei Dienste stören einander nicht")
    func getrennteDienste() throws {
        let a = store(), b = store()
        defer { a.loeschen(); b.loeschen() }
        try a.speichern("a")
        #expect(b.lesen() == nil)
    }

    @Test("Speichern mit der konfigurierten Zugriffsgruppe klappt im Simulator")
    func mitZugriffsgruppe() throws {
        let store = store(gruppe: Konfiguration.keychainZugriffsgruppe)
        defer { store.loeschen() }
        try store.speichern("g1")
        #expect(store.lesen() == "g1")
    }
}
