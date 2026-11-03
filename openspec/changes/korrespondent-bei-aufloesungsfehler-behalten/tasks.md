# Tasks

## 1. Repository

- [x] 1.1 `app/repository.py`: `InvoiceUpsert.correspondent` und der Parameter `correspondent` von `upsert_invoice` erlauben `_UNSET`; `_upsert_invoice_locked` lässt das Feld bei `_UNSET` aus Vergleich und `UPDATE` weg und schreibt beim `INSERT` `NULL` (D2). Prüfen: Tests in `tests/test_invoices_repo.py` für unverändert (kein Commit, kein Signal), Titeländerung mit `_UNSET`-Korrespondent (Korrespondent bleibt) und Neuanlage mit `_UNSET` (`NULL`).

## 2. Sync

- [x] 2.1 `app/paperless_sync.py`: Hilfsfunktion für den Sync, die `None` / Name / `_UNSET` liefert (D1, D5), mit Warnung im Log (D4); `_correspondent_name` behält ihr Verhalten. `_upsert_row` nutzt die neue Funktion. Prüfen: Tests für Karte trifft, Einzelabruf trifft, Einzelabruf wirft (Exception und HTTP-404) → `_UNSET` und Logzeile, Dokument ohne Korrespondent → `None`; bestehende Tests zu `_correspondent_name` grün.
- [x] 2.2 `_sync_invoices`: `synced`-Ereignis nur bei echter Korrespondenten-Änderung, `_UNSET` zählt nicht (D3). Prüfen: Sync-Test mit fehlschlagendem Einzelabruf: Korrespondent bleibt, kein Ereignis, `geändert=0`; Folge-Lauf mit erfolgreicher Auflösung bei neu angelegter Rechnung trägt den Namen nach und erzeugt ein Ereignis; Dokument ohne Korrespondent leert das Feld.

## 3. Abschluss

- [x] 3.1 Doku: `feature-documentation/paperless-integration/sync-und-aktionen.md` (Rückfall auf den Einzelabruf, Verhalten bei Fehlschlag), `prd/PROGRESS.md` (bekannten Punkt als erledigt markieren, Abschnitt für den Change). Prüfen: Dateien aktualisiert.
- [x] 3.2 Gesamtprüfung: `uv run pytest`, `uv run ruff check .`, `graphify update .`, `openspec validate korrespondent-bei-aufloesungsfehler-behalten`. Prüfen: Ausgaben ohne Fehler.
