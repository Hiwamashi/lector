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
from .fileops import file_hash as compute_file_hash
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

    Ein Namenstreffer im Verarbeitet-Ordner gilt erst als das gesuchte Original, wenn
    `document.file_hash` ihn bestätigt (siehe `_find_in_processed`) — sonst könnte ein
    fremdes, unbeteiligtes Dokument mit zufällig passendem Namen fälschlich als
    Fundort gelten.
    """
    if Path(document.source_path).exists():
        return OriginalLocation.WATCH_DIR
    match = _find_in_processed(
        settings.processed_dir, document.original_filename, document.file_hash
    )
    if match is not None:
        return OriginalLocation.PROCESSED_DIR
    return OriginalLocation.NOT_FOUND


def _find_in_processed(
    processed_dir: Path, original_filename: str, file_hash: str | None
) -> Path | None:
    """Sucht das Original im Ordner der verarbeiteten Dateien, auch unter Namenszusatz.

    `unique_target` (siehe `app/fileops.py`) hängt bei einer Namenskollision `_1`, `_2`,
    … vor die Dateiendung an — der Namensabgleich berücksichtigt deshalb sowohl den
    exakten Namen als auch diesen Zusatz.

    Der Name allein ist kein Beleg: Ein fremdes Dokument kann rein zufällig genauso
    heißen (mit oder ohne Zusatz), ohne mit dem gesuchten Original identisch zu sein.
    Ein Namenskandidat gilt deshalb erst als bestätigt, wenn sein Inhalt per
    `file_hash()` mit `file_hash` übereinstimmt — dem beim Eingang berechneten Hash
    des Originals (`document.file_hash`, siehe `Worker._intake_file`). Ist `file_hash`
    unbekannt (`None`), ist keine Bestätigung möglich; die Funktion liefert dann
    konsequent `None`, statt einen unbestätigten Namenstreffer zurückzugeben.

    Gehasht werden nur die per Name gefundenen Kandidaten (üblicherweise null bis
    zwei), nicht der gesamte Ordnerinhalt.
    """
    if file_hash is None:
        return None
    if not processed_dir.exists():
        return None
    stem = Path(original_filename).stem
    suffix = Path(original_filename).suffix
    pattern = re.compile(rf"^{re.escape(stem)}(_\d+)?{re.escape(suffix)}$")
    for entry in processed_dir.iterdir():
        if entry.is_file() and pattern.match(entry.name) and compute_file_hash(entry) == file_hash:
            return entry
    return None
