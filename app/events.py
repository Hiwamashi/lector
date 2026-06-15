"""SSE-Event-Bus für Live-Updates im Web-UI (siehe PRD §5.2).

Der Worker läuft in Threads und meldet Änderungen über `publish_threadsafe`, das die
Verteilung in den asyncio-Loop einspeist. Abonnenten (SSE-Verbindungen) erhalten ein
typisiertes Token (`doc:<id>` für Dokumente, `inv:<id>` für Paperless-Rechnungen) und laden
die jeweilige Zeile/Detailansicht neu.
"""

from __future__ import annotations

import asyncio


class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[str]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue[str]:
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=1000)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[str]) -> None:
        self._subscribers.discard(queue)

    def _publish(self, token: str) -> None:
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(token)
            except asyncio.QueueFull:
                pass

    def publish_threadsafe(self, token: str) -> None:
        """Aus einem beliebigen Thread aufrufbar (Repository-Notifier). Token z.B. ``doc:42``."""
        if self._loop is None:
            return
        self._loop.call_soon_threadsafe(self._publish, token)
