# Oberflächentexte, Anzeigenamen & Begriffe (UI)

**Modul:** `app/main.py` (Label-Tabellen, Jinja-Filter), `app/templates/**`,
`app/pipeline.py` (Verlaufsmeldungen bei Fehlern)

Rohwerte aus der Datenbank (Enum-Werte, Quellkennungen, Zahlen) erscheinen **nie** direkt in
der Oberfläche. Sie laufen über Anzeigenamen-Tabellen und Jinja-Filter. Unbekannte Werte fallen
auf den Rohwert zurück, statt leer zu erscheinen — ein neuer Enum-Wert bleibt also sichtbar,
bis er einen Namen bekommt.

## Jinja-Filter

| Filter | Quelle | Beispiel |
|---|---|---|
| `doc_type_label` | `DOC_TYPE_LABELS` | `erechnung_xml` → „E-Rechnung (XML)“, `image` → „Bild“ |
| `event_label` | `EVENT_LABELS` (Dokument- **und** Rechnungsereignisse) | `moved_to_consume` → „An Paperless übergeben“ |
| `payment_source_label` | `PAYMENT_SOURCE_LABELS` | `einvoice` → „Aus der E-Rechnung“ |
| `fmt_amount(currency)` | — | `1240.5, "EUR"` → „1.240,50 EUR“ |
| `fmt_amount_input` | — | `1240.5` → „1240,50“ (Eingabefeld) |

**Fallstrick Betrag im Eingabefeld:** `fmt_amount_input` setzt bewusst **keinen**
Tausenderpunkt. `_parse_amount()` ersetzt Komma durch Punkt und würde „1.240,50“ als
„1.240.50“ lesen und scheitern. Anzeige mit Tausenderpunkt, Eingabe ohne.

Die CSS-Klasse im Verlauf (`event-type--failed` usw.) hängt weiter am **Rohwert**, nur der
sichtbare Text ist übersetzt.

## Begriffe (Glossar)

- **Fehlgeschlagen** — Endzustand `failed` (Dokument) bzw. SevDesk `failed`. Nicht „Fehler“:
  das las sich wie ein Zähler.
- **Alle Dokumente / Alle Rechnungen** — Rücksprung aus Detailansichten; entspricht der
  Navigation. Nicht „Übersicht“ oder „Dashboard“.
- **Ergebnis-PDF** — `output_path`. **Herkunft der Zahldaten** — `source`.
- **Nach Paperless zurückgeschrieben** — `written_back_at` (vorher „Rückschrieb“).

## Zustände mit eigener Formulierung

- **Leerzustand der Listen:** unterscheidet „noch nichts da“ von „Filter trifft nichts“. Die
  Routen reichen dazu `filtered` (aus den **wirksamen** Filtern, ein verworfener Wert wie
  `?status=bogus` zählt nicht) an `history_rows.html` und `invoice_rows.html` (Seite **und**
  Fragment-Endpunkt, sonst kippt der Text beim Live-Abgleich). `recipient_rows.html` liest
  `filters` direkt.
- **Fehlgeschlagenes Dokument:** `failed` hat mehrere Ursachen, die Box unterscheidet sie
  (`detail_body.html`, Kontext `retry_max` aus beiden Detail-Routen):
  - **Versuche ausgeschöpft** (`attempt_count >= RETRY_MAX`, Pipeline oder Recovery): Anzahl
    der Versuche, Original im Fehlerordner, Wiederholungsweg (erneut einwerfen/hochladen).
  - **Verworfen** (Ereignis `discarded` im Verlauf): nur die Verwerfen-Meldung, kein
    Wiederholungsangebot — es war eine bewusste Entscheidung.
  - **Sonst** (z. B. Original fehlt bei der Freigabe): „Verarbeitung fehlgeschlagen.“ ohne
    Aussage über den Fehlerordner.
  Die technische Meldung folgt jeweils als „Grund:“.
- **Rechnung mit Exportfehler:** `error_message` stammt ausschließlich aus dem SevDesk-Export.
  Überschrift je nach Lage: Export deaktiviert → Schalter nennen; `uncertain` → erst in SevDesk
  nachsehen (ein zweiter Export könnte doppeln); sonst → „Daten prüfen und erneut exportieren“.
- **Deaktivierter SevDesk-Export:** Grund steht sichtbar neben der Schaltfläche, nicht nur im
  `title`-Tooltip.
- **Upload:** Einzahl/Mehrzahl („1 Datei“ / „2 Dateien“); abgewiesene Formate nennen die
  unterstützten Endungen; Speicherfehler nennen den Wiederholungsweg.

## Verlaufsmeldungen aus der Pipeline

`_handle_failure()` in `app/pipeline.py` und die Neustart-Recovery in `app/recovery.py`
schreiben Zeiten in **Ortszeit** im Anzeigeformat
(„Nächster Versuch am 29.09.2026 um 14:30“), nicht mehr ISO/UTC — alle anderen Zeiten der UI
sind Ortszeit. Maßgeblich ist die Zeitzone des Containers (`TZ`).

## Barrierefreiheit

Suchfelder, Auswahllisten, das Anzahl-Feld des KI-Laufs und die Empfänger-Auswahl je Zeile
tragen `aria-label` — Platzhalter sind keine Beschriftung. „Details“-Links nennen im
`aria-label` das Dokument, damit sie außerhalb des Kontexts verständlich sind.
