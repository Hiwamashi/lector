"""OCR-Adapter-Interface (engine-unabhängig).

Jeder Adapter kennt sein eigenes Seitenlimit und chunkt intern (siehe PRD §4.4). Die
Bildvorverarbeitung und der Sandwich-PDF-Bau liegen engine-unabhängig darüber.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import Protocol

from PIL import Image

from ..models import OcrPage, OcrResult

log = logging.getLogger("lector.ocr")


class ProgressCallback(Protocol):
    """Wird mit der kumulierten Anzahl fertig verarbeiteter Seiten aufgerufen.

    `from_cache` sagt, ob der eben abgeschlossene Block aus dem Zwischenspeicher kam — ohne
    das sähe ein Lauf, der ein langes Dokument in Sekunden abschließt, wie eine
    Fehlfunktion aus. Der Vorgabewert hält ältere Aufrufer am Leben, die nur die
    Seitenzahl übergeben.
    """

    def __call__(self, processed: int, from_cache: bool = False) -> None: ...


class ChunkStore(Protocol):
    """Ablageort für bewahrte Blockergebnisse, engine-unabhängig.

    Der Adapter kennt nur Blockindizes. An welchen Vorgang und welche Bedingungen ein
    Eintrag gebunden ist, entscheidet der Aufrufer, der den Ablageort fertig bestückt
    übergibt — ein künftiger Adapter erbt die Ersparnis damit, ohne etwas dafür zu tun.
    """

    def get(self, chunk_index: int) -> list[OcrPage] | None:
        """Bewahrtes Ergebnis dieses Blocks, oder None."""

    def put(self, chunk_index: int, pages: list[OcrPage]) -> None:
        """Ergebnis dieses Blocks bewahren."""


class SafeChunkStore:
    """Hülle, die jeden Fehler des Ablageorts verschluckt (siehe design.md D4).

    Die Verhältnismäßigkeit ist eindeutig: Ein nicht bewahrter Block kostet einen
    erneuten Aufruf, ein wegen des Zwischenspeichers abgebrochener Lauf kostet alle.
    """

    def __init__(self, inner: ChunkStore) -> None:
        self._inner = inner

    def get(self, chunk_index: int) -> list[OcrPage] | None:
        try:
            return self._inner.get(chunk_index)
        except Exception:
            log.warning("Zwischenspeicher nicht lesbar (Block %s)", chunk_index, exc_info=True)
            return None

    def put(self, chunk_index: int, pages: list[OcrPage]) -> None:
        try:
            self._inner.put(chunk_index, pages)
        except Exception:
            log.warning("Block %s ließ sich nicht bewahren", chunk_index, exc_info=True)


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
    def identity(self) -> str:
        """Alles, was diese Engine für ein Erkennungsergebnis identifiziert.

        Vorgabewert ist `name`. Eine Engine mit mehreren Konfigurationen (Projekt, Region,
        Prozessor, Modellversion, ...) MUSS diese Eigenschaft überschreiben — sonst bliebe
        ein bewahrter Block nach dem Umkonfigurieren fälschlich gültig, weil `chunk_fingerprint`
        davon nichts wüsste.
        """
        return self.name

    @property
    @abstractmethod
    def page_limit(self) -> int:
        """Maximale Seitenzahl pro Online-Request dieser Engine."""

    @abstractmethod
    def process(
        self,
        pages: list[Image.Image],
        progress: ProgressCallback | None = None,
        store: ChunkStore | None = None,
    ) -> OcrResult:
        """Erkennt Text + Bounding-Boxes für alle Seiten. Chunkt intern bis page_limit.

        Ist `store` gesetzt, MUSS der Adapter vor jedem Block dort nachsehen und einen
        Treffer verwenden, statt die Engine zu fragen; jeder frisch erkannte Block wird
        abgelegt, bevor der nächste beginnt. Der übergebene `store` ist bereits gegen eigene
        Fehler abgesichert (der Aufrufer hüllt ihn in `SafeChunkStore`) — der Adapter muss
        sich darum nicht kümmern.
        """
