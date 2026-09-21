"""Retention-Job: löscht Dateien im processed-Ordner, die älter als N Tage sind
(siehe PRD §3.1), und räumt bewahrte OCR-Teilergebnisse auf. DB-Einträge der Vorgänge
bleiben für die Historie erhalten."""

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


def purge_chunk_cache(repo, retention_days: int) -> int:
    """Räumt bewahrte OCR-Teilergebnisse auf, die niemand mehr braucht.

    Zweites Netz neben der Freigabe beim Zustandsübergang: Der Job prüft die Tatsache
    selbst (Vorgang in einem Endzustand, oder Frist abgelaufen) und ist damit unabhängig
    davon, ob jede künftige Endzustandssetzung die Freigabe mitnimmt.
    """
    try:
        deleted = repo.purge_chunk_results(retention_days)
    except Exception:
        log.exception("Aufräumen der bewahrten Teilergebnisse fehlgeschlagen")
        return 0
    if deleted:
        log.info("Retention: %d bewahrte Teilergebnis(se) entfernt", deleted)
    return deleted
