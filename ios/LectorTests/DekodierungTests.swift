import Foundation
import Testing
@testable import Lector

@Suite("DTOs: Dekodierung nach Schnittstellenvertrag v1")
struct DekodierungTests {
    private func lesen<T: Decodable>(_ typ: T.Type, _ text: String) throws -> T {
        try JSONKodierung.decoder().decode(T.self, from: Data(text.utf8))
    }

    @Test("Selbstauskunft")
    func info() throws {
        let info = try lesen(ServerInfo.self, #"{"service":"lector","api_version":1,"auth_mode":"paperless"}"#)
        #expect(info == ServerInfo(service: "lector", apiVersion: 1, authMode: .paperless))
        #expect(try lesen(ServerInfo.self, #"{"service":"lector","api_version":1,"auth_mode":"none"}"#).authMode == .none)
    }

    @Test("Unbekannter Zugangsmodus ist kein gültiger Lector")
    func unbekannterModus() {
        #expect(throws: DecodingError.self) {
            try lesen(ServerInfo.self, #"{"service":"lector","api_version":1,"auth_mode":"magie"}"#)
        }
    }

    @Test("Anmeldeantwort")
    func login() throws {
        let antwort = try lesen(LoginAntwort.self, #"{"token":"abc.def","username":"anna"}"#)
        #expect(antwort == LoginAntwort(token: "abc.def", username: "anna"))
    }

    @Test("Anmeldeanfrage sendet code immer, ohne MFA als null")
    func loginRumpf() throws {
        let ohne = try JSONSerialization.jsonObject(
            with: JSONEncoder().encode(LoginAnfrage(username: "a", password: "b", code: nil))) as? [String: Any]
        #expect(ohne?.keys.sorted() == ["code", "password", "username"])
        #expect(ohne?["code"] is NSNull)
        let mit = try JSONSerialization.jsonObject(
            with: JSONEncoder().encode(LoginAnfrage(username: "a", password: "b", code: "123456"))) as? [String: Any]
        #expect(mit?["code"] as? String == "123456")
    }

    private let dokument = """
    {"id": 7, "original_filename": "Rechnung.pdf", "status": "processing", "doc_type": "pdf",
     "total_pages": 12, "processed_pages": 5, "attempt_count": 1, "next_retry_at": null,
     "error_message": null, "page_limit_approved": false,
     "created_at": "2026-10-12T08:30:00Z", "started_at": "2026-10-12T08:31:00.250000Z", "finished_at": null}
    """

    @Test("Vorgang: Schlüssel, Zeitpunkte mit Z, mit Mikrosekunden und null")
    func vorgang() throws {
        let d = try lesen(DokumentDTO.self, dokument)
        #expect(d.id == 7)
        #expect(d.originalFilename == "Rechnung.pdf")
        #expect(d.zustand == .processing)
        #expect(d.docType == "pdf")
        #expect(d.totalPages == 12 && d.processedPages == 5)
        #expect(d.pageLimitApproved == false)
        #expect(d.nextRetryAt == nil && d.finishedAt == nil)
        #expect(d.createdAt == Date(timeIntervalSince1970: 1_791_793_800))
        let gestartet = try #require(d.startedAt)
        #expect(abs(gestartet.timeIntervalSince1970 - 1_791_793_860.25) < 0.001)
    }

    @Test("Unbekannter Zustand bleibt als Rohwert lesbar, statt die Liste zu brechen")
    func unbekannterZustand() throws {
        let d = try lesen(DokumentDTO.self, dokument.replacingOccurrences(of: "processing", with: "neuer_zustand"))
        #expect(d.status == "neuer_zustand")
        #expect(d.zustand == nil)
    }

    @Test("Liste mit Zählern, Detail mit Verlauf, Entscheidung und Upload")
    func zusammengesetzte() throws {
        let liste = try lesen(DokumentListeDTO.self, """
        {"documents": [\(dokument)], "counts": {"pending": 0, "processing": 1, "blocked": 0, "done": 4,
         "skipped_erechnung": 2, "failed": 0}, "limit": 200, "offset": 0}
        """)
        #expect(liste.documents.count == 1 && liste.limit == 200 && liste.offset == 0)
        #expect(liste.counts["skipped_erechnung"] == 2)
        #expect(Set(liste.counts.keys) == Set(DokumentZustand.allCases.map(\.rawValue)))

        let detail = try lesen(DokumentDetailDTO.self, """
        {"document": \(dokument), "events": [{"id": 1, "timestamp": "2026-10-12T08:30:01Z",
         "event_type": "detected", "message": null}], "page_limit": 100, "retry_max": 3}
        """)
        #expect(detail.events.first?.eventType == "detected")
        #expect(detail.events.first?.message == nil)
        #expect(detail.pageLimit == 100 && detail.retryMax == 3)

        let entscheidung = try lesen(DokumentAntwortDTO.self, #"{"document": \#(dokument)}"#)
        #expect(entscheidung.document.id == 7)

        let upload = try lesen(UploadAntwortDTO.self, """
        {"results": [{"filename": "a.pdf", "accepted": true, "reason": null, "stored_as": "a.pdf"},
                     {"filename": "b.txt", "accepted": false, "reason": "unsupported_format", "stored_as": null}]}
        """)
        #expect(upload.results[0].storedAs == "a.pdf")
        #expect(upload.results[1].reason == "unsupported_format")
    }

    @Test("Zustandsbezeichnungen wie in der Weboberfläche")
    func bezeichnungen() {
        #expect(DokumentZustand.allCases.map(\.bezeichnung)
                == ["Wartet", "In Arbeit", "Angehalten", "Fertig", "E-Rechnung", "Fehlgeschlagen"])
    }
}
