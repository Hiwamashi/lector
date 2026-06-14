# Watch-Folder, Queue & Worker

**Module:** `app/watcher.py` (Stabilitätsprüfung), `app/worker.py` (Orchestrierung)

## Vollständigkeitsprüfung (`StabilityTracker`)

Kombinierte Strategie (PRD offene Frage 1, entschieden):

1. Dateien mit Teil-Suffix (`.tmp`/`.part`/`.crdownload`) gelten **nie** als fertig.
2. Eine reguläre Datei gilt erst als bereit, wenn ihre Größe über
   `STABILITY_WINDOW_SECONDS` unverändert bleibt (zeitbasiert, nicht poll-basiert).
3. Wird `.tmp` auf den Zielnamen umbenannt, greift dieselbe Stabilitätsprüfung am Zielnamen.

`poll(candidates, now)` ist rein (Zeit als Parameter) → gut testbar. Jede Datei wird genau
einmal als „ready" emittiert; verschwundene Dateien fallen aus dem Zustand.

> Die Zeitbasis macht den Tracker robust gegen zusätzliche Auslöser: Ein watchdog-Ereignis darf
> den Scan jederzeit anstoßen, ohne die Stabilitätslogik zu verfälschen.

## Worker

`Worker` startet im FastAPI-Lifespan vier asyncio-Tasks plus einen watchdog-Observer:

- **Scan-Loop:** alle `POLL_INTERVAL_SECONDS` (oder bei watchdog-Weckung) `scan_dir` +
  `tracker.poll`; fertige, unterstützte Dateien → `_intake_file` (Hash + Dedup) →
  DB-Eintrag → Queue.
- **Process-Loop:** konsumiert die Queue **seriell** und führt `run_pipeline` in einem
  `ThreadPoolExecutor(max_workers=1)` aus → CPU-Last blockiert den Event-Loop (UI/SSE) nicht.
- **Retry-Loop:** alle 30 s `claim_due_retries` → erneut einreihen.
- **Retention-Loop:** stündlich `purge_processed` (siehe [retention.md](retention.md)).

**Doppel-Einreihung vermeiden:** ein In-Memory-Set `_inflight` verhindert, dass dasselbe
Dokument gleichzeitig über Scan, Retry oder Startup-Wiederaufnahme mehrfach in die Queue
gelangt. Nach Abschluss wird die ID wieder entfernt.

**Wiederaufnahme nach Neustart:** beim Start werden alle offenen `pending`-Dokumente erneut
eingereiht.
