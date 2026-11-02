# Tasks

Testbefehle: `uv run pytest`, `uv run ruff check .`. Aufgaben mit **(manuell)** führt der
Anwender aus; der Agent bereitet Werte und Befehle vor und hakt erst nach Rückmeldung ab. Der
SevDesk-Token erscheint nie im Repository oder im Chat.

## 1. SevDesk-API klären

- [x] 1.1 **(manuell, mit Agent)** Gegen die echte SevDesk-API prüfen: (a) welche Felder `GET /Voucher` liefert (ID, `voucherDate`, `supplierName` bzw. eingebetteter Kontakt, `sumGross`, `currency`, `description`, `status`) und wie geblättert wird (`limit`/`offset`, Maximum je Seite); (b) ob `saveVoucher` mit einer Position (`sumGross`, Steuersatz 0) ohne `accountingType` angenommen wird. Prüfen: Befunde mit anonymisierten Beispielantworten in `design.md` (Entscheidungen 5 und 9) nachgetragen; Abweichungen von der Annahme dort als Änderung vermerkt.

## 2. Datenmodell und Migration

- [x] 2.1 `app/db.py`: Spalten `recipient_label`, `paperless_voucher_ref`, `review_reason` an `paperless_invoices`, `it_probability` an `document_recipients`; Tabellen `sevdesk_vouchers`, `invoice_voucher_matches`, `sevdesk_sync_state` (Design 5) samt Indizes; Nachzug über `_migrate()`. Prüfen: Test legt eine Datenbank im alten Schema an, ruft `init_db()` auf und findet alle neuen Spalten und Tabellen.
- [x] 2.2 `app/models.py`: `SevdeskStatus.REVIEW`/`DISMISSED`, neue Event-Typen (Prüffall, verworfen, Treffer bestätigt/verworfen, Belegabruf), Dataclasses für Beleg, Treffer und Einstufung; `RecipientSuggestion`/`RecipientCache` um `it_probability`. Prüfen: `uv run pytest tests/test_invoices_repo.py` grün.
- [x] 2.3 `app/repository.py`: Lesen/Schreiben der neuen Spalten, Beleg-Abzug ersetzen in einer Transaktion (Upsert + Löschen nicht gelieferter IDs), Treffer lesen/schreiben (similar neu, confirmed/rejected bewahren), Sync-Zustand, Korrespondenten-Historie per `GROUP BY`, Abfrage „Belege ohne Rechnung“. Prüfen: neue Tests in `tests/test_invoices_repo.py` decken Ersetzen, Bewahren der Entscheidungen und die Abfrage „Belege ohne Rechnung“ ab.

## 3. Konfiguration

- [x] 3.1 `app/config.py`: `SEVDESK_CONTEXT_LABEL` (Standard `IT-Consulting`), `SEVDESK_CONTEXT_MIN_CONFIDENCE` (0,75), `SEVDESK_MATCH_WINDOW_DAYS` (14), `SEVDESK_MATCH_MIN_SCORE` (0,4), `SEVDESK_VOUCHER_SYNC_MINUTES` (60), ggf. Wert aus 1.1(b); Startvalidierung für Wertebereiche (Schwellen 0..1, Fenster/Intervall > 0) mit gemeinsamer Fehlermeldung. Prüfen: Tests für Standardwerte und je einen ungültigen Wert; `.env.example` ergänzt.

## 4. SevDesk-Client

- [x] 4.1 `SevdeskClient.list_vouchers()` mit Blättern und gekapseltem Feld-Mapping nach Befund 1.1. Prüfen: `tests/test_sevdesk.py` mit `httpx.MockTransport` über zwei Seiten, inklusive fehlendem Lieferantennamen.
- [x] 4.2 `save_voucher_from_temp(..., amount=None, account_datev_id=None)`: nur wenn Betrag UND Konto-ID vorliegen, eine Position in `voucherPosSave` (`accountDatev`, `taxRate` 0, `net` false, `sumGross`), sonst wie bisher `None`; neue ENV `SEVDESK_ACCOUNT_DATEV_ID` (optional) in `app/config.py` und `.env.example` (Design 9, Befund 1.1(b)). Prüfen: Tests prüfen beide Payload-Varianten.

## 5. Abgleich

- [x] 5.1 Matching-Funktion (Design 6): sichere Treffer über `sevdesk_voucher_id`/`paperless_voucher_ref`, ähnliche über Betrag, Währung, Fenster, Score mit Namensnormalisierung; vergebene und verworfene Belege ausschließen. Prüfen: Unit-Tests für alle Szenarien der Requirements „sicherer Treffer“ und „ähnlicher Treffer“ aus `specs/sevdesk-abgleich/spec.md`, einschließlich AWS-Beispiel und 1-Cent-Abweichung.
- [x] 5.2 `PaperlessSync.sync_vouchers()`: Abruf mit Lock, Ersetzen des Abzugs nur nach vollständigem Abruf, Fehler in `sevdesk_sync_state`, danach Matching neu berechnen, SSE-Benachrichtigung; Aufruf im `_paperless_loop` nach eigenem Intervall. Prüfen: Tests für Erfolg, Abbruch mitten im Blättern (Abzug unverändert) und gelöschten Beleg.
- [x] 5.3 Nach erfolgreichem Export den neuen Beleg sofort in den Abzug übernehmen und als `id`-Treffer verknüpfen. Prüfen: Test exportiert mit gemocktem SevDesk und findet danach den sicheren Treffer ohne Abruf.

## 6. Einstufung

