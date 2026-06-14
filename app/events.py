"""SSE-Event-Bus für Live-Updates im Web-UI (siehe PRD §5.2).

Der Worker läuft in Threads und meldet Dokument-Änderungen über `publish_threadsafe`, das die
Verteilung in den asyncio-Loop einspeist. Abonnenten (SSE-Verbindungen) erhalten die
betroffene document_id und laden die jeweilige Zeile/Detailansicht per HTMX neu.
"""

from __future__ import annotations

import asyncio


class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[int]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue[int]:
        queue: asyncio.Queue[int] = asyncio.Queue(maxsize=1000)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[int]) -> None:
        self._subscribers.discard(queue)

    def _publish(self, document_id: int) -> None:
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(document_id)
            except asyncio.QueueFull:
                pass

    def publish_threadsafe(self, document_id: int) -> None:
        """Aus einem beliebigen Thread aufrufbar (Repository-Notifier)."""
        if self._loop is None:
            return
        self._loop.call_soon_threadsafe(self._publish, document_id)
