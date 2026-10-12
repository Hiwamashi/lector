import Foundation
import Synchronization
@testable import Lector

/// Antwort einer Attrappe: Statuscode und Rumpf.
struct AttrappenAntwort: Sendable {
    let status: Int
    let rumpf: Data

    static func json(_ status: Int, _ text: String) -> AttrappenAntwort {
        AttrappenAntwort(status: status, rumpf: Data(text.utf8))
    }

    static func json(_ text: String) -> AttrappenAntwort { json(200, text) }

    static func leer(_ status: Int) -> AttrappenAntwort {
        AttrappenAntwort(status: status, rumpf: Data())
    }

    /// Fehlerformat des Vertrags: `{"error": {"code", "message"}}`.
    static func fehler(_ status: Int, _ code: String, _ meldung: String = "Meldung") -> AttrappenAntwort {
        json(status, #"{"error":{"code":"\#(code)","message":"\#(meldung)"}}"#)
    }
}

/// Austauschbarer Transport für Tests: merkt sich jede Anfrage und lässt eine Closure antworten.
actor TransportAttrappe: Transport {
    typealias Antworter = @Sendable (URLRequest) async throws -> AttrappenAntwort

    private(set) var anfragen: [URLRequest] = []
    private let antworter: Antworter

    init(_ antworter: @escaping Antworter) {
        self.antworter = antworter
    }

    func senden(_ request: URLRequest) async throws -> (Data, HTTPURLResponse) {
        anfragen.append(request)
        let antwort = try await antworter(request)
        let http = HTTPURLResponse(
            url: request.url!, statusCode: antwort.status, httpVersion: "HTTP/1.1", headerFields: nil)!
        return (antwort.rumpf, http)
    }

    func anzahl(pfad: String) -> Int {
        anfragen.filter { $0.url?.path == pfad }.count
    }

    func anfragen(pfad: String) -> [URLRequest] {
        anfragen.filter { $0.url?.path == pfad }
    }
}

/// Jede Anfrage scheitert wie im Flugmodus.
struct TransportOhneNetz: Transport {
    func senden(_ request: URLRequest) async throws -> (Data, HTTPURLResponse) {
        throw URLError(.notConnectedToInternet)
    }
}

extension URLRequest {
    /// Zugangsschlüssel der Anfrage, sonst `nil`.
    var bearer: String? {
        guard let wert = value(forHTTPHeaderField: "Authorization"), wert.hasPrefix("Bearer ") else { return nil }
        return String(wert.dropFirst("Bearer ".count))
    }

    /// JSON-Rumpf als Wörterbuch, für Prüfungen am gesendeten Body.
    var jsonRumpf: [String: Any]? {
        guard let httpBody else { return nil }
        return (try? JSONSerialization.jsonObject(with: httpBody)) as? [String: Any]
    }
}

/// Eine frische, eigene Suite je Test, damit die App Group des Geräts unberührt bleibt.
func testKonfiguration(adresse: String? = "https://lector.example.de", modus: AuthModus = .paperless) -> ServerKonfiguration {
    let konfiguration = ServerKonfiguration(suite: "test.\(UUID().uuidString)")
    if let adresse, let url = URL(string: adresse) { konfiguration.speichern(adresse: url, authModus: modus) }
    return konfiguration
}
