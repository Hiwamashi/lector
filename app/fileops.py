"""Dateioperationen: Hashing, kollisionsfreies Verschieben/Kopieren, Eigentümerschaft.

Ergebnis-PDFs müssen im geteilten consume-Ordner der Paperless-UID/GID (1000) gehören.
chown schlägt ohne Root fehl (z.B. lokal/macOS) — das wird bewusst ignoriert.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path


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
