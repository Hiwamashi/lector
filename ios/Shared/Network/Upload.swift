import Foundation

/// Der Multipart-Rumpf für `POST /api/v1/upload` (Feld `files`), als Datei im temporären Ordner
/// geschrieben und in Blöcken kopiert, damit auch große PDFs nicht ganz in den Speicher kommen.
enum MultipartRumpf {
    static let feldname = "files"
    private static let blockgroesse = 1 << 20

    /// Schreibt Kopf, Dateiinhalt und Abschluss nach `ziel`.
    static func schreiben(datei: UploadDatei, grenze: String, nach ziel: URL) throws {
        FileManager.default.createFile(atPath: ziel.path, contents: nil)
        let ausgabe = try FileHandle(forWritingTo: ziel)
        defer { try? ausgabe.close() }
        let eingabe = try FileHandle(forReadingFrom: datei.url)
        defer { try? eingabe.close() }

        let kopf = "--\(grenze)\r\n"
            + "Content-Disposition: form-data; name=\"\(feldname)\"; filename=\"\(bereinigt(datei.dateiname))\"\r\n"
            + "Content-Type: \(datei.medientyp)\r\n\r\n"
        try ausgabe.write(contentsOf: Data(kopf.utf8))
        while let block = try eingabe.read(upToCount: blockgroesse), !block.isEmpty {
            try ausgabe.write(contentsOf: block)
        }
        try ausgabe.write(contentsOf: Data("\r\n--\(grenze)--\r\n".utf8))
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
    /// Es wird nichts zwischengespeichert; die temporäre Rumpfdatei wird in jedem Fall gelöscht.
    func hochladen(
        _ datei: UploadDatei, fortschritt: (@Sendable (Double) -> Void)? = nil
    ) async throws -> UploadErgebnisDTO {
        let grenze = "Lector-" + UUID().uuidString
        let rumpf = FileManager.default.temporaryDirectory
            .appendingPathComponent("upload-\(UUID().uuidString).multipart")
        defer { try? FileManager.default.removeItem(at: rumpf) }
        do {
            try MultipartRumpf.schreiben(datei: datei, grenze: grenze, nach: rumpf)
        } catch {
            throw UploadFehler.dateiNichtLesbar
        }

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
    /// Die vorbereitete Datei ließ sich nicht lesen oder der Rumpf nicht schreiben.
    case dateiNichtLesbar
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
