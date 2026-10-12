import Foundation

/// Die Eingabe der Serveradresse (D10): normalisieren und `http` auf das lokale Netz beschränken.
enum ServerAdresse {
    enum Fehler: Error, Equatable {
        case leer
        case ungueltig
        /// `http://` außerhalb des lokalen Netzes.
        case unverschluesselt
    }

    /// Fehlt das Schema, wird `https://` ergänzt; Schrägstriche am Ende, Anfrageteil und Anker
    /// entfallen. Ein Pfad bleibt erhalten (Dienst hinter einem Unterpfad).
    static func normalisieren(_ eingabe: String) throws -> URL {
        let text = eingabe.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { throw Fehler.leer }
        let mitSchema = text.contains("://") ? text : "https://" + text
        guard var komponenten = URLComponents(string: mitSchema),
              let schema = komponenten.scheme?.lowercased(), schema == "http" || schema == "https",
              let host = komponenten.host, !host.isEmpty else { throw Fehler.ungueltig }
        komponenten.scheme = schema
        komponenten.query = nil
        komponenten.fragment = nil
        komponenten.user = nil
        komponenten.password = nil
        while komponenten.path.hasSuffix("/") { komponenten.path.removeLast() }
        if schema == "http", !istLokalesNetz(host: host) { throw Fehler.unverschluesselt }
        guard let url = komponenten.url else { throw Fehler.ungueltig }
        return url
    }

    /// Lokales Netz: `localhost`, Hosts auf `.local`, Namen ohne Punkt, private, Loopback- und
    /// Link-Local-IPv4 sowie die entsprechenden IPv6-Bereiche. Öffentliche Hosts und Adressen nicht.
    static func istLokalesNetz(host: String) -> Bool {
        var name = host.lowercased()
        if name.hasPrefix("["), name.hasSuffix("]") { name = String(name.dropFirst().dropLast()) }
        if name == "localhost" || name.hasSuffix(".local") { return true }
        if name.contains(":") { return istLokalesIPv6(name) }
        if let teile = ipv4(name) { return istPrivatesIPv4(teile) }
        return !name.contains(".")
    }

    private static func ipv4(_ text: String) -> [Int]? {
        let teile = text.split(separator: ".", omittingEmptySubsequences: false)
        guard teile.count == 4 else { return nil }
        let zahlen = teile.compactMap { Int($0) }
        guard zahlen.count == 4, zahlen.allSatisfy({ (0...255).contains($0) }) else { return nil }
        return zahlen
    }

    private static func istPrivatesIPv4(_ z: [Int]) -> Bool {
        switch (z[0], z[1]) {
        case (10, _), (127, _), (192, 168), (169, 254): true
        case (172, 16...31): true
        default: false
        }
    }

    private static func istLokalesIPv6(_ name: String) -> Bool {
        name == "::1" || name.hasPrefix("fc") || name.hasPrefix("fd") || name.hasPrefix("fe80")
    }
}

/// Ergebnis der Prüfung einer Adresse beim Dienst.
enum ServerPruefung {
    enum Fehler: Error, Equatable {
        /// Der Dienst antwortet nicht (Netzfehler, Zeitüberschreitung).
        case nichtErreichbar
        /// Es antwortet etwas, aber kein Lector (anderer Status, anderes JSON, anderer `service`).
        case keinLector
        /// Ein Lector, aber mit einer anderen Version der Schnittstelle.
        case andereVersion(gemeldet: Int)
    }

    static let unterstuetzteVersion = 1

    /// `GET <adresse>/api/info`. Liefert die Selbstauskunft nur für einen Lector mit unterstützter Version.
    static func pruefen(adresse: URL, transport: any Transport) async throws -> ServerInfo {
        let request = try Anfrage.bauen(basis: adresse, methode: "GET", pfad: "/api/info", zeitlimit: 10)
        let daten: Data, antwort: HTTPURLResponse
        do {
            (daten, antwort) = try await Anfrage.uebertragen(request, ueber: transport)
        } catch APIFehler.keinNetz {
            throw Fehler.nichtErreichbar
        }
        guard antwort.statusCode == 200,
              let info = try? JSONKodierung.decoder().decode(ServerInfo.self, from: daten),
              info.service == "lector" else { throw Fehler.keinLector }
        guard info.apiVersion == unterstuetzteVersion else { throw Fehler.andereVersion(gemeldet: info.apiVersion) }
        return info
    }
}
