import Foundation

/// Die eingerichtete Serveradresse samt Zugangsmodus, dauerhaft in den geteilten `UserDefaults`
/// der App Group (`group.me.krinke.lector`). So sehen App und Share Extension dieselbe Einrichtung.
///
/// Wertetyp mit Suite-Name statt geteiltem `UserDefaults`-Objekt, weil dieses nicht `Sendable`
/// ist. Tests geben eine eigene Suite an.
struct ServerKonfiguration: Sendable, Equatable {
    static let appGruppe = "group.me.krinke.lector"

    let suite: String

    init(suite: String = ServerKonfiguration.appGruppe) { self.suite = suite }

    private static let adresseSchluessel = "server.adresse"
    private static let modusSchluessel = "server.authModus"

    private var defaults: UserDefaults { UserDefaults(suiteName: suite) ?? .standard }

    /// Die zuletzt bestätigte Basisadresse, ohne Schrägstrich am Ende.
    var adresse: URL? {
        defaults.string(forKey: Self.adresseSchluessel).flatMap { URL(string: $0) }
    }

    var authModus: AuthModus? {
        defaults.string(forKey: Self.modusSchluessel).flatMap { AuthModus(rawValue: $0) }
    }

    /// Nur für bestätigte Adressen aufrufen (nach `ServerPruefung`).
    func speichern(adresse: URL, authModus: AuthModus) {
        defaults.set(adresse.absoluteString, forKey: Self.adresseSchluessel)
        defaults.set(authModus.rawValue, forKey: Self.modusSchluessel)
    }

    func authModusSetzen(_ modus: AuthModus) {
        defaults.set(modus.rawValue, forKey: Self.modusSchluessel)
    }

    func zuruecksetzen() {
        defaults.removeObject(forKey: Self.adresseSchluessel)
        defaults.removeObject(forKey: Self.modusSchluessel)
    }
}
