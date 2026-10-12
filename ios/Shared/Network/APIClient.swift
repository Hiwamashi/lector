import Foundation

/// Der Weg ins Netz, austauschbar: Produktion über `URLSession`, Tests über eine Attrappe.
/// Liefert jede HTTP-Antwort zurück (auch 4xx/5xx) und wirft nur bei Transportfehlern.
protocol Transport: Sendable {
    func senden(_ request: URLRequest) async throws -> (Data, HTTPURLResponse)
    /// Sendet den Rumpf aus einer Datei, ohne ihn ganz in den Speicher zu laden (Upload).
    /// `fortschritt` meldet den Anteil 0…1 der gesendeten Bytes.
    func hochladen(
        _ request: URLRequest, ausDatei datei: URL, fortschritt: (@Sendable (Double) -> Void)?
    ) async throws -> (Data, HTTPURLResponse)
}

extension Transport {
    /// Vorgabe für Attrappen: liest die Datei als Rumpf und nutzt `senden`. Nur die Produktion
    /// (`URLSessionTransport`) streamt.
    func hochladen(
        _ request: URLRequest, ausDatei datei: URL, fortschritt: (@Sendable (Double) -> Void)?
    ) async throws -> (Data, HTTPURLResponse) {
        var mitRumpf = request
        mitRumpf.httpBody = try Data(contentsOf: datei)
        let ergebnis = try await senden(mitRumpf)
        fortschritt?(1)
        return ergebnis
    }
}

struct URLSessionTransport: Transport {
    private let session: URLSession

    init() {
        let konfiguration = URLSessionConfiguration.default
        // Keine Cookies und kein Cache: Die Anmeldung läuft ausschließlich über den Bearer-Header.
        konfiguration.httpCookieStorage = nil
        konfiguration.requestCachePolicy = .reloadIgnoringLocalCacheData
        // Ohne Netz sofort scheitern, statt zu warten: Es gibt keine Warteschlange, die später nachholt.
        konfiguration.waitsForConnectivity = false
        session = URLSession(configuration: konfiguration)
    }

    func senden(_ request: URLRequest) async throws -> (Data, HTTPURLResponse) {
        let (daten, antwort) = try await session.data(for: request)
        guard let http = antwort as? HTTPURLResponse else { throw URLError(.badServerResponse) }
        return (daten, http)
    }

    func hochladen(
        _ request: URLRequest, ausDatei datei: URL, fortschritt: (@Sendable (Double) -> Void)?
    ) async throws -> (Data, HTTPURLResponse) {
        let verfolger = FortschrittsVerfolger(fortschritt)
        let (daten, antwort) = try await session.upload(for: request, fromFile: datei, delegate: verfolger)
        guard let http = antwort as? HTTPURLResponse else { throw URLError(.badServerResponse) }
        return (daten, http)
    }
}

/// Meldet den Sendefortschritt eines Uploads. Das Delegate gehört nur zu dieser einen Aufgabe.
private final class FortschrittsVerfolger: NSObject, URLSessionTaskDelegate {
    private let fortschritt: (@Sendable (Double) -> Void)?

    init(_ fortschritt: (@Sendable (Double) -> Void)?) { self.fortschritt = fortschritt }

    func urlSession(
        _ session: URLSession, task: URLSessionTask, didSendBodyData bytesSent: Int64,
        totalBytesSent: Int64, totalBytesExpectedToSend: Int64
    ) {
        guard let fortschritt, totalBytesExpectedToSend > 0 else { return }
        fortschritt(min(1, Double(totalBytesSent) / Double(totalBytesExpectedToSend)))
    }
}

/// `error.code` des einheitlichen Fehlerformats (D4, D5). Unbekannte Codes werden `.unbekannt`.
enum FehlerCode: String, Sendable, Equatable {
    case nichtAngemeldet = "not_authenticated"
    case nichtGefunden = "not_found"
    case nichtAngehalten = "not_blocked"
    case verwerfenFehlgeschlagen = "discard_failed"
    case keineDateien = "no_files"
    case ungueltigeAnfrage = "invalid_request"
    case ungueltigeAnmeldedaten = "invalid_credentials"
    case mfaErforderlich = "mfa_required"
    case paperlessNichtErreichbar = "paperless_unavailable"
    case gebremst = "throttled"
    case unbekannt

    init(rohwert: String?) {
        self = rohwert.flatMap(FehlerCode.init(rawValue:)) ?? .unbekannt
    }
}

enum APIFehler: Error, Equatable {
    /// Der Dienst hat mit einem Fehlerstatus geantwortet. `meldung` ist der deutsche Klartext
    /// aus `error.message`, sofern vorhanden.
    case server(status: Int, code: FehlerCode, meldung: String?)
    /// Kein Netz oder Dienst nicht erreichbar. Kein Grund, den Schlüssel zu verwerfen.
    case keinNetz
    /// 401: Der Dienst kennt die Sitzung nicht (mehr). Der Schlüssel ist dann bereits verworfen.
    case nichtAngemeldet
    /// Es ist noch keine Serveradresse eingerichtet.
    case keineServeradresse
    /// Antwort war kein passendes JSON.
    case ungueltigeAntwort
}

