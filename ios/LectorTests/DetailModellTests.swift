import Foundation
import Testing
@testable import Lector

@MainActor
@Suite("Detail: Verlauf, Freigeben, Verwerfen, 409")
struct DetailModellTests {
    private func modell(
        _ dokument: String, gemeldet: ReferenzListe? = nil, _ antworter: @escaping TransportAttrappe.Antworter
    ) -> (DetailModell, TransportAttrappe) {
        let (client, transport) = Hilfen.client(antworter)
        let start = try! JSONKodierung.decoder().decode(DokumentDTO.self, from: Data(dokument.utf8))
        let liste = gemeldet
        return (DetailModell(dokument: start, client: client, aktualisiert: { neu in liste?.werte.append(neu) }), transport)
    }

    @MainActor
    final class ReferenzListe { var werte: [DokumentDTO] = [] }

    @Test("Der Verlauf kommt in zeitlicher Reihenfolge, Seiten- und Versuchsgrenze aus der Antwort")
    func verlauf() async {
        let blockiert = Hilfen.dokument(3, status: "blocked", seiten: 120)
        let (m, _) = modell(blockiert) { _ in
            Hilfen.detail(blockiert, ereignisse: [
                Hilfen.ereignis(2, "blocked", "2026-09-29T12:31:00Z", "Angehalten"),
                Hilfen.ereignis(1, "detected", "2026-09-29T12:30:00Z", "Erkannt"),
            ], seitenGrenze: 100)
        }
        await m.laden()
        #expect(m.ereignisse.map(\.eventType) == ["detected", "blocked"])
        #expect(m.seitenGrenze == 100)
        #expect(m.versuchsGrenze == 3)
        #expect(m.istAngehalten)
        #expect(m.dokument.totalPages == 120)
        #expect(m.geladen)
    }

    @Test("Freigeben sendet POST …/release und übernimmt den neuen Stand")
    func freigeben() async throws {
        let blockiert = Hilfen.dokument(3, status: "blocked", seiten: 120)
        let gemeldet = ReferenzListe()
        let (m, transport) = modell(blockiert, gemeldet: gemeldet) { anfrage in
            if anfrage.httpMethod == "POST" { return .json(#"{"document": \#(Hilfen.dokument(3, status: "pending", seiten: 120))}"#) }
            return Hilfen.detail(Hilfen.dokument(3, status: "pending", seiten: 120))
        }
        await m.entscheiden(.freigeben)
        let post = try #require(await transport.anfragen.first { $0.httpMethod == "POST" })
        #expect(post.url?.path == "/api/v1/documents/3/release")
        #expect(m.dokument.zustand == .pending)
        #expect(!m.istAngehalten)
        #expect(m.hinweis == nil)
        #expect(gemeldet.werte.last?.zustand == .pending)
    }

    @Test("Verwerfen sendet POST …/discard")
    func verwerfen() async throws {
        let blockiert = Hilfen.dokument(3, status: "blocked", seiten: 120)
        let (m, transport) = modell(blockiert) { anfrage in
            let neu = Hilfen.dokument(3, status: "failed", seiten: 120, fehler: "Verworfen: …")
            return anfrage.httpMethod == "POST" ? .json(#"{"document": \#(neu)}"#) : Hilfen.detail(neu)
        }
        await m.entscheiden(.verwerfen)
        let post = try #require(await transport.anfragen.first { $0.httpMethod == "POST" })
        #expect(post.url?.path == "/api/v1/documents/3/discard")
        #expect(m.dokument.zustand == .failed)
    }

    @Test("409: Hinweis „nicht mehr angehalten“ und der Stand wird nachgeladen")
    func konflikt() async {
        let blockiert = Hilfen.dokument(3, status: "blocked", seiten: 120)
        let gemeldet = ReferenzListe()
        let (m, transport) = modell(blockiert, gemeldet: gemeldet) { anfrage in
            anfrage.httpMethod == "POST"
                ? .fehler(409, "not_blocked", "Nicht angehalten.")
                : Hilfen.detail(Hilfen.dokument(3, status: "done", seiten: 120))
        }
        await m.entscheiden(.verwerfen)
        #expect(m.hinweis?.contains("nicht mehr angehalten") == true)
        #expect(m.fehler == nil)
        #expect(m.dokument.zustand == .done)
        #expect(await transport.anfragen.map(\.httpMethod) == ["POST", "GET"])
        #expect(gemeldet.werte.last?.zustand == .done)
    }

    @Test("Anderer Fehler beim Entscheiden: Meldung, kein Hinweis zum 409")
    func fehler() async {
        let blockiert = Hilfen.dokument(3, status: "blocked", seiten: 120)
        let (m, _) = modell(blockiert) { _ in .fehler(500, "discard_failed", "Das Original konnte nicht verschoben werden.") }
        await m.entscheiden(.verwerfen)
        #expect(m.fehler == "Das Original konnte nicht verschoben werden.")
        #expect(m.hinweis == nil)
        #expect(m.istAngehalten)
    }
}
