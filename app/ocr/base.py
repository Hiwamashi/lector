"""OCR-Adapter-Interface (engine-unabhängig).

Jeder Adapter kennt sein eigenes Seitenlimit und chunkt intern (siehe PRD §4.4). Die
Bildvorverarbeitung und der Sandwich-PDF-Bau liegen engine-unabhängig darüber.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator

from PIL import Image

from ..models import OcrResult

# Wird mit der kumulierten Anzahl fertig verarbeiteter Seiten aufgerufen.
ProgressCallback = Callable[[int], None]


def chunked[T](items: list[T], size: int) -> Iterator[list[T]]:
    if size < 1:
        raise ValueError("Chunkgröße muss >= 1 sein")
    for i in range(0, len(items), size):
        yield items[i : i + size]


class RateLimiter:
    """Einfaches seitenbasiertes Rate-Limit gegen die Document-AI-Quota (pages per minute).

    Vor dem Versand eines Blocks wird so lange gewartet, dass die durchschnittliche Rate
    `max_pages_per_minute` nicht überschreitet. Bei <= 0 ist das Limit deaktiviert.
    """

    def __init__(self, max_pages_per_minute: int) -> None:
        self._seconds_per_page = 60.0 / max_pages_per_minute if max_pages_per_minute > 0 else 0.0
        self._next_allowed = time.monotonic()

    def acquire(self, pages: int) -> None:
        if self._seconds_per_page <= 0:
            return
        now = time.monotonic()
        wait = self._next_allowed - now
        if wait > 0:
            time.sleep(wait)
            now = time.monotonic()
        self._next_allowed = max(now, self._next_allowed) + pages * self._seconds_per_page


class OcrAdapter(ABC):
    name: str = "abstract"

    @property
    @abstractmethod
    def page_limit(self) -> int:
        """Maximale Seitenzahl pro Online-Request dieser Engine."""

    @abstractmethod
    def process(
        self, pages: list[Image.Image], progress: ProgressCallback | None = None
    ) -> OcrResult:
        """Erkennt Text + Bounding-Boxes für alle Seiten. Chunkt intern bis page_limit."""
