import Foundation

/// Der Weg zum Ereignisstrom, austauschbar: Produktion über `URLSession.bytes`, Tests über einen
/// simulierten Byte-Strom. Liefert die Antwort und die Bytes des Rumpfes; Fehlerstatus gibt die
/// Quelle unverändert zurück, die Auswertung macht `EreignisStrom`.
protocol EreignisQuelle: Sendable {
    func oeffnen(_ request: URLRequest) async throws -> (HTTPURLResponse, AsyncThrowingStream<UInt8, any Error>)
}

struct URLSessionEreignisQuelle: EreignisQuelle {
    private let session: URLSession

    init() {
        let konfiguration = URLSessionConfiguration.default
        konfiguration.httpCookieStorage = nil
        konfiguration.requestCachePolicy = .reloadIgnoringLocalCacheData
        konfiguration.waitsForConnectivity = false
        // Idle-Zeitlimit: Der Dienst sendet alle 15 s einen Keepalive, ein Strom ohne Zeichen
        // ist also abgerissen und wird neu aufgebaut.
        konfiguration.timeoutIntervalForRequest = 45
        konfiguration.timeoutIntervalForResource = 60 * 60 * 24
        session = URLSession(configuration: konfiguration)
    }

    func oeffnen(_ request: URLRequest) async throws -> (HTTPURLResponse, AsyncThrowingStream<UInt8, any Error>) {
        let (bytes, antwort) = try await session.bytes(for: request)
        guard let http = antwort as? HTTPURLResponse else { throw URLError(.badServerResponse) }
        let strom = AsyncThrowingStream<UInt8, any Error> { fortsetzung in
            let aufgabe = Task {
                do {
                    for try await byte in bytes { fortsetzung.yield(byte) }
                    fortsetzung.finish()
                } catch {
                    fortsetzung.finish(throwing: error)
                }
            }
            fortsetzung.onTermination = { _ in aufgabe.cancel() }
        }
        return (http, strom)
    }
}

/// Was der Strom der Historie meldet.
enum StromMeldung: Equatable, Sendable {
    /// Ein Vorgang hat sich geändert (`data: doc:<id>`).
    case dokument(Int)
    /// Die Verbindung wurde nach einem Abbruch neu aufgebaut: Die Liste muss vollständig neu
    /// geladen werden, weil in der Zwischenzeit Meldungen verloren gegangen sein können.
    case wiederaufgebaut
}

/// Setzt Bytes zu Zeilen zusammen (`\n`, `\r\n` und `\r` trennen) und ordnet sie ein. Arbeitet
/// auf Bytes, damit ein Zeichen oder eine Zeile über mehrere Datenpakete verteilt sein darf.
struct ZeilenLeser {
    enum Zeile: Equatable {
        case kommentar
        case dokument(Int)
        /// Leere Zeile, anderes Präfix (`inv:`, `rec:`, `batch:`) oder anderes Feld.
        case ignoriert
    }

    private var puffer: [UInt8] = []
    private var letztesWarCR = false

    /// Nimmt ein Byte; liefert die Einordnung, wenn damit eine Zeile abgeschlossen wurde.
    mutating func aufnehmen(_ byte: UInt8) -> Zeile? {
        if byte == 0x0A {
            // „\r\n“: Die Zeile wurde schon beim `\r` abgeschlossen.
            if letztesWarCR { letztesWarCR = false; return nil }
            return abschliessen()
        }
        letztesWarCR = (byte == 0x0D)
        if byte == 0x0D { return abschliessen() }
        puffer.append(byte)
        return nil
    }

    private mutating func abschliessen() -> Zeile {
        defer { puffer.removeAll(keepingCapacity: true) }
        return Self.einordnen(String(decoding: puffer, as: UTF8.self))
    }

    static func einordnen(_ zeile: String) -> Zeile {
        if zeile.hasPrefix(":") { return .kommentar }
        guard zeile.hasPrefix("data:") else { return .ignoriert }
        let wert = zeile.dropFirst("data:".count).trimmingCharacters(in: .whitespaces)
        guard wert.hasPrefix("doc:"), let id = Int(wert.dropFirst("doc:".count)) else { return .ignoriert }
        return .dokument(id)
    }
}

