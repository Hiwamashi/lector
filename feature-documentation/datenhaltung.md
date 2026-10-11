# SQLite-Datenhaltung

**Module:** `app/db.py` (Schema/Verbindung), `app/repository.py` (CRUD), `app/models.py` (Enums/DTOs)

## Schema

- `documents` — eine Zeile pro Eingangsdatei (PRD §4.3). Status-Enum `DocStatus`:
  `pending | processing | done | skipped_erechnung | failed`. Typ-Enum `DocType`:
  `pdf | tiff | image | erechnung_xml | erechnung_pdf`.
- `document_events` — 1:n Verlaufs-Log. Event-Enum `EventType`:
  `detected | preprocessing | ocr_chunk | built_pdf | moved_to_consume | retry_scheduled |
  skipped_erechnung | failed | done`.
- `web_sessions` — Serverseitige Sitzungsliste (nur bei `AUTH_MODE=paperless`). Eine Zeile pro aktive Sitzung:
  - `id`: Eindeutige Sitzungs-ID (`secrets.token_urlsafe(32)`), signiert im Cookie.
  - `username`: Paperless-Nutzername (nicht eindeutig — ein Nutzer kann mehrere Sitzungen haben).
  - `created_at`: Anmeldezeitpunkt (UTC, Format `YYYY-MM-DD HH:MM:SS`). Absolute Obergrenze: 90 Tage.
  - `last_seen_at`: Zeitpunkt der letzten Nutzung (UTC, gleiche Formatierung). Gleitende Obergrenze: 30 Tage.
  
  Die Tabelle wird **nicht** per API manipuliert — nur intern durch `Repository`-Methoden. Ein Abmelden (`POST /logout`) löscht die Zeile; die Datenbank-Bereinigung (Retention-Job) entfernt abgelaufene Zeilen.

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
- **Web-Sitzungen:**
  - `create_web_session(username)`: Legt eine neue Zeile an, liefert die `sid` (ausschließlich serverseitig erzeugt).
  - `get_web_session(sid)`: Liefert `(username, created_at, last_seen_at)` oder `None`.
  - `touch_web_session(sid, now)`: Setzt `last_seen_at` neu (höchstens einmal pro Minute gedrosselt, siehe `LAST_SEEN_WRITE_INTERVAL` in `app/auth.py`).
  - `delete_web_session(sid)`: Löscht diese Sitzung; andere Sitzungen derselben Person bleiben.
  - `purge_web_sessions()`: Entfernt Zeilen mit `last_seen_at` älter als 30 Tage oder `created_at` älter als 90 Tage.

## Aufräumen (Retention)

Der **stündliche Retention-Job** (`app/worker.py`, `_retention_loop()`) und ein **Aufruf beim Start** (Lifespan in `app/main.py`) rufen `repo.purge_web_sessions()` auf. Abgelaufene Sitzungen werden dauerhaft gelöscht; neue Anmeldungen erzeugen neue Einträge.
