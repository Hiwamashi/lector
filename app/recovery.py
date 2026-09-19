"""Recovery: Bausteine, um Vorgänge aufzulösen, die durch einen Prozessabbruch mitten
in der Verarbeitung (`status=processing`) hängen geblieben sind.

Die eigentliche Auflösungslogik (Entscheidungstabelle) ist nicht Teil dieses Moduls —
hier steht zunächst nur die Ortsbestimmung des Originals, die diese Logik braucht.
"""

from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path

from .config import Settings
from .models import Document


class OriginalLocation(StrEnum):
    """Wo das Original eines Vorgangs aktuell zu finden ist."""

    WATCH_DIR = "watch_dir"
    PROCESSED_DIR = "processed_dir"
    NOT_FOUND = "not_found"


def locate_original(document: Document, settings: Settings) -> OriginalLocation:
    """Bestimmt, wo das Original eines Vorgangs liegt: Eingang, verarbeitet oder nirgends.

    Betrifft ausdrücklich nur den Eingangsordner (`settings.watch_dir`) und den Ordner
    der verarbeiteten Dateien (`settings.processed_dir`) — der Ausgabeordner
    (`settings.consume_dir`) taugt nicht als Zeuge, weil Paperless ihn überwacht und
    jede eingelesene Datei daraus entfernt.
    """
    if Path(document.source_path).exists():
        return OriginalLocation.WATCH_DIR
    if _find_in_processed(settings.processed_dir, document.original_filename) is not None:
        return OriginalLocation.PROCESSED_DIR
    return OriginalLocation.NOT_FOUND


def _find_in_processed(processed_dir: Path, original_filename: str) -> Path | None:
    """Sucht das Original im Ordner der verarbeiteten Dateien, auch unter Namenszusatz.

    `unique_target` (siehe `app/fileops.py`) hängt bei einer Namenskollision `_1`, `_2`,
    … vor die Dateiendung an. Ohne Berücksichtigung dieses Zusatzes würde ein verschobenes
    Original fälschlich als nirgends auffindbar gelten.
    """
    exact = processed_dir / original_filename
    if exact.exists():
        return exact
    if not processed_dir.exists():
        return None
    stem = Path(original_filename).stem
    suffix = Path(original_filename).suffix
    pattern = re.compile(rf"^{re.escape(stem)}_\d+{re.escape(suffix)}$")
    for entry in processed_dir.iterdir():
        if entry.is_file() and pattern.match(entry.name):
            return entry
    return None
