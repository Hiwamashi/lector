"""Retention-Job: löscht Dateien im processed-Ordner, die älter als N Tage sind
(siehe PRD §3.1). DB-Einträge bleiben für die Historie erhalten."""

from __future__ import annotations

import logging
import time
from pathlib import Path

log = logging.getLogger("lector.retention")


def purge_processed(processed_dir: Path, retention_days: int, *, now: float | None = None) -> int:
    """Löscht Dateien älter als `retention_days`. Gibt die Anzahl gelöschter Dateien zurück."""
    if retention_days <= 0 or not processed_dir.exists():
        return 0
    cutoff = (now if now is not None else time.time()) - retention_days * 86400
    deleted = 0
    for entry in processed_dir.iterdir():
        if not entry.is_file():
            continue
        try:
            if entry.stat().st_mtime < cutoff:
                entry.unlink()
                deleted += 1
        except OSError:
            log.warning("Konnte Datei nicht löschen: %s", entry)
    if deleted:
        log.info("Retention: %d Datei(en) aus %s gelöscht", deleted, processed_dir)
    return deleted