/// Baut Anfragen für `AuthSession`, `ServerPruefung` und `APIClient` gleich, damit alle dieselbe
/// Adresslogik nutzen.
enum Anfrage {
    static func bauen(
        basis: URL, methode: String, pfad: String, query: [URLQueryItem] = [],
        rumpf: (any Encodable & Sendable)? = nil, bearer: String? = nil, zeitlimit: TimeInterval = 30
    ) throws -> URLRequest {
        var text = basis.absoluteString
        while text.hasSuffix("/") { text.removeLast() }
        guard var komponenten = URLComponents(string: text + pfad) else { throw APIFehler.ungueltigeAntwort }
        if !query.isEmpty { komponenten.queryItems = query }
        guard let url = komponenten.url else { throw APIFehler.ungueltigeAntwort }

        var request = URLRequest(url: url, timeoutInterval: zeitlimit)
        request.httpMethod = methode
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if let rumpf {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONKodierung.encoder().encode(rumpf)
        }
        if let bearer { request.setValue("Bearer \(bearer)", forHTTPHeaderField: "Authorization") }
        return request
    }

    /// Wie `Transport.senden`, aber Transportfehler werden zu `APIFehler.keinNetz`.
    static func uebertragen(_ request: URLRequest, ueber transport: any Transport) async throws -> (Data, HTTPURLResponse) {
        do {
            return try await transport.senden(request)
        } catch is CancellationError {
            throw CancellationError()
        } catch {
            throw APIFehler.keinNetz
        }
    }

    /// Der Fehler zu einer Antwort mit Fehlerstatus; liest `{"error": {"code", "message"}}`.
    static func fehler(status: Int, daten: Data) -> APIFehler {
        struct Rumpf: Decodable {
            struct Inhalt: Decodable { let code: String?; let message: String? }
            let error: Inhalt
        }
        let rumpf = try? JSONDecoder().decode(Rumpf.self, from: daten)
        return .server(status: status, code: FehlerCode(rohwert: rumpf?.error.code), meldung: rumpf?.error.message)
    }
}

/// Dünner HTTP-Client der App für die angemeldete Schnittstelle: Adresse aus der Einrichtung,
/// JSON, zentraler `Authorization`-Header. Ein 401 verwirft den Schlüssel und setzt den Zustand
/// auf „Anmeldung nötig“; Netz- und 5xx-Fehler lassen ihn unangetastet. Kein Refresh-Ablauf (D2).
struct APIClient: Sendable {
    let konfiguration: ServerKonfiguration
    let transport: any Transport
    let sitzung: AuthSession

    init(konfiguration: ServerKonfiguration = ServerKonfiguration(), transport: any Transport = URLSessionTransport(), sitzung: AuthSession) {
        self.konfiguration = konfiguration
        self.transport = transport
        self.sitzung = sitzung
    }

    /// Eine fertige Anfrage mit Adresse und Schlüssel — auch für Wege, die nicht über `senden`
    /// laufen (Ereignisstrom, Upload).
    func authentifizierteAnfrage(
        _ methode: String, _ pfad: String, query: [URLQueryItem] = [], rumpf: (any Encodable & Sendable)? = nil,
        zeitlimit: TimeInterval = 30
    ) async throws -> URLRequest {
        guard let basis = konfiguration.adresse else { throw APIFehler.keineServeradresse }
        return try Anfrage.bauen(
            basis: basis, methode: methode, pfad: pfad, query: query, rumpf: rumpf,
            bearer: await sitzung.schluessel(), zeitlimit: zeitlimit)
    }

    /// Antwortrumpf einer erfolgreichen (2xx) Anfrage. Fehlerstatus werfen `APIFehler.server`,
    /// 401 wirft `APIFehler.nichtAngemeldet`.
    func senden(
        _ methode: String, _ pfad: String, query: [URLQueryItem] = [], rumpf: (any Encodable & Sendable)? = nil
    ) async throws -> Data {
        let request = try await authentifizierteAnfrage(methode, pfad, query: query, rumpf: rumpf)
        let (daten, antwort) = try await Anfrage.uebertragen(request, ueber: transport)
        return try await pruefen(antwort, daten, gesendet: request)
    }

    func anfrage<Antwort: Decodable & Sendable>(
        _ methode: String, _ pfad: String, query: [URLQueryItem] = [], rumpf: (any Encodable & Sendable)? = nil
    ) async throws -> Antwort {
        let daten = try await senden(methode, pfad, query: query, rumpf: rumpf)
        do {
            return try JSONKodierung.decoder().decode(Antwort.self, from: daten)
        } catch {
            throw APIFehler.ungueltigeAntwort
        }
    }

    /// Wertet den Status einer Antwort aus; auch für Wege außerhalb von `senden` (Upload, Ereignisstrom).
    func pruefen(_ antwort: HTTPURLResponse, _ daten: Data, gesendet request: URLRequest) async throws -> Data {
        if antwort.statusCode == 401 {
            let gesendet = request.value(forHTTPHeaderField: "Authorization").map { String($0.dropFirst("Bearer ".count)) }
            await sitzung.sitzungAbgelaufen(abgelehnt: gesendet)
            throw APIFehler.nichtAngemeldet
        }
        guard (200..<300).contains(antwort.statusCode) else {
            throw Anfrage.fehler(status: antwort.statusCode, daten: daten)
        }
        return daten
    }
}
