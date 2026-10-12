import Foundation

/// Die verdrahteten Bausteine der laufenden App. Tests bauen ihre eigenen aus Attrappen.
@MainActor
final class AppAbhaengigkeiten {
    let konfiguration: ServerKonfiguration
    let transport: any Transport
    let tokenStore: any TokenStore
    let authSession: AuthSession
    let apiClient: APIClient
    let ereignisQuelle: any EreignisQuelle
    let sitzung: SitzungsModell
    /// `false` in den gehosteten Unit-Tests: Sie sollen nicht ins Netz.
    let serverPruefungStartet: Bool

    init(startart: Startart = .ermitteln()) {
        let konfiguration: ServerKonfiguration
        let transport: any Transport
        let store: any TokenStore
        let quelle: any EreignisQuelle
        #if DEBUG
        konfiguration = startart.attrappe || startart.gehostetterTest
            ? ServerKonfiguration(suite: UITestStart.suite(fuer: startart)) : ServerKonfiguration()
        UITestStart.vorbereiten(startart, konfiguration: konfiguration)
        let dienst = UITestDienst(live: startart.live, uploadFehler: startart.uploadFehler, uploadAbgelehnt: startart.uploadAbgelehnt)
        transport = startart.attrappe ? UITestTransport(authModus: startart.authModus, dienst: dienst) : URLSessionTransport()
        quelle = startart.attrappe ? UITestEreignisQuelle(dienst: dienst) : URLSessionEreignisQuelle()
        store = startart.attrappe || startart.gehostetterTest
            ? SpeicherTokenStore(startart.angemeldet ? "attrappen-schluessel" : nil) : KeychainTokenStore()
        #else
        // Release: keine Attrappen, kein Testtransport (Startart ist hier immer `.standard`).
        konfiguration = ServerKonfiguration()
        transport = URLSessionTransport()
        store = KeychainTokenStore()
        quelle = URLSessionEreignisQuelle()
        #endif

        let auth = AuthSession(konfiguration: konfiguration, transport: transport, tokenStore: store)
        self.konfiguration = konfiguration
        self.transport = transport
        tokenStore = store
        authSession = auth
        ereignisQuelle = quelle
        apiClient = APIClient(konfiguration: konfiguration, transport: transport, sitzung: auth)
        serverPruefungStartet = startart.serverPruefungStartet
        sitzung = SitzungsModell(
            sitzung: auth, konfiguration: konfiguration, transport: transport,
            anfangszustand: AuthSession.anfangszustand(tokenStore: store))
    }
}

/// Wie die App startet. In Release immer `.standard`; in Debug lassen Startargumente den UI-Tests
/// eine Attrappen-Sitzung ohne Netz und Keychain vorgeben (siehe `UITestStart`).
struct Startart: Sendable {
    /// Attrappen-Transport, flüchtiger Schlüsselspeicher und eigene Suite statt App Group.
    var attrappe = false
    /// Die Attrappen-Sitzung ist angemeldet (Schlüssel vorhanden).
    var angemeldet = false
    /// Serveradresse ist schon eingerichtet (sonst beginnt die App mit der Einrichtung).
    var adresseGesetzt = false
    /// Der Ereignisstrom der Attrappe meldet Änderungen (siehe `UITestStart`).
    var live = false
    /// Der erste Upload der Attrappe scheitert, alle weiteren gelingen.
    var uploadFehler = false
    /// Die Attrappe lehnt jede hochgeladene Datei ab.
    var uploadAbgelehnt = false
    /// Zugangsmodus der Attrappe.
    var authModus: AuthModus = .paperless
    /// Gehosteter Unit-Test: flüchtiger Speicher, keine Prüfung beim Start.
    var gehostetterTest = false
    var serverPruefungStartet = true

    static let standard = Startart()

    static func ermitteln() -> Startart {
        #if DEBUG
        return UITestStart.startart()
        #else
        return .standard
        #endif
    }
}
