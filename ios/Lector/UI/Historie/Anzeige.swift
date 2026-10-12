import Foundation

/// Zeitraumfilter der Historie; die Rohwerte sind der Parameter `period` der Schnittstelle.
enum Zeitraum: String, CaseIterable, Sendable {
    case alle = ""
    case tag = "24h"
    case woche = "7d"
    case monat = "30d"

    /// Texte wie im Zeitraum-Filter der Weboberfläche.
    var bezeichnung: String {
        switch self {
        case .alle: "Gesamter Zeitraum"
        case .tag: "Letzte 24 h"
        case .woche: "Letzte 7 Tage"
        case .monat: "Letzte 30 Tage"
        }
    }

    /// Frühester Anlagezeitpunkt, der noch zum Zeitraum gehört; `nil` = unbegrenzt.
    func grenze(jetzt: Date = .now) -> Date? {
        switch self {
        case .alle: nil
        case .tag: jetzt.addingTimeInterval(-24 * 3600)
        case .woche: jetzt.addingTimeInterval(-7 * 24 * 3600)
        case .monat: jetzt.addingTimeInterval(-30 * 24 * 3600)
        }
    }
}

/// Anzeigenamen aus `feature-documentation/ui-texte.md` (Tabellen `DOC_TYPE_LABELS`,
/// `EVENT_LABELS`). Unbekannte Werte bleiben als Rohwert sichtbar, statt leer zu erscheinen.
enum Bezeichnung {
    static func dokumenttyp(_ rohwert: String?) -> String {
        guard let rohwert else { return "—" }
        return switch rohwert {
        case "pdf": "PDF"
        case "tiff": "TIFF"
        case "image": "Bild"
        case "erechnung_xml": "E-Rechnung (XML)"
        case "erechnung_pdf": "E-Rechnung (PDF)"
        default: rohwert
        }
    }

    static func ereignis(_ rohwert: String) -> String {
        switch rohwert {
        case "detected": "Erkannt"
        case "preprocessing": "Vorverarbeitung"
        case "ocr_chunk": "Texterkennung"
        case "built_pdf": "PDF erstellt"
        case "moved_to_consume": "An Paperless übergeben"
        case "retry_scheduled": "Neuer Versuch geplant"
        case "skipped_erechnung": "E-Rechnung durchgereicht"
        case "blocked": "Angehalten"
        case "released": "Freigegeben"
        case "discarded": "Verworfen"
        case "failed": "Fehlgeschlagen"
        case "done": "Fertig"
        default: rohwert
        }
    }

    /// Zustandsname; unbekannte Rohwerte erscheinen unverändert.
    static func zustand(_ dokument: DokumentDTO) -> String {
        dokument.zustand?.bezeichnung ?? dokument.status
    }
}

/// Zeitpunkte in der Zeitzone des Geräts (Spec „Historie“). Zeitzone und Gebietsschema sind
/// für Tests austauschbar.
enum Zeitanzeige {
    static func text(_ datum: Date?, zeitzone: TimeZone = .current, gebiet: Locale = .current) -> String {
        guard let datum else { return "—" }
        return datum.formatted(
            Date.FormatStyle(locale: gebiet, timeZone: zeitzone)
                .day(.twoDigits).month(.twoDigits).year(.defaultDigits)
                .hour(.twoDigits(amPM: .omitted)).minute(.twoDigits))
    }
}

/// Meldungstexte für Fehler der Historie. `nil` = nichts anzeigen (Abbruch durch die Person oder
/// abgelaufene Sitzung, die die Wurzelansicht zur Anmeldung führt).
enum HistorieFehler {
    static func text(fuer fehler: any Error) -> String? {
        switch fehler {
        case is CancellationError: nil
        case APIFehler.nichtAngemeldet: nil
        case APIFehler.keinNetz: "Keine Verbindung zum Lector-Dienst. Bitte prüfe das Netz und versuche es erneut."
        case APIFehler.keineServeradresse: "Es ist noch keine Serveradresse eingerichtet."
        case APIFehler.ungueltigeAntwort: "Der Dienst hat unerwartet geantwortet. Bitte versuche es später erneut."
        case APIFehler.server(_, _, let meldung?) where !meldung.isEmpty: meldung
        default: "Der Dienst meldet einen Fehler. Bitte versuche es später erneut."
        }
    }
}
