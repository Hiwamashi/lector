import Foundation

// Abbild des „Schnittstellenvertrags v1“ (openspec/changes/ios-app/design.md, Anhang).
// Schlüssel kommen als snake_case und werden von `JSONKodierung` in camelCase gelesen.

/// Zugangsmodus des Dienstes (`AUTH_MODE`).
enum AuthModus: String, Codable, Sendable, Equatable {
    case none
    case paperless
}

/// `GET /api/info`
struct ServerInfo: Decodable, Equatable, Sendable {
    let service: String
    let apiVersion: Int
    let authMode: AuthModus
}

/// `POST /api/v1/login`, Rumpf. `code` wird immer gesendet, ohne MFA als `null`.
struct LoginAnfrage: Encodable, Equatable, Sendable {
    let username: String
    let password: String
    let code: String?

    enum CodingKeys: String, CodingKey { case username, password, code }

    func encode(to encoder: any Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(username, forKey: .username)
        try container.encode(password, forKey: .password)
        try container.encode(code, forKey: .code)
    }
}

/// `POST /api/v1/login`, Antwort 200
struct LoginAntwort: Decodable, Equatable, Sendable {
    let token: String
    let username: String
}

/// Zustand eines Vorgangs. Die Rohwerte entsprechen `Document.status`.
enum DokumentZustand: String, CaseIterable, Sendable {
    case pending
    case processing
    case blocked
    case done
    case skippedErechnung = "skipped_erechnung"
    case failed

    /// Anzeigename wie in der Weboberfläche (`STATUS_LABELS`, `feature-documentation/ui-texte.md`).
    var bezeichnung: String {
        switch self {
        case .pending: "Wartet"
        case .processing: "In Arbeit"
        case .blocked: "Angehalten"
        case .done: "Fertig"
        case .skippedErechnung: "E-Rechnung"
        case .failed: "Fehlgeschlagen"
        }
    }
}

/// `Document` des Vertrags.
struct DokumentDTO: Decodable, Equatable, Sendable, Identifiable {
    let id: Int
    let originalFilename: String
    /// Rohwert; `zustand` liefert die typisierte Form (unbekannte Werte bleiben hier sichtbar).
    let status: String
    let docType: String?
    let totalPages: Int?
    let processedPages: Int
    let attemptCount: Int
    let nextRetryAt: Date?
    let errorMessage: String?
    let pageLimitApproved: Bool
    let createdAt: Date?
    let startedAt: Date?
    let finishedAt: Date?

    var zustand: DokumentZustand? { DokumentZustand(rawValue: status) }
}

/// `Event` des Vertrags.
struct EreignisDTO: Decodable, Equatable, Sendable, Identifiable {
    let id: Int
    let timestamp: Date
    let eventType: String
    let message: String?
}

/// `GET /api/v1/documents`
struct DokumentListeDTO: Decodable, Equatable, Sendable {
    let documents: [DokumentDTO]
    /// Je Zustand (Rohwert) die Anzahl über den ganzen Bestand, ungefiltert.
    let counts: [String: Int]
    let limit: Int
    let offset: Int
}

/// `GET /api/v1/documents/{id}`
struct DokumentDetailDTO: Decodable, Equatable, Sendable {
    let document: DokumentDTO
    let events: [EreignisDTO]
    let pageLimit: Int
    let retryMax: Int
}

/// `POST /api/v1/documents/{id}/release` und `/discard`
struct DokumentAntwortDTO: Decodable, Equatable, Sendable {
    let document: DokumentDTO
}

/// `POST /api/v1/upload`, Antwort 200
struct UploadAntwortDTO: Decodable, Equatable, Sendable {
    let results: [UploadErgebnisDTO]
}

struct UploadErgebnisDTO: Decodable, Equatable, Sendable {
    let filename: String
    let accepted: Bool
    /// `unsupported_format`, `unusable_name` oder `store_failed`; sonst `nil`.
    let reason: String?
    let storedAs: String?
}
