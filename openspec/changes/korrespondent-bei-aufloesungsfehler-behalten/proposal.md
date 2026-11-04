# Proposal

## Why

Der Rechnungs-Sync löst den Korrespondentennamen je Dokument über eine je Lauf geladene Karte auf,
bei fehlender ID über einen Einzelabruf. Scheitert auch dieser (Netzfehler, Zeitüberschreitung,
HTTP-Fehler), liefert `_correspondent_name` `None`. Der Sync hält das für „kein Korrespondent“ und
leert den gespeicherten Namen der Rechnung. Seit dem Change `paperless-sync-ohne-stillstand` fällt das
zusätzlich als Änderung auf: Die Rechnung gilt als geändert, bekommt ein `synced`-Ereignis und ein
Live-Signal. Beim nächsten erfolgreichen Lauf wird der Name wieder gesetzt, mit einem weiteren
Ereignis. Ein vorübergehender Fehler in Paperless verfälscht so Daten und Verlauf.

## What Changes

- Der Sync unterscheidet „Dokument hat keinen Korrespondenten“ von „Name nicht auflösbar“.
- Ist der Name nicht auflösbar, bleibt der gespeicherte Korrespondent der Rechnung unverändert. Eine
  neue Rechnung wird ohne Korrespondent angelegt; der nächste Lauf trägt ihn nach.
- Der Korrespondent allein löst in diesem Fall weder eine Änderung noch ein `synced`-Ereignis noch ein
  Live-Signal aus. Andere geänderte Felder werden weiterhin geschrieben.
- Hat das Dokument in Paperless keinen Korrespondenten, wird das Feld wie bisher geleert.
- Der Sync protokolliert einen fehlgeschlagenen Einzelabruf als Warnung mit Korrespondenten-ID und
  Fehlertyp.
- Unverändert: GiroCode-Kreditor aus dem Korrespondenten und die Empfänger-Vorschläge behandeln einen
  nicht auflösbaren Namen weiterhin als „kein Name“.

## Capabilities

### New Capabilities

### Modified Capabilities
- `rechnungs-sync`: neue Anforderung, dass ein nicht auflösbarer Korrespondentenname den gespeicherten
  Wert nicht überschreibt.

## Impact

- `app/paperless_sync.py`: `_correspondent_name` bzw. ein neuer Weg für den Sync, `_upsert_row`,
  Ereignisprüfung in `_sync_invoices`.
- `app/repository.py`: `InvoiceUpsert.correspondent` darf „nicht gesetzt“ sein; Vergleich und Schreiben
  in `_upsert_invoice_locked` überspringen dann das Feld.
- Tests in `tests/test_invoices_repo.py` und `tests/test_voucher_sync.py`.
- Doku `feature-documentation/paperless-integration/sync-und-aktionen.md`, `prd/PROGRESS.md`
  (bekannter Punkt wird erledigt).
- Keine Datenbankmigration, keine neue Konfiguration, keine Änderung an der Oberfläche.
