import Foundation
import Testing
@testable import Lector

@Suite("Anzeige: Zeitzone, Begriffe aus ui-texte.md, Fehlertexte")
struct AnzeigeTests {
    @Test("Zeitpunkte erscheinen in der Zeitzone des Geräts, nicht in UTC")
    func zeitzone() throws {
        let datum = try #require(JSONKodierung.datum(aus: "2026-09-29T12:30:00Z"))
        let berlin = try #require(TimeZone(identifier: "Europe/Berlin"))
        let tokio = try #require(TimeZone(identifier: "Asia/Tokyo"))
        let de = Locale(identifier: "de_DE")
        let imSommer = Zeitanzeige.text(datum, zeitzone: berlin, gebiet: de)
        #expect(imSommer.contains("29.09.2026"))
        #expect(imSommer.contains("14:30"))
        #expect(Zeitanzeige.text(datum, zeitzone: tokio, gebiet: de).contains("21:30"))
        #expect(Zeitanzeige.text(nil) == "—")
    }

    @Test("Zustandsbegriffe wie in der Weboberfläche")
    func zustaende() {
        #expect(DokumentZustand.allCases.map(\.bezeichnung)
            == ["Wartet", "In Arbeit", "Angehalten", "Fertig", "E-Rechnung", "Fehlgeschlagen"])
        #expect(Bezeichnung.ereignis("moved_to_consume") == "An Paperless übergeben")
        #expect(Bezeichnung.ereignis("neuer_typ") == "neuer_typ")
        #expect(Bezeichnung.dokumenttyp("erechnung_xml") == "E-Rechnung (XML)")
        #expect(Bezeichnung.dokumenttyp(nil) == "—")
    }

    @Test("Fehlertexte: ohne Netz Klartext, 401 und Abbruch still, Servermeldung durchgereicht")
    func fehlertexte() {
        #expect(HistorieFehler.text(fuer: APIFehler.keinNetz)?.hasPrefix("Keine Verbindung") == true)
        #expect(HistorieFehler.text(fuer: APIFehler.nichtAngemeldet) == nil)
        #expect(HistorieFehler.text(fuer: CancellationError()) == nil)
        #expect(HistorieFehler.text(fuer: APIFehler.server(status: 500, code: .unbekannt, meldung: "Kaputt.")) == "Kaputt.")
        #expect(HistorieFehler.text(fuer: APIFehler.server(status: 500, code: .unbekannt, meldung: nil)) != nil)
    }
}
