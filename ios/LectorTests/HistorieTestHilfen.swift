import Foundation
import Synchronization
@testable import Lector

/// Gemeinsame Bausteine der Tests für Historie, Detail und Ereignisstrom.
enum Hilfen {
    static func dokument(
        _ id: Int, status: String = "done", name: String? = nil, seiten: Int? = 1, verarbeitet: Int = 0,
        angelegt: String = "2026-09-29T12:30:00Z", versuche: Int = 0, fehler: String? = nil
    ) -> String {
        let seitenText = seiten.map(String.init) ?? "null"
        let fehlerText = fehler.map { "\"\($0)\"" } ?? "null"
        return """
        {"id": \(id), "original_filename": "\(name ?? "Beleg-\(id).pdf")", "status": "\(status)", "doc_type": "pdf",
         "total_pages": \(seitenText), "processed_pages": \(verarbeitet), "attempt_count": \(versuche),
         "next_retry_at": null, "error_message": \(fehlerText), "page_limit_approved": false,
         "created_at": "\(angelegt)", "started_at": null, "finished_at": null}
        """
    }

    static let nullZaehler = #"{"pending": 0, "processing": 0, "blocked": 0, "done": 0, "skipped_erechnung": 0, "failed": 0}"#

    static func liste(_ dokumente: [String], zaehler: String = nullZaehler, limit: Int = 50, offset: Int = 0) -> AttrappenAntwort {
        .json(#"{"documents": [\#(dokumente.joined(separator: ","))], "counts": \#(zaehler), "limit": \#(limit), "offset": \#(offset)}"#)
    }

    static func zaehler(pending: Int = 0, processing: Int = 0, blocked: Int = 0, done: Int = 0, erechnung: Int = 0, failed: Int = 0) -> String {
        #"{"pending": \#(pending), "processing": \#(processing), "blocked": \#(blocked), "done": \#(done), "skipped_erechnung": \#(erechnung), "failed": \#(failed)}"#
    }

    static func detail(_ dokument: String, ereignisse: [String] = [], seitenGrenze: Int = 100, versuche: Int = 3) -> AttrappenAntwort {
        .json(#"{"document": \#(dokument), "events": [\#(ereignisse.joined(separator: ","))], "page_limit": \#(seitenGrenze), "retry_max": \#(versuche)}"#)
    }

    static func ereignis(_ id: Int, _ art: String, _ zeit: String, _ text: String? = nil) -> String {
        let t = text.map { "\"\($0)\"" } ?? "null"
        return #"{"id": \#(id), "timestamp": "\#(zeit)", "event_type": "\#(art)", "message": \#(t)}"#
    }

    /// Client gegen eine Attrappe; Schlüssel `k1`.
    static func client(_ antworter: @escaping TransportAttrappe.Antworter) -> (APIClient, TransportAttrappe) {
        let transport = TransportAttrappe(antworter)
        let konfiguration = testKonfiguration()
        let sitzung = AuthSession(konfiguration: konfiguration, transport: transport, tokenStore: SpeicherTokenStore("k1"))
        return (APIClient(konfiguration: konfiguration, transport: transport, sitzung: sitzung), transport)
    }

    /// Wartet (höchstens `sekunden`), bis die Bedingung gilt.
    @MainActor
    static func warten(_ sekunden: Double = 5, bis bedingung: @MainActor () async -> Bool) async -> Bool {
        let ende = Date.now.addingTimeInterval(sekunden)
        while Date.now < ende {
            if await bedingung() { return true }
            try? await Task.sleep(for: .milliseconds(10))
        }
        return await bedingung()
    }
}

/// Eine Verbindung des simulierten Ereignisstroms.
struct StromVerbindung: Sendable {
    enum Ende: Sendable { case sauber, fehler, offen }
    var status = 200
    /// Datenpakete; ein Paket darf eine Zeile mittendrin abbrechen.
    var pakete: [String] = []
    var ende: Ende = .offen
}

/// Simulierter Byte-Strom: liefert die Verbindungen der Reihe nach, danach bleibt jede offen.
final class StromQuelleAttrappe: EreignisQuelle, Sendable {
    private struct Zustand {
        var oeffnungen = 0
        var anfragen: [URLRequest] = []
        var abgebaut = 0
    }

    private let verbindungen: [StromVerbindung]
    private let zustand = Mutex(Zustand())

    init(_ verbindungen: [StromVerbindung]) { self.verbindungen = verbindungen }

    var oeffnungen: Int { zustand.withLock { $0.oeffnungen } }
    /// Wie viele Ströme der Verbraucher bereits geschlossen hat.
    var abgebaut: Int { zustand.withLock { $0.abgebaut } }
    var anfragen: [URLRequest] { zustand.withLock { $0.anfragen } }

    func oeffnen(_ request: URLRequest) async throws -> (HTTPURLResponse, AsyncThrowingStream<UInt8, any Error>) {
        let nummer = zustand.withLock { z -> Int in
            z.anfragen.append(request)
            z.oeffnungen += 1
            return z.oeffnungen - 1
        }
        let verbindung = nummer < verbindungen.count ? verbindungen[nummer] : StromVerbindung()
        let http = HTTPURLResponse(url: request.url!, statusCode: verbindung.status, httpVersion: "HTTP/1.1", headerFields: nil)!
        let strom = AsyncThrowingStream<UInt8, any Error> { fortsetzung in
            for paket in verbindung.pakete { for byte in paket.utf8 { fortsetzung.yield(byte) } }
            switch verbindung.ende {
            case .sauber: fortsetzung.finish()
            case .fehler: fortsetzung.finish(throwing: URLError(.networkConnectionLost))
            case .offen: break
            }
            fortsetzung.onTermination = { [self] _ in zustand.withLock { $0.abgebaut += 1 } }
        }
        return (http, strom)
    }
}

/// Merkt sich die angeforderten Wartezeiten und wartet nicht wirklich.
final class PausenProtokoll: Sendable {
    private let werte = Mutex<[Duration]>([])
    var dauern: [Duration] { werte.withLock { $0 } }
    var pause: @Sendable (Duration) async throws -> Void {
        { [self] dauer in
            werte.withLock { $0.append(dauer) }
            try await Task.sleep(for: .milliseconds(1))
        }
    }
}
