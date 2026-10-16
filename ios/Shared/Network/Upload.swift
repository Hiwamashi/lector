import Foundation

/// Der Multipart-Rumpf für `POST /api/v1/upload` (Feld `files`), als Datei im temporären Ordner
/// geschrieben und in Blöcken kopiert, damit auch große PDFs nicht ganz in den Speicher kommen.
enum MultipartRumpf {
    static let feldname = "files"
    private static let blockgroesse = 1 << 20

    /// Schreibt Kopf, Dateiinhalt und Abschluss nach `ziel`. Die Ursache bleibt unterscheidbar:
    /// Quelle nicht lesbar → `dateiNichtLesbar`, Rumpf nicht anleg- oder schreibbar → `rumpfNichtSchreibbar`.
    static func schreiben(datei: UploadDatei, grenze: String, nach ziel: URL) throws {
        let eingabe: FileHandle
        do { eingabe = try FileHandle(forReadingFrom: datei.url) } catch { throw UploadFehler.dateiNichtLesbar }
        defer { try? eingabe.close() }

        guard FileManager.default.createFile(atPath: ziel.path, contents: nil) else {
            throw UploadFehler.rumpfNichtSchreibbar
        }
        let ausgabe: FileHandle
        do { ausgabe = try FileHandle(forWritingTo: ziel) } catch { throw UploadFehler.rumpfNichtSchreibbar }
        defer { try? ausgabe.close() }

        let kopf = "--\(grenze)\r\n"
            + "Content-Disposition: form-data; name=\"\(feldname)\"; filename=\"\(bereinigt(datei.dateiname))\"\r\n"
            + "Content-Type: \(datei.medientyp)\r\n\r\n"
        do {
            try ausgabe.write(contentsOf: Data(kopf.utf8))
            while true {
                let block: Data?
                do { block = try eingabe.read(upToCount: blockgroesse) } catch { throw UploadFehler.dateiNichtLesbar }
                guard let block, !block.isEmpty else { break }
                try ausgabe.write(contentsOf: block)
            }
            try ausgabe.write(contentsOf: Data("\r\n--\(grenze)--\r\n".utf8))
        } catch let fehler as UploadFehler {
            throw fehler
        } catch {
            throw UploadFehler.rumpfNichtSchreibbar
        }
    }

    /// Anführungszeichen und Zeilenumbrüche würden den Kopf aufbrechen.
    static func bereinigt(_ name: String) -> String {
        name.replacingOccurrences(of: "\"", with: "%22")
            .replacingOccurrences(of: "\r", with: "")
            .replacingOccurrences(of: "\n", with: "")
    }
}

extension APIClient {
    /// Lädt eine Datei als eigene Anfrage hoch und liefert das Ergebnis des Dienstes für sie.
    /// Eine abgelehnte Datei (`accepted == false`) ist **kein** Fehler, sondern ein Ergebnis mit
    /// `reason`. Netzfehler werfen `APIFehler.keinNetz`, 401 `APIFehler.nichtAngemeldet`.
    /// Es wird nichts zwischengespeichert; die temporäre Rumpfdatei (in `rumpfOrdner`) wird in jedem
    /// Fall gelöscht. Fehlt die Quelldatei, wirft es `dateiNichtLesbar`, lässt sich der Rumpf nicht
    /// schreiben (z. B. Speicher voll), `rumpfNichtSchreibbar`.
    func hochladen(
        _ datei: UploadDatei, fortschritt: (@Sendable (Double) -> Void)? = nil,
        rumpfOrdner: URL = FileManager.default.temporaryDirectory
    ) async throws -> UploadErgebnisDTO {
        let grenze = "Lector-" + UUID().uuidString
        let rumpf = rumpfOrdner
            .appendingPathComponent("upload-\(UUID().uuidString).multipart")
        defer { try? FileManager.default.removeItem(at: rumpf) }
        try MultipartRumpf.schreiben(datei: datei, grenze: grenze, nach: rumpf)

        var request = try await authentifizierteAnfrage("POST", "/api/v1/upload", zeitlimit: 300)
        request.setValue("multipart/form-data; boundary=\(grenze)", forHTTPHeaderField: "Content-Type")

        let daten: Data, antwort: HTTPURLResponse
        do {
            (daten, antwort) = try await transport.hochladen(request, ausDatei: rumpf, fortschritt: fortschritt)
        } catch is CancellationError {
            throw CancellationError()
        } catch {
            throw APIFehler.keinNetz
        }
        let inhalt = try await pruefen(antwort, daten, gesendet: request)
        guard let ergebnis = try? JSONKodierung.decoder().decode(UploadAntwortDTO.self, from: inhalt),
              let eintrag = ergebnis.results.first else { throw APIFehler.ungueltigeAntwort }
        return eintrag
    }
}

enum UploadFehler: Error, Equatable {
    /// Die vorbereitete Quelldatei ließ sich nicht öffnen oder lesen (z. B. gelöscht).
    case dateiNichtLesbar
    /// Der Multipart-Rumpf ließ sich nicht anlegen oder schreiben (z. B. Gerätespeicher voll);
    /// die Quelldatei liegt dabei noch vor, ein erneutes Senden bleibt sinnvoll.
    case rumpfNichtSchreibbar
}

extension UploadErgebnisDTO {
    /// Deutscher Klartext für `reason` einer abgelehnten Datei.
    var ablehnungstext: String {
        switch reason {
        case "unsupported_format": "Dateiformat wird nicht unterstützt"
        case "unusable_name": "Dateiname nicht verwendbar"
        case "store_failed": "Der Dienst konnte die Datei nicht speichern"
        default: "Vom Dienst abgelehnt"
        }
    }
}
