"""Dateioperationen: Hashing, kollisionsfreies Verschieben/Kopieren, Eigentümerschaft.

Ergebnis-PDFs müssen im geteilten consume-Ordner der Paperless-UID/GID (1000) gehören.
chown schlägt ohne Root fehl (z.B. lokal/macOS) — das wird bewusst ignoriert.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import threading
from pathlib import Path
from typing import BinaryIO

# Schützt ausschließlich die Zielnamen-Neubestimmung + os.replace() in store_upload()
# gegen gleichzeitige Uploads im eigenen Prozess (Thread-Pool). Gegen einen externen
# Schreiber auf demselben Verzeichnis (z.B. eine SMB-Kopie, die im selben Moment
# denselben Namen anlegt) hilft der Lock nicht — dieser Wettlauf steckt unverändert
# bereits in unique_target() und betrifft den gesamten Code, nicht nur store_upload().
_replace_lock = threading.Lock()


def file_hash(path: Path, chunk_size: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(chunk_size):
            h.update(block)
    return h.hexdigest()


def unique_target(directory: Path, filename: str) -> Path:
    """Liefert einen freien Zielpfad; bei Kollision wird `_1`, `_2`, … angehängt."""
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / filename
    if not target.exists():
        return target
    stem, suffix = target.stem, target.suffix
    n = 1
    while True:
        candidate = directory / f"{stem}_{n}{suffix}"
        if not candidate.exists():
            return candidate
        n += 1


def set_ownership(path: Path, uid: int, gid: int) -> None:
    try:
        os.chown(path, uid, gid)
    except (PermissionError, OSError, AttributeError):
        # Ohne Root nicht möglich; im Container läuft der Prozess passend privilegiert.
        pass


def move_into(
    src: Path, directory: Path, *, uid: int | None = None, gid: int | None = None
) -> Path:
    target = unique_target(directory, src.name)
    shutil.move(str(src), str(target))
    if uid is not None and gid is not None:
        set_ownership(target, uid, gid)
    return target


def copy_into(
    src: Path, directory: Path, *, uid: int | None = None, gid: int | None = None
) -> Path:
    target = unique_target(directory, src.name)
    shutil.copy2(str(src), str(target))
    if uid is not None and gid is not None:
        set_ownership(target, uid, gid)
    return target


def sanitize_upload_filename(raw: str) -> str:
    """Reduziert einen client-gelieferten Namen auf einen unmittelbaren Dateinamen.

    Windows-Clients liefern teils Backslashes als Trenner; beide Trennzeichen zählen,
    nur der letzte Bestandteil bleibt übrig. Ein Name, der danach leer ist oder nur aus
    Punkten besteht (`.`, `..`, `...`), wäre entweder das aktuelle/übergeordnete
    Verzeichnis oder harmlos, aber sinnlos — beides liefert `""` als "unbrauchbar"-Wert,
    den der Aufrufer wie eine nicht unterstützte Endung behandelt. Kein Ersatzname wird
    erfunden, da der Nutzer diesen nie angegeben hat.
    """
    name = raw.strip()
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = name.strip()
    if name == "" or set(name) == {"."}:
        return ""
    return name


def store_upload(
    source: BinaryIO,
    directory: Path,
    filename: str,
    *,
    partial_suffix: str,
    chunk_size: int = 1 << 20,
) -> Path:
    """Schreibt einen Upload-Stream kollisionsfrei und erst nach Abschluss sichtbar.

    Der Stream landet zunächst unter einem Zwischenpfad mit `partial_suffix` und wird
    erst per `os.replace()` (atomar, gleiches Verzeichnis) auf den Zielpfad umbenannt.
    So existiert unter dem Zielnamen nie eine unvollständige Datei. Kollidiert bereits
    der Zwischenpfad (Leiche eines abgebrochenen früheren Uploads), wird auf einen
    freien Zwischenpfad ausgewichen, statt den neuen Upload scheitern zu lassen.

    Der Zielname wird zunächst nur vorläufig bestimmt (Basis für den Zwischenpfad) und
    unmittelbar vor `os.replace()` unter `_replace_lock` neu ermittelt. Ohne diesen
    zweiten, gesperrten Blick könnten zwei gleichzeitige Uploads mit demselben Namen
    beide denselben freien Zielnamen sehen (beide Zieldateien existieren zu Beginn
    noch nicht) und der zweite `os.replace()` würde das gerade fertiggestellte
    Ergebnis des ersten lautlos überschreiben. Das Schreiben der Zwischendatei bleibt
    außerhalb des Locks und damit parallel; serialisiert wird nur die kurze
    Namensentscheidung. Gegen einen gleichzeitigen *externen* Schreiber auf demselben
    Verzeichnis schützt der Lock nicht (siehe Modul-Kommentar zu `_replace_lock`).
    """
    provisional_target = unique_target(directory, filename)
    partial = provisional_target.with_name(provisional_target.name + partial_suffix)
    n = 1
    while partial.exists():
        partial = provisional_target.with_name(f"{provisional_target.name}_{n}{partial_suffix}")
        n += 1
    try:
        with partial.open("wb") as out:
            while block := source.read(chunk_size):
                out.write(block)
        with _replace_lock:
            target = unique_target(directory, filename)
            os.replace(partial, target)
    except BaseException:
        try:
            partial.unlink(missing_ok=True)
        except OSError:
            pass  # Aufräumen ist best effort; der ursprüngliche Fehler zählt.
        raise
    return target
