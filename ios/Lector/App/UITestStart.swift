#if DEBUG
import Foundation
import Synchronization
import UIKit

/// Nur in Debug: Startargumente für UI-Tests (und die gehosteten Unit-Tests), damit sie ohne
/// Server, Keychain und App Group laufen. Es gibt keinen Weg, das in Release zu aktivieren.
///
/// - `-UITEST_ATTRAPPE`: Attrappen-Transport (`UITestTransport`), Schlüssel nur im Arbeitsspeicher,
///   eigene `UserDefaults`-Suite (bei jedem Start geleert).
/// - `-UITEST_ADRESSE_GESETZT`: Die Serveradresse `https://lector.test` ist schon bestätigt.
/// - `-UITEST_ANGEMELDET`: Ein Schlüssel liegt im Speicher (nur mit `-UITEST_ADRESSE_GESETZT` sinnvoll).
/// - `-UITEST_AUTH_MODUS <none|paperless>`: Zugangsmodus der Attrappe, Vorgabe `paperless`.
/// - `-UITEST_LIVE`: Der Ereignisstrom der Attrappe meldet nach 5 s einen Zustandswechsel
///   (Vorgang 2 wird fertig) und nach 7 s einen neuen Vorgang (8).
/// - `-UITEST_TESTBILD`: Im Menü „Beleg übergeben“ erscheint „Testbild übergeben“; es umgeht Kamera
///   und Fotoauswahl und übergibt drei erzeugte Bilder.
/// - `-UITEST_UPLOAD_FEHLER`: Der erste Upload scheitert wie ohne Netz, alle weiteren gelingen.
/// - `-UITEST_UPLOAD_ABGELEHNT`: Der Dienst lehnt jede hochgeladene Datei ab (`unsupported_format`).
enum UITestStart {
    static func startart() -> Startart {
        let argumente = ProcessInfo.processInfo.arguments
        var start = Startart()
        if istGehosteterUnitTest { start.gehostetterTest = true; start.serverPruefungStartet = false }
        start.attrappe = argumente.contains("-UITEST_ATTRAPPE")
        if start.attrappe { start.gehostetterTest = false; start.serverPruefungStartet = true }
        start.adresseGesetzt = argumente.contains("-UITEST_ADRESSE_GESETZT")
        start.angemeldet = argumente.contains("-UITEST_ANGEMELDET")
        start.live = argumente.contains("-UITEST_LIVE")
        start.uploadFehler = argumente.contains("-UITEST_UPLOAD_FEHLER")
        start.uploadAbgelehnt = argumente.contains("-UITEST_UPLOAD_ABGELEHNT")
        if let text = UserDefaults.standard.string(forKey: "UITEST_AUTH_MODUS"), let modus = AuthModus(rawValue: text) {
            start.authModus = modus
        }
        return start
    }

    static func suite(fuer start: Startart) -> String {
        start.attrappe ? "me.krinke.lector.uitest" : "me.krinke.lector.unittest.host"
    }

    /// Leert die Suite und legt die verlangte Ausgangslage an.
    static func vorbereiten(_ start: Startart, konfiguration: ServerKonfiguration) {
        guard start.attrappe || start.gehostetterTest else { return }
        UserDefaults.standard.removePersistentDomain(forName: konfiguration.suite)
        if start.adresseGesetzt, let adresse = URL(string: "https://lector.test") {
            konfiguration.speichern(adresse: adresse, authModus: start.authModus)
        }
    }

    static var testbildEingespeist: Bool { ProcessInfo.processInfo.arguments.contains("-UITEST_TESTBILD") }

    /// Drei Seiten für den Testweg ohne Kamera und Mediathek.
    static func testbilder() -> [UIImage] {
        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        return [(600, 800), (800, 600), (500, 500)].map { breite, hoehe in
            UIGraphicsImageRenderer(size: CGSize(width: breite, height: hoehe), format: format).image { kontext in
                UIColor.systemTeal.setFill()
                kontext.fill(CGRect(x: 0, y: 0, width: breite, height: hoehe))
            }
        }
    }

    private static var istGehosteterUnitTest: Bool {
        ProcessInfo.processInfo.environment["XCTestConfigurationFilePath"] != nil
    }
}

