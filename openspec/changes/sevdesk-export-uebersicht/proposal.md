# Proposal

## Why

Der Export nach SevDesk ist heute blind: Lector kennt nur die Belege, die es selbst angelegt
hat, und die Rechnungsliste mischt private und geschäftliche Rechnungen. Vor einem Export ist
weder erkennbar, ob eine Rechnung überhaupt zu IT-Consulting gehört, noch ob in SevDesk schon
ein Beleg mit ähnlichen Werten liegt. Doppelte Belege und falsch zugeordnete Ausgaben fallen
erst in SevDesk auf.

## What Changes

- **Neu: Export-Übersicht.** Jede Paperless-Rechnung erscheint mit drei Merkmalen: Kontext
  (IT-Consulting mit Konfidenz und Herkunft der Einschätzung), Lector-Exportstatus und
  SevDesk-Abgleich (sicherer oder ähnlicher Treffer). Filter auf „IT-Consulting ab Schwelle“,
  „nicht exportiert“ und „mögliche Dublette“; Export einzeln und als Mehrfachauswahl.
- **Neu: SevDesk-Belege lesen.** Lector ruft die Belege aus SevDesk ab und hält sie in einem
  lokalen Cache. Die Zuordnung Rechnung ↔ Beleg ist eine eigene Beziehung (sicher über die
  Beleg-ID, ähnlich über Betrag, Datum und Lieferant mit Score). Der Nutzer kann einen
  ähnlichen Treffer bestätigen oder verwerfen; die Entscheidung bleibt über Syncs erhalten.
  Das Modell ist so geschnitten, dass ein späterer beidseitiger Abgleich (SevDesk-Belege ohne
  Paperless-Dokument) nur eine weitere Ansicht ist.
- **Neu: Einstufung „IT-Consulting“.** Die Konfidenz entsteht gestuft: manuell gesetzter
  Empfänger → Historie desselben Korrespondenten → KI-Einschätzung. Die KI-Abfrage der
  Empfänger-Zuordnung liefert dafür zusätzlich eine Wahrscheinlichkeit für IT-Consulting
  (ein Aufruf, beide Antworten).
- **Geändert: Export.** Ein Export setzt das Paperless-Feld „Empfänger“ auf IT-Consulting.
  Steht dort ein anderer Empfänger oder findet die Prüfung einen ähnlichen Beleg, fragt die
  Übersicht vorher nach. Ein gesicherter Betrag (GiroCode-Status `ready`/`edited`) wird als
  Belegsumme mitgegeben.
- **Geändert: Tag-Weg.** Der Paperless-Tag bleibt als Abkürzung, durchläuft aber dieselben
  Prüfungen. Kann er nicht eindeutig exportieren (abweichender Empfänger, mögliche Dublette),
  erhält die Rechnung den neuen Status „zu prüfen“ statt still exportiert zu werden.
- **Geändert: Batch-Lauf der Empfänger-Zuordnung.** Er bearbeitet auch Dokumente erneut, deren
  Cache-Eintrag noch keine IT-Consulting-Einschätzung hat.

Nicht Teil dieses Changes: die Ansicht „SevDesk-Belege ohne Paperless-Dokument“ (Abgleich B),
automatisches Verbuchen in SevDesk, eine eigene Kontext-Option außer IT-Consulting.

## Capabilities

### New Capabilities

- `sevdesk-export`: Wie eine Paperless-Rechnung nach SevDesk gelangt — Übersicht, Auslöser
  (Übersicht und Tag), Prüfungen vor dem Export, Statusmodell inklusive „zu prüfen“,
  Rückschrieb an Paperless einschließlich Empfänger.
- `sevdesk-abgleich`: Abruf und Cache der SevDesk-Belege, Zuordnung zu Rechnungen (sicher/
  ähnlich mit Score) und die vom Nutzer bestätigten oder verworfenen Treffer.
- `geschaeftskontext-einstufung`: Einschätzung, ob eine Rechnung zu IT-Consulting gehört, mit
  Konfidenz und nachvollziehbarer Herkunft (Empfänger, Korrespondenten-Historie, KI).

### Modified Capabilities

_keine_ — die Paperless-Integration hat bisher keine Spec; ihr bestehendes Verhalten, soweit
dieser Change es berührt, wird in den neuen Capabilities festgehalten.

## Impact

- **Code:** `app/sevdesk.py` (Belege lesen, Summe mitgeben), `app/paperless_sync.py` (Abgleich,
  Einstufung, Prüfungen, Empfänger-Rückschrieb, Batch-Auswahl), `app/recipient_llm.py`
  (zusätzliches Tool-Feld), `app/repository.py`, `app/db.py` (neue Tabellen und Spalten,
  Migration), `app/models.py` (Status `review`, neue Dataclasses), `app/main.py` (Routen),
  Templates `invoices.html`, `partials/invoice_rows.html`, `partials/invoice_detail_body.html`.
- **API extern:** zusätzliche Lesezugriffe auf `GET /Voucher` der SevDesk-API; mehr Tokens je
  KI-Aufruf und ein einmaliger Nachlauf über bereits bewertete Dokumente.
- **Konfiguration:** neue ENV-Variablen (Kontext-Option, Schwelle, Abgleichsfenster,
  Abruf-Intervall), dokumentiert in `.env.example` und `feature-documentation/konfiguration.md`.
- **Tests:** `tests/test_sevdesk.py`, `tests/test_invoices_repo.py`, `tests/test_recipients.py`,
  `tests/test_web.py`.
- **Doku:** `feature-documentation/paperless-integration/` (Export, neuer Abgleich, Einstufung),
  `prd/PROGRESS.md`.
- **Keine Änderung** am OCR-Pfad, an der iOS-App und an `/api/`.
