# Pipeline, Datei-Lifecycle & Auto-Retry

**Module:** `app/pipeline.py` (Orchestrierung), `app/fileops.py` (Dateioperationen)

## `run_pipeline(document_id, repo, settings, adapter)`

Läuft synchron im seriellen Thread-Pool des Workers. Ablauf:

1. Status → `processing`; `detect()`; Event `detected`; `doc_type` speichern.
2. **E-Rechnung:** `copy_into(consume)` (unverändert), Original `move_into(processed)`,
   Status `skipped_erechnung`.
3. **OCR-Weg:** `extract_pages` → `total_pages`/`ocr_engine` setzen → `preprocess_page` je Seite
   → `adapter.process(progress)` (Fortschritt + Event `ocr_chunk` je Block) →
   `build_sandwich_pdf` (Temp) → `move_into(consume, uid/gid)` → Original `move_into(processed)`
   → Status `done`.

Events entlang des Wegs: `preprocessing`, `ocr_chunk`, `built_pdf`, `moved_to_consume`, `done`.

## Fehler & Auto-Retry (`_handle_failure`)

- `attempt_count` wird inkrementiert.
- Solange `attempt_count < RETRY_MAX`: `schedule_retry(RETRY_DELAY_MINUTES)` setzt
  `next_retry_at` und Status zurück auf `pending`; Event `retry_scheduled`.
- Sonst: Original `move_into(error)`, Status `failed` mit `error_message`, Event `failed`.
- Mit Defaults `RETRY_MAX=3` ⇒ Versuche 1+2 planen Retry, Versuch 3 schlägt endgültig fehl.
- **Kein** manueller Retry-Button (PRD §3.1).

## fileops

- `file_hash` (SHA-256, Dedup).
- `unique_target` (kollisionsfreier Zielname, hängt `_1`, `_2`, … an).
- `move_into`/`copy_into` mit optionalem `chown` auf `PUID/PGID` (geteilter consume-Ordner mit
  Paperless). chown-Fehler ohne Root werden bewusst ignoriert.