/// Liest `/events` (Server-Sent Events) und meldet geänderte Vorgänge (D11). Bricht die Verbindung
/// ab oder endet sie, wird sie mit wachsender Wartezeit neu aufgebaut und danach
/// `.wiederaufgebaut` gemeldet. Ein 401 beendet den Strom (die Sitzung ist dann abgelaufen).
/// Das Beenden der Verbraucher-Aufgabe (Wechsel in den Hintergrund) schließt die Verbindung.
struct EreignisStrom: Sendable {
    /// Wartezeiten vor dem 1., 2., … Wiederaufbau; die letzte gilt für alle weiteren.
    static let standardWartezeiten: [Duration] = [.seconds(1), .seconds(2), .seconds(5), .seconds(10), .seconds(30)]

    let client: APIClient
    let quelle: any EreignisQuelle
    let wartezeiten: [Duration]
    let pause: @Sendable (Duration) async throws -> Void

    init(
        client: APIClient, quelle: any EreignisQuelle = URLSessionEreignisQuelle(),
        wartezeiten: [Duration] = EreignisStrom.standardWartezeiten,
        pause: @escaping @Sendable (Duration) async throws -> Void = { try await Task.sleep(for: $0) }
    ) {
        self.client = client
        self.quelle = quelle
        self.wartezeiten = wartezeiten
        self.pause = pause
    }

    func meldungen() -> AsyncStream<StromMeldung> {
        AsyncStream { fortsetzung in
            let aufgabe = Task { await schleife(fortsetzung) }
            fortsetzung.onTermination = { _ in aufgabe.cancel() }
        }
    }

    private func schleife(_ fortsetzung: AsyncStream<StromMeldung>.Continuation) async {
        var fehlversuche = 0
        var erstesMal = true
        while !Task.isCancelled {
            do {
                var request = try await client.authentifizierteAnfrage("GET", "/events", zeitlimit: 45)
                request.setValue("text/event-stream", forHTTPHeaderField: "Accept")
                let (antwort, bytes) = try await quelle.oeffnen(request)
                try await pruefen(antwort, bytes, request)
                if !erstesMal { fortsetzung.yield(.wiederaufgebaut) }
                erstesMal = false
                try await lesen(bytes, fortsetzung) { fehlversuche = 0 }
            } catch is CancellationError {
                break
            } catch APIFehler.nichtAngemeldet, APIFehler.keineServeradresse {
                break
            } catch {
                // Netz weg, Server-Fehler oder Strom gerissen: weiter mit Wiederaufbau.
            }
            if Task.isCancelled { break }
            erstesMal = false
            let warte = wartezeiten.isEmpty ? Duration.seconds(1) : wartezeiten[min(fehlversuche, wartezeiten.count - 1)]
            fehlversuche += 1
            do { try await pause(warte) } catch { break }
        }
        fortsetzung.finish()
    }

    /// Fehlerstatus: Rumpf (klein) lesen und wie bei jeder Anfrage auswerten, damit 401 den Schlüssel verwirft.
    private func pruefen(_ antwort: HTTPURLResponse, _ bytes: AsyncThrowingStream<UInt8, any Error>, _ request: URLRequest) async throws {
        guard !(200..<300).contains(antwort.statusCode) else { return }
        var rumpf = Data()
        for try await byte in bytes {
            rumpf.append(byte)
            if rumpf.count >= 16_384 { break }
        }
        _ = try await client.pruefen(antwort, rumpf, gesendet: request)
        throw APIFehler.server(status: antwort.statusCode, code: .unbekannt, meldung: nil)
    }

    private func lesen(
        _ bytes: AsyncThrowingStream<UInt8, any Error>, _ fortsetzung: AsyncStream<StromMeldung>.Continuation,
        erstesZeichen: () -> Void
    ) async throws {
        var leser = ZeilenLeser()
        var gesehen = false
        for try await byte in bytes {
            if !gesehen { gesehen = true; erstesZeichen() }
            switch leser.aufnehmen(byte) {
            case .dokument(let id): fortsetzung.yield(.dokument(id))
            case .kommentar, .ignoriert, nil: break
            }
        }
    }
}
