# SQLite-Datenhaltung

**Module:** `app/db.py` (Schema/Verbindung), `app/repository.py` (CRUD), `app/models.py` (Enums/DTOs)

## Schema

- `documents` — eine Zeile pro Eingangsdatei (PRD §4.3). Status-Enum `DocStatus`:
  `pending | processing | done | skipped_erechnung | failed`. Typ-Enum `DocType`:
  `pdf | tiff | image | erechnung_xml | erechnung_pdf`.
- `document_events` — 1:n Verlaufs-Log. Event-Enum `EventType`:
  `detected | preprocessing | ocr_chunk | built_pdf | moved_to_consume | retry_scheduled |
  skipped_erechnung | failed | done`.

WAL-Modus, Foreign-Keys und `busy_timeout` sind aktiviert (`db.connect`).

## Repository

`Repository(db_path, notifier)` kapselt alle DB-Zugriffe.

- **Threadsicherheit:** eine geteilte Verbindung (`check_same_thread=False`) plus
  `threading.Lock`, weil der Worker im Thread-Pool und FastAPI-Handler im Event-Loop
  parallel zugreifen.
- **Notifier:** Bei jeder Änderung wird `notifier(document_id)` aufgerufen → speist den
  SSE-Bus (siehe [web-ui-sse.md](web-ui-sse.md)).
- **Zeitstempel:** `set_status` setzt `started_at` (→processing) bzw. `finished_at`
  (→done/skipped/failed) automatisch. Zeiten werden als UTC geparst.
- **Dedup:** `find_by_hash_active(hash)` findet ein nicht endgültig fehlgeschlagenes Dokument
  gleichen Inhalts (Doppelverarbeitungs-Schutz).
- **Retry-Auswahl:** `claim_due_retries()` liefert alle `pending`-Dokumente mit fälligem oder
  fehlendem `next_retry_at`.
- **Filter:** `list_documents(status, search, since, limit, offset)` für die Historientabelle;
  `status_counts()` für die Dashboard-Kacheln.