- [x] 6.1 `_sync_invoices`/`_sync_sevdesk_tag` spiegeln Empfänger-Label und „SevDesk-Beleg“-Wert in die neuen Spalten. Prüfen: Sync-Test mit Dokument mit und ohne Empfänger.
- [x] 6.2 `classify()` nach Design 3 inklusive Fall „Kontext-Option fehlt im Feld“. Prüfen: Unit-Tests für alle Szenarien aus `specs/geschaeftskontext-einstufung/spec.md` (Rangfolge, 3/3-Historie, widersprüchliche Historie, keine Quelle, Schwelle).
- [x] 6.3 `recipient_llm.py`: Tool-Feld `it_consulting_probability` (required), Absatz im System-Block mit dem konfigurierten Label, Parsing mit Bereichsprüfung; Speichern im Cache. Prüfen: `tests/test_recipients.py` prüft Tool-Schema, gültigen Wert und Wert 1,4 → nicht eingeschätzt.
- [x] 6.4 `_collect_missing_ids` nimmt Einträge ohne `it_probability` wieder auf. Prüfen: Test mit altem Cache-Eintrag (wird bearbeitet) und vollständigem Eintrag (wird übersprungen).

## 7. Export

- [x] 7.1 `export_blockers(invoice)` (harte Sperre: sicherer/bestätigter Treffer; Rückfragegründe: offene Dublette, abweichender Empfänger). Prüfen: Unit-Tests je Grund und ohne Grund.
- [x] 7.2 `export_invoice(invoice_id, confirmed=False)`: harte Sperre verhindert Export; Rückfragegründe nur mit `confirmed`; Betrag bei `giro_status` `ready`/`edited` mitgeben; Claim, `failed`/`uncertain` unverändert. Prüfen: bestehende Export-Tests grün, neue Tests für Sperre, Bestätigung und Betrag.
- [x] 7.3 Rückschrieb setzt den Empfänger auf die Kontext-Option und das lokale `recipient_label`; Sync holt fehlende Rückschriebe nach, ohne die Notiz doppelt zu schreiben. Prüfen: Test mit scheiterndem ersten Rückschrieb und erfolgreichem Nachholen; Notiz existiert genau einmal.
- [x] 7.4 Tag-Weg: mit Rückfragegrund Status `review` + `review_reason` statt `queued`/Auto-Export; mit harter Sperre kein Export. Prüfen: Tests für Familien-Empfänger mit Auto-Export, unauffälliges Dokument mit Auto-Export und Dokument mit sicherem Treffer.
- [x] 7.5 Mehrfachexport: exportiert Rechnungen ohne Gründe, liefert die übersprungenen mit Grund. Prüfen: Test mit fünf Rechnungen, eine davon mögliche Dublette.

## 8. Oberfläche

- [x] 8.1 Routen in `app/main.py`: Filterparameter für `/invoices` und `/fragment/invoices`, `POST /invoices/sevdesk-refresh`, `POST /invoices/export-batch`, `POST /invoices/{id}/export` mit `confirm`, `POST /invoices/{id}/dismiss`, `POST /invoices/{id}/matches/{voucher_id}` (bestätigen/verwerfen); statische Routen vor parametrisierten registrieren. Prüfen: `tests/test_web.py` inklusive `test_no_route_is_shadowed_by_a_parametrised_one` grün.
- [x] 8.2 `invoices.html`/`partials/invoice_rows.html`: Spalten Kontext (Konfidenz + Quelle), Abgleich, Filter, Mehrfachauswahl, Abrufstand mit Fehlerhinweis, Hinweis bei fehlender Kontext-Option; SSE-Fragment trägt Filter mit. Prüfen: Web-Tests rendern die Liste mit je einer Rechnung je Kontextquelle und mit „Abgleich nicht verfügbar“.
- [x] 8.3 `partials/invoice_detail_body.html`: Kandidaten mit Score und Bestätigen/Verwerfen, Rückfrage vor dem Export mit Gründen, Prüffall verwerfen. Prüfen: Web-Test löst Export mit Rückfragegrund ohne `confirm` aus und erhält die Rückfrage statt eines Exports.
- [x] 8.4 Texte nach `feature-documentation/ui-texte.md`. Prüfen: Durchsicht der neuen Texte gegen die Richtlinie.

## 9. Abnahme und Dokumentation

- [x] 9.1 **(manuell, mit Agent)** Auf dem NAS: Deployment, erster Belegabruf, Batch-Lauf für Einschätzungen; Stichprobe von zehn Rechnungen (Kontext plausibel? bekannte SevDesk-Belege als Treffer erkannt?); ein Testexport setzt in Paperless den Empfänger IT-Consulting. Prüfen: Befund in `prd/PROGRESS.md` festgehalten, ggf. Score-Gewichte in `design.md` nachgezogen.
- [x] 9.2 Doku: `feature-documentation/paperless-integration/sevdesk-export.md` und `sync-und-aktionen.md` aktualisieren, neu `sevdesk-abgleich.md` und `kontext-einstufung.md`, `empfaenger-zuordnung.md` (neues Tool-Feld, Batch-Auswahl), `README.md` der Integration, `konfiguration.md`, `prd/PROGRESS.md` inklusive Rollback-Hinweis; danach `graphify update .`. Prüfen: Dateien vorhanden und verlinkt, graphify ohne Fehler.
- [x] 9.3 Gesamtprüfung: `uv run pytest` und `uv run ruff check .` grün; `openspec validate sevdesk-export-uebersicht --strict` ohne Befund.