/// Der Lector-Dienst als Attrappe für die UI-Tests: antwortet nach Pfad und Eingabe, ohne Netz.
///
/// - Host `kein-lector.test`: `/api/info` antwortet 404 (kein Lector).
/// - Anmeldung: Passwort `falsch` → 401 `invalid_credentials`, `paperless-weg` → 503
///   `paperless_unavailable`, `zu-viele` → 429 `throttled`. Nutzername `mfa-nutzer` verlangt den
///   Code `123456`, sonst 401 `mfa_required` bzw. `invalid_credentials`. Alles andere gelingt.
/// - `POST /api/v1/logout` → 204. Unbekannte Pfade → 404 `not_found`.
///
/// - `GET /api/v1/documents`, `GET /api/v1/documents/{id}`, `POST …/release|discard`: die
///   Vorgänge aus `UITestDienst` (Filter, Seiten, Zähler wie der echte Dienst).
///
/// - `POST /api/v1/upload`: Ergebnis je Datei (`UITestDienst.uploadAntwort`), Fehler und Ablehnung
///   über die Startargumente `-UITEST_UPLOAD_FEHLER` und `-UITEST_UPLOAD_ABGELEHNT`.
struct UITestTransport: Transport {
    let authModus: AuthModus
    let dienst: UITestDienst

    init(authModus: AuthModus, dienst: UITestDienst = UITestDienst(live: false)) {
        self.authModus = authModus
        self.dienst = dienst
    }

    func hochladen(
        _ request: URLRequest, ausDatei datei: URL, fortschritt: (@Sendable (Double) -> Void)?
    ) async throws -> (Data, HTTPURLResponse) {
        if dienst.uploadScheitert() { throw URLError(.notConnectedToInternet) }
        fortschritt?(1)
        return antwort(200, dienst.uploadAntwort(), request)
    }

