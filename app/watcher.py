"""Watch-Folder-Vollständigkeitsprüfung (siehe PRD §4.4, offene Frage 1).

Kombinierte Strategie: Dateien mit einem Teil-Suffix (`.tmp`/`.part`/…) gelten nie als fertig.
Eine reguläre Datei gilt erst als bereit, wenn ihre Größe über ein Zeitfenster
(`stability_window_seconds`) unverändert bleibt. Wird eine `.tmp`-Datei auf ihren Zielnamen
umbenannt, greift dieselbe Stabilitätsprüfung auf dem Zielnamen.

Die Stabilität ist zeit- statt poll-basiert: dadurch darf der Scan jederzeit (z.B. durch ein
watchdog-Ereignis) zusätzlich ausgelöst werden, ohne die Zeitlogik zu verfälschen. Der
`StabilityTracker` ist rein (Zeit wird als Parameter übergeben) und damit gut testbar.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class _Tracked:
    size: int
    last_change: float


class StabilityTracker:
    def __init__(self, partial_suffixes: list[str], stability_window_seconds: float) -> None:
        self._partial = {s.lower() for s in partial_suffixes}
        self._window = max(stability_window_seconds, 0.0)
        self._tracked: dict[Path, _Tracked] = {}
        self._emitted: set[Path] = set()

    def _is_partial(self, path: Path) -> bool:
        return path.suffix.lower() in self._partial

    def poll(self, candidates: list[tuple[Path, int]], now: float) -> list[Path]:
        """Nimmt (Pfad, Größe)-Paare des aktuellen Verzeichnisinhalts plus die aktuelle Zeit
        und liefert die Pfade, die in diesem Poll neu als 'fertig' gelten."""
        present = {p for p, _ in candidates}
        for gone in [p for p in self._tracked if p not in present]:
            self._tracked.pop(gone, None)
        self._emitted &= present

        ready: list[Path] = []
        for path, size in candidates:
            if self._is_partial(path) or path in self._emitted or size <= 0:
                continue
            entry = self._tracked.get(path)
            if entry is None or entry.size != size:
                self._tracked[path] = _Tracked(size=size, last_change=now)
                continue
            if now - entry.last_change >= self._window:
                self._emitted.add(path)
                self._tracked.pop(path, None)
                ready.append(path)
        return ready


def scan_dir(directory: Path) -> list[tuple[Path, int]]:
    result: list[tuple[Path, int]] = []
    if not directory.exists():
        return result
    for entry in directory.iterdir():
        if entry.is_file():
            try:
                result.append((entry, entry.stat().st_size))
            except OSError:
                continue
    return result
