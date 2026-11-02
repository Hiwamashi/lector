# Tasks

Testbefehle: `uv run pytest`, `uv run ruff check .`. Nach Codeänderungen `graphify update .`.
Aufgaben mit **(manuell)** laufen gegen die echte Instanz; Befunde nur anonymisiert im
öffentlichen Repository.

## 1. Repository

- [x] 1.1 `app/repository.py`: Vergleich vor dem Schreiben in `upsert_invoice` (D1) – neu oder geänderte Angabe → schreiben, `last_synced_at` setzen, Commit, `inv:`-Token; unverändert → nichts davon. Prüfen: Tests in `tests/test_invoices_repo.py` – zweiter identischer Aufruf ändert `last_synced_at` nicht, sendet kein Token (Notifier-Zähler) und erhöht `conn.total_changes` nicht; geänderter Titel, Empfänger, Beleg-Vermerk und Datum werden geschrieben; leerer Text gleich `None`; nicht übergebenes Spiegelfeld bleibt unberührt.
- [x] 1.2 `upsert_invoices(rows)` (D2): eine Transaktion, ein Commit, Tokens nur für geänderte Rechnungen, Rückgabe je `paperless_id` mit ID, Ergebnis (`new`/`changed`/`unchanged`) und vorherigem Stand. Prüfen: Test mit 3 Zeilen (neu, geändert, unverändert) – genau ein Commit (über `total_changes` bzw. Commit-Zähler), zwei Tokens, korrekte Ergebnisse; leere Liste schreibt nichts.

## 2. Sync

- [x] 2.1 `app/paperless_sync.py`: `_sync_invoices` zweiphasig (sammeln → `upsert_invoices` → Ereignisse und `_extract_and_store` wie bisher, D4). Prüfen: bestehende Tests in `tests/test_voucher_sync.py` grün; neuer Test – zweiter Lauf mit unveränderten Fake-Dokumenten erzeugt kein `SYNCED`-Ereignis, kein Token und keinen Schreibzugriff; geänderter Titel erzeugt genau ein Ereignis.
- [x] 2.2 `_sync_sevdesk_tag` ebenso auf `upsert_invoices` umstellen; Vormerken/Export-Logik unverändert. Prüfen: bestehende Tag-/Export-Tests grün; Test, dass ein Lauf ohne Änderung keine Rechnungszeile schreibt.
- [x] 2.3 Zeitmessung (D5): INFO-Zeile je Lauf mit geprüft/neu/geändert und Dauer je Schritt, ohne Titel/Namen. Prüfen: Test mit `caplog` auf die Zeile und darauf, dass kein Dokumenttitel darin vorkommt.

## 3. Anzeige und Verknüpfung

- [x] 3.1 `invoice_sections.html`: Beschriftung „Zuletzt geändert“ (D3), Kommentar am Modellfeld. Prüfen: Test in `tests/test_web.py` auf die neue Beschriftung; `tests/test_status_consistency.py` grün.
- [x] 3.2 `app/paperless_link.py`: Fehlertyp im Abbruch-Log (D6). Prüfen: Test in `tests/test_paperless_link.py` – `httpx.ReadTimeout` ohne Text ergibt eine Logzeile mit `ReadTimeout`.

## 4. Abschluss

- [x] 4.1 Doku: `feature-documentation/paperless-integration/sync-und-aktionen.md` (Änderungserkennung, gesammeltes Schreiben, Logzeile, „Zuletzt geändert“), `rechnungs-ui.md` (Beschriftung), `scan-verknuepfung.md` (Fehlertyp), `prd/PROGRESS.md`. Prüfen: Dateien enthalten die neuen Punkte.
- [x] 4.2 Gesamtprüfung: `uv run pytest`, `uv run ruff check .`, `graphify update .`, `openspec validate paperless-sync-ohne-stillstand`. Prüfen: alle ohne Fehler.
- [ ] 4.3 **(manuell)** Nach Rollout auf dem NAS: `/healthz`-Antwortzeit über zwei Sync-Takte alle 15 s messen (keine Antwort über 2 s), neue Logzeile zeigt 0 geänderte Rechnungen bei Lauf ohne Änderung und die Schrittdauern, Scan-Verknüpfung läuft ohne Abbruch. Befund anonymisiert in `PROGRESS.md`.