    func senden(_ request: URLRequest) async throws -> (Data, HTTPURLResponse) {
        let pfad = request.url?.path ?? ""
        let host = request.url?.host ?? ""
        switch (request.httpMethod ?? "GET", pfad) {
        case ("GET", "/api/info"):
            if host == "kein-lector.test" { return antwort(404, #"{"detail":"Not Found"}"#, request) }
            return antwort(200, #"{"service":"lector","api_version":1,"auth_mode":"\#(authModus.rawValue)"}"#, request)
        case ("POST", "/api/v1/login"):
            return login(request)
        case ("POST", "/api/v1/logout"):
            return antwort(204, "", request)
        case ("GET", "/api/v1/documents"):
            return antwort(200, dienst.liste(query: request.url?.query ?? ""), request)
        default:
            if let treffer = dokumentPfad(pfad, methode: request.httpMethod ?? "GET") { return treffer(request) }
            return fehler(404, "not_found", "Nicht gefunden.", request)
        }
    }

    /// `/api/v1/documents/{id}` (GET) und `/api/v1/documents/{id}/release|discard` (POST).
    private func dokumentPfad(_ pfad: String, methode: String) -> ((URLRequest) -> (Data, HTTPURLResponse))? {
        let teile = pfad.split(separator: "/").map(String.init)
        guard teile.count >= 4, teile[0] == "api", teile[1] == "v1", teile[2] == "documents", let id = Int(teile[3]) else { return nil }
        switch (methode, teile.count, teile.count > 4 ? teile[4] : "") {
        case ("GET", 4, _):
            return { request in
                guard let text = dienst.detail(id) else { return fehler(404, "not_found", "Vorgang nicht gefunden.", request) }
                return antwort(200, text, request)
            }
        case ("POST", 5, "release"), ("POST", 5, "discard"):
            let freigabe = teile[4] == "release"
            return { request in
                switch dienst.entscheiden(id, freigeben: freigabe) {
                case .ok(let text): return antwort(200, text, request)
                case .nichtGefunden: return fehler(404, "not_found", "Vorgang nicht gefunden.", request)
                case .nichtAngehalten: return fehler(409, "not_blocked", "Der Vorgang ist nicht angehalten.", request)
                }
            }
        default:
            return nil
        }
    }

    private func login(_ request: URLRequest) -> (Data, HTTPURLResponse) {
        let rumpf = (request.httpBody.flatMap { try? JSONSerialization.jsonObject(with: $0) }) as? [String: Any] ?? [:]
        let nutzer = rumpf["username"] as? String ?? ""
        let passwort = rumpf["password"] as? String ?? ""
        let code = rumpf["code"] as? String

        switch passwort {
        case "falsch": return fehler(401, "invalid_credentials", "Anmeldung fehlgeschlagen.", request)
        case "paperless-weg": return fehler(503, "paperless_unavailable", "Paperless ist nicht erreichbar.", request)
        case "zu-viele": return fehler(429, "throttled", "Zu viele Versuche.", request)
        default: break
        }
        if nutzer == "mfa-nutzer" {
            if code == nil { return fehler(401, "mfa_required", "MFA-Code erforderlich.", request) }
            if code != "123456" { return fehler(401, "invalid_credentials", "Anmeldung fehlgeschlagen.", request) }
        }
        return antwort(200, #"{"token":"attrappen-schluessel","username":"\#(nutzer)"}"#, request)
    }

    private func fehler(_ status: Int, _ code: String, _ meldung: String, _ request: URLRequest) -> (Data, HTTPURLResponse) {
        antwort(status, #"{"error":{"code":"\#(code)","message":"\#(meldung)"}}"#, request)
    }

    private func antwort(_ status: Int, _ text: String, _ request: URLRequest) -> (Data, HTTPURLResponse) {
        let http = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: "HTTP/1.1", headerFields: nil)!
        return (Data(text.utf8), http)
    }
}

/// Die Vorgänge der Attrappe: ein kleiner fester Bestand, der Entscheidungen und (mit `live`)
/// Meldungen des Ereignisstroms mitmacht. Liefert JSON im Format des Schnittstellenvertrags v1.
///
/// Bestand (neueste zuerst): 7 angehalten (wird bei jeder Entscheidung „schon anderweitig
/// entschieden“, also 409), 6 wartet, 5 E-Rechnung, 4 fehlgeschlagen, 3 angehalten (120 Seiten),
/// 2 in Arbeit (2 von 5 Seiten), 1 fertig (vor 10 Tagen). Seitenobergrenze 100, Versuche höchstens 3.
final class UITestDienst: @unchecked Sendable {
    private struct Vorgang {
        var id: Int
        var name: String
        var status: String
        var typ: String
        var seiten: Int?
        var verarbeitet = 0
        var versuche = 0
        var fehler: String?
        var freigegeben = false
        var angelegt: Date
        var ereignisse: [(typ: String, text: String?)] = []
    }

    private let zustand: Mutex<[Vorgang]>
    let live: Bool
    private let uploadFehler: Bool
    private let uploadAbgelehnt: Bool
    private let uploads = Mutex(0)

    init(live: Bool, uploadFehler: Bool = false, uploadAbgelehnt: Bool = false, jetzt: Date = .now) {
        self.live = live
        self.uploadFehler = uploadFehler
        self.uploadAbgelehnt = uploadAbgelehnt
        func vor(_ stunden: Double) -> Date { jetzt.addingTimeInterval(-stunden * 3600) }
        zustand = Mutex([
            Vorgang(id: 7, name: "Schon-entschieden.pdf", status: "blocked", typ: "pdf", seiten: 40, angelegt: vor(1),
                    ereignisse: [("detected", "Erkannt"), ("blocked", "Angehalten: 40 Seiten.")]),
            Vorgang(id: 6, name: "Wartet-Beleg.pdf", status: "pending", typ: "pdf", seiten: 1, angelegt: vor(2),
                    ereignisse: [("detected", "Erkannt")]),
            Vorgang(id: 5, name: "XRechnung-Stadtwerke.xml", status: "skipped_erechnung", typ: "erechnung_xml", angelegt: vor(3),
                    ereignisse: [("detected", "Erkannt"), ("skipped_erechnung", "E-Rechnung durchgereicht")]),
            Vorgang(id: 4, name: "Fehler-Beleg.pdf", status: "failed", typ: "image", seiten: 1, versuche: 3,
                    fehler: "Texterkennung nicht erreichbar", angelegt: vor(4),
                    ereignisse: [("detected", "Erkannt"), ("retry_scheduled", "Neuer Versuch geplant"), ("failed", "Texterkennung nicht erreichbar")]),
            Vorgang(id: 3, name: "Grosser-Vertrag.pdf", status: "blocked", typ: "pdf", seiten: 120, angelegt: vor(5),
                    ereignisse: [("detected", "Erkannt"), ("blocked", "Angehalten: 120 Seiten.")]),
            Vorgang(id: 2, name: "Kassenbon-Edeka.pdf", status: "processing", typ: "pdf", seiten: 5, verarbeitet: 2, versuche: 1,
                    angelegt: vor(6), ereignisse: [("detected", "Erkannt"), ("ocr_chunk", "Seiten 1 bis 2")]),
            Vorgang(id: 1, name: "Rechnung-Telekom.pdf", status: "done", typ: "pdf", seiten: 2, verarbeitet: 2, versuche: 1,
                    angelegt: vor(240), ereignisse: [("detected", "Erkannt"), ("built_pdf", "PDF erstellt"), ("done", "Fertig")]),
        ])
    }

    enum Entscheidungsergebnis { case ok(String), nichtGefunden, nichtAngehalten }

    // MARK: Antworten

    func liste(query: String) -> String {
        let parameter = Dictionary(
            URLComponents(string: "?" + query)?.queryItems?.map { ($0.name, $0.value ?? "") } ?? [],
            uniquingKeysWith: { _, neu in neu })
        let limit = max(1, min(Int(parameter["limit"] ?? "") ?? 200, 200))
        let offset = max(0, Int(parameter["offset"] ?? "") ?? 0)
        let status = parameter["status"].flatMap { $0.isEmpty ? nil : $0 }
        let suche = parameter["q"].flatMap { $0.isEmpty ? nil : $0 }
        let stunden: Double? = switch parameter["period"] { case "24h": 24; case "7d": 7 * 24; case "30d": 30 * 24; default: nil }

        let alle = zustand.withLock { $0 }
        let gefiltert = alle.filter { vorgang in
            if let status, vorgang.status != status { return false }
            if let suche, !vorgang.name.localizedCaseInsensitiveContains(suche) { return false }
            if let stunden, vorgang.angelegt < Date.now.addingTimeInterval(-stunden * 3600) { return false }
            return true
        }.sorted { $0.id > $1.id }
        let seite = gefiltert.dropFirst(offset).prefix(limit)
        var zaehler: [String: Int] = [:]
        for z in DokumentZustand.allCases { zaehler[z.rawValue] = alle.filter { $0.status == z.rawValue }.count }
        return Self.json(["documents": seite.map(Self.dokument), "counts": zaehler, "limit": limit, "offset": offset])
    }

    func detail(_ id: Int) -> String? {
        guard let vorgang = zustand.withLock({ $0.first { $0.id == id } }) else { return nil }
        return Self.json(["document": Self.dokument(vorgang), "events": Self.ereignisse(vorgang), "page_limit": 100, "retry_max": 3])
    }

    func entscheiden(_ id: Int, freigeben: Bool) -> Entscheidungsergebnis {
        zustand.withLock { alle in
            guard let index = alle.firstIndex(where: { $0.id == id }) else { return .nichtGefunden }
            guard alle[index].status == "blocked" else { return .nichtAngehalten }
            if id == 7 {
                // Wurde inzwischen in der Weboberfläche freigegeben.
                alle[index].status = "done"
                alle[index].ereignisse.append(("released", "Freigegeben"))
                return .nichtAngehalten
            }
            if freigeben {
                alle[index].status = "pending"
                alle[index].freigegeben = true
                alle[index].ereignisse.append(("released", "Freigegeben"))
            } else {
                alle[index].status = "failed"
                alle[index].fehler = "Verworfen: Das Dokument wurde nicht verarbeitet (Seitenobergrenze)."
                alle[index].ereignisse.append(("discarded", "Verworfen"))
            }
            return .ok(Self.json(["document": Self.dokument(alle[index])]))
        }
    }

    // MARK: Upload

    /// Zählt den Versuch; mit `-UITEST_UPLOAD_FEHLER` scheitert nur der erste.
    func uploadScheitert() -> Bool {
        let nummer = uploads.withLock { $0 += 1; return $0 }
        return uploadFehler && nummer == 1
    }

    func uploadAntwort() -> String {
        uploadAbgelehnt
            ? #"{"results":[{"filename":"Scan.pdf","accepted":false,"reason":"unsupported_format","stored_as":null}]}"#
            : #"{"results":[{"filename":"Scan.pdf","accepted":true,"reason":null,"stored_as":"Scan.pdf"}]}"#
    }

    // MARK: Live

    /// Zustandswechsel für den Strom (nur mit `live`): Vorgang 2 wird fertig.
    func fertigStellen() {
        zustand.withLock { alle in
            guard let index = alle.firstIndex(where: { $0.id == 2 }) else { return }
            alle[index].status = "done"
            alle[index].verarbeitet = alle[index].seiten ?? 0
            alle[index].ereignisse.append(("done", "Fertig"))
        }
    }

    /// Neuer Vorgang für den Strom (nur mit `live`).
    func neuAnlegen() {
        zustand.withLock { alle in
            guard !alle.contains(where: { $0.id == 8 }) else { return }
            alle.append(Vorgang(id: 8, name: "Neu-eingegangen.pdf", status: "pending", typ: "pdf", seiten: 1, angelegt: .now,
                                ereignisse: [("detected", "Erkannt")]))
        }
    }

    // MARK: JSON

    private static func zeit(_ datum: Date?) -> Any {
        guard let datum else { return NSNull() }
        return ISO8601DateFormatter().string(from: datum)
    }

    private static func dokument(_ v: Vorgang) -> [String: Any] {
        [
            "id": v.id, "original_filename": v.name, "status": v.status, "doc_type": v.typ,
            "total_pages": v.seiten.map { $0 as Any } ?? NSNull(), "processed_pages": v.verarbeitet,
            "attempt_count": v.versuche, "next_retry_at": NSNull(), "error_message": v.fehler.map { $0 as Any } ?? NSNull(),
            "page_limit_approved": v.freigegeben, "created_at": zeit(v.angelegt),
            "started_at": NSNull(), "finished_at": v.status == "done" || v.status == "failed" ? zeit(v.angelegt) : NSNull(),
        ]
    }

    private static func ereignisse(_ v: Vorgang) -> [[String: Any]] {
        v.ereignisse.enumerated().map { index, e in
            ["id": v.id * 100 + index, "timestamp": zeit(v.angelegt.addingTimeInterval(Double(index) * 60)),
             "event_type": e.typ, "message": e.text.map { $0 as Any } ?? NSNull()]
        }
    }

    private static func json(_ objekt: [String: Any]) -> String {
        let daten = (try? JSONSerialization.data(withJSONObject: objekt)) ?? Data()
        return String(decoding: daten, as: UTF8.self)
    }
}

/// Ereignisstrom der Attrappe: bleibt offen, sendet ein Kommentar und mit `live` zwei Meldungen.
struct UITestEreignisQuelle: EreignisQuelle {
    let dienst: UITestDienst

    func oeffnen(_ request: URLRequest) async throws -> (HTTPURLResponse, AsyncThrowingStream<UInt8, any Error>) {
        let http = HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: "HTTP/1.1", headerFields: nil)!
        let dienst = dienst
        let strom = AsyncThrowingStream<UInt8, any Error> { fortsetzung in
            let aufgabe = Task {
                func senden(_ text: String) { for byte in text.utf8 { fortsetzung.yield(byte) } }
                senden(": connected\n\n")
                if dienst.live {
                    try? await Task.sleep(for: .seconds(5))
                    dienst.fertigStellen()
                    senden("data: doc:2\n\n")
                    try? await Task.sleep(for: .seconds(2))
                    dienst.neuAnlegen()
                    senden("data: doc:8\n\n")
                }
                while !Task.isCancelled {
                    try? await Task.sleep(for: .seconds(15))
                    senden(": keepalive\n\n")
                }
                fortsetzung.finish()
            }
            fortsetzung.onTermination = { _ in aufgabe.cancel() }
        }
        return (http, strom)
    }
}
#endif
