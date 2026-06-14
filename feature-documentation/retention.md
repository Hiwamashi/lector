# Retention-Job

**Modul:** `app/retention.py` · **Funktion:** `purge_processed(processed_dir, retention_days, now=None)`

Löscht Dateien im `processed`-Ordner, die älter als `PROCESSED_RETENTION_DAYS` (Default 30) sind
(PRD §3.1). **DB-Einträge bleiben** für die Historie erhalten — gelöscht werden nur die Dateien.

- Vergleich über `st_mtime` gegen `now - retention_days*86400`. `now` ist injizierbar (testbar).
- `retention_days <= 0` deaktiviert den Job; nicht löschbare Dateien werden geloggt, nicht
  abgebrochen.
- Ausführung: stündlicher Retention-Loop im Worker (siehe [watch-folder.md](watch-folder.md)).
