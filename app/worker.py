"""Hintergrund-Worker: Watch-Folder-Scan, serielle Verarbeitungs-Queue, Auto-Retry und
täglicher Retention-Job (siehe PRD §4.1).

Ein einzelner Thread-Pool-Worker garantiert die serielle Abarbeitung; CPU-lastige Schritte
(OpenCV, PDF-Bau) laufen darin, während der asyncio-Loop für UI/SSE frei bleibt. Ein
watchdog-Observer weckt den Scan-Loop bei neuen Dateien, die eigentliche Bereitschaft
entscheidet die zeitbasierte Stabilitätsprüfung.
"""

from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .config import Settings
from .detection import is_supported
from .events import EventBus
from .fileops import file_hash
from .ocr.base import OcrAdapter
from .paperless_sync import PaperlessSync
from .pipeline import run_pipeline
from .repository import Repository
from .retention import purge_chunk_cache, purge_processed
from .watcher import StabilityTracker, scan_dir

log = logging.getLogger("lector.worker")

_RETRY_POLL_SECONDS = 30.0
_RETENTION_POLL_SECONDS = 3600.0

# Namen der Hintergrundarbeiten, die `start()` immer anlegt (Zeilen 79-84 unten) — im
# Gegensatz zu "paperless-sync", die nur bei wirksamem Feature entsteht.
_ALWAYS_STARTED_TASKS = ("scan", "process", "retry", "retention")
_PAPERLESS_TASK_NAME = "paperless-sync"


class TaskState(StrEnum):
    """Zustand einer einzelnen Hintergrundarbeit des Workers.

    "Nicht gestartet" ist ausdrücklich kein Fehler — sie gilt nur für die
    Paperless-Schleife bei abgeschaltetem Feature. Jede andere fehlende Task ist ein
    struktureller Fehlerfall (siehe `Worker._core_task_status`).
    """

    LAUFEND = "laufend"
    BEENDET = "beendet"
    NICHT_GESTARTET = "nicht_gestartet"


@dataclass
class BackgroundTaskStatus:
    """Zustandsauskunft einer Hintergrundarbeit — rein lesend, keine Selbstheilung."""

    name: str
    state: TaskState
    error: str | None = None


class _WakeHandler(FileSystemEventHandler):
    def __init__(self, wake) -> None:
        self._wake = wake

    def on_any_event(self, event) -> None:
        self._wake()


class Worker:
    def __init__(
        self,
        settings: Settings,
        repo: Repository,
        adapter: OcrAdapter,
        bus: EventBus,
        paperless_sync: PaperlessSync | None = None,
    ) -> None:
        self.settings = settings
        self.repo = repo
        self.adapter = adapter
        self.bus = bus
        self.paperless_sync = paperless_sync
        self.queue: asyncio.Queue[int] = asyncio.Queue()
        self.tracker = StabilityTracker(
            settings.partial_suffix_list, settings.stability_window_seconds
        )
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="lector-pipeline")
        self._inflight: set[int] = set()
        self._wake = asyncio.Event()
        self._stop = asyncio.Event()
        self._tasks: list[asyncio.Task] = []
        self._observer: Observer | None = None
        self._last_retention = 0.0

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        self.bus.bind_loop(loop)
        self._start_observer(loop)
        # Wiederaufnahme: alle offenen pending-Dokumente (z.B. nach Neustart) einreihen.
        for doc in self.repo.claim_due_retries():
            self._enqueue(doc.id)
        self._tasks = [
            asyncio.create_task(self._scan_loop(), name="scan"),
            asyncio.create_task(self._process_loop(), name="process"),
            asyncio.create_task(self._retry_loop(), name="retry"),
            asyncio.create_task(self._retention_loop(), name="retention"),
        ]
        if self.paperless_sync is not None and self.paperless_sync.enabled:
            self._tasks.append(
                asyncio.create_task(self._paperless_loop(), name="paperless-sync")
            )
            log.info(
                "Paperless-Sync aktiv (Intervall %ss)",
                self.settings.paperless_sync_interval_seconds,
            )
        log.info("Worker gestartet, überwacht %s", self.settings.watch_dir)

    async def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=2)
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._executor.shutdown(wait=False, cancel_futures=True)
        log.info("Worker gestoppt")

    def background_task_states(self) -> list[BackgroundTaskStatus]:
        """Meldet je Hintergrundarbeit, ob sie läuft, beendet ist oder wegen eines
        abgeschalteten Features nie gestartet wurde.

        Rein lesend: fragt nur `task.done()`/`task.exception()` ab, startet nichts neu
        und führt keine eigene Buchführung (keinen Zeitstempel, keine Frist) — eine
        wirklich beendete Task ist ein struktureller Fehler, der auffallen soll, statt
        weggeräumt zu werden.
        """
        by_name = {task.get_name(): task for task in self._tasks}
        statuses = [
            self._core_task_status(name, by_name.get(name)) for name in _ALWAYS_STARTED_TASKS
        ]
        statuses.append(self._paperless_task_status(by_name.get(_PAPERLESS_TASK_NAME)))
        return statuses

    def _core_task_status(self, name: str, task: asyncio.Task | None) -> BackgroundTaskStatus:
        """Für die vier Tasks, die `start()` immer anlegt — es gibt für sie kein
        abschaltbares Feature. Fehlt eine dennoch, lief `start()` nie oder brach vorzeitig
        ab: ein Fehlerfall, kein „nicht gestartet, weil abgeschaltet"."""
        if task is None:
            return BackgroundTaskStatus(name, TaskState.BEENDET, error="Task wurde nie gestartet")
        if not task.done():
            return BackgroundTaskStatus(name, TaskState.LAUFEND)
        return BackgroundTaskStatus(name, TaskState.BEENDET, error=self._task_error(task))

    def _paperless_task_status(self, task: asyncio.Task | None) -> BackgroundTaskStatus:
        if task is None:
            if self.paperless_sync is not None and self.paperless_sync.enabled:
                # Feature wirksam, Task aber nicht vorhanden: `start()` lief nie oder
                # brach vor dem Anlegen dieser Task ab — ein Fehlerfall.
                return BackgroundTaskStatus(
                    _PAPERLESS_TASK_NAME, TaskState.BEENDET, error="Task wurde nie gestartet"
                )
            return BackgroundTaskStatus(_PAPERLESS_TASK_NAME, TaskState.NICHT_GESTARTET)
        if not task.done():
            return BackgroundTaskStatus(_PAPERLESS_TASK_NAME, TaskState.LAUFEND)
        return BackgroundTaskStatus(
            _PAPERLESS_TASK_NAME, TaskState.BEENDET, error=self._task_error(task)
        )

    @staticmethod
    def _task_error(task: asyncio.Task) -> str | None:
        """Liest die Ursache einer beendeten Task, ohne an einem Abbruch zu reißen.

        `task.exception()` wirft selbst eine `CancelledError`, wenn die Task abgebrochen
        wurde — auf einer bereits beendeten Task ist das kein Bug, sondern die
        dokumentierte Art, einen Abbruch zu melden. Ungefangen würde die Zustandsauskunft
        an genau dem Zustand reißen, den sie beschreiben soll.
        """
        try:
            exc = task.exception()
        except asyncio.CancelledError:
            return "Task wurde abgebrochen"
        return f"{type(exc).__name__}: {exc}" if exc is not None else None

    # ---- intern ----------------------------------------------------------

    def _start_observer(self, loop: asyncio.AbstractEventLoop) -> None:
        self.settings.watch_dir.mkdir(parents=True, exist_ok=True)
        handler = _WakeHandler(lambda: loop.call_soon_threadsafe(self._wake.set))
        self._observer = Observer()
        self._observer.schedule(handler, str(self.settings.watch_dir), recursive=False)
        self._observer.daemon = True
        self._observer.start()

    def _enqueue(self, document_id: int) -> None:
        if document_id in self._inflight:
            return
        self._inflight.add(document_id)
        self.queue.put_nowait(document_id)

    def _intake_file(self, path: Path) -> None:
        """Legt für eine fertige Eingangsdatei einen DB-Eintrag an (mit Dedup über Hash)."""
        if not is_supported(path):
            log.info("Überspringe nicht unterstützte Datei: %s", path.name)
            return
        try:
            digest = file_hash(path)
        except OSError:
            return
        if self.repo.find_by_hash_active(digest) is not None:
            log.info("Doppelte Datei übersprungen (Hash bekannt): %s", path.name)
            return
        doc_id = self.repo.create_document(
            original_filename=path.name, source_path=str(path), file_hash=digest
        )
        self._enqueue(doc_id)

    async def _scan_loop(self) -> None:
        loop = asyncio.get_running_loop()
        while not self._stop.is_set():
            try:
                candidates = await loop.run_in_executor(
                    None, scan_dir, self.settings.watch_dir
                )
                ready = self.tracker.poll(candidates, now=time.monotonic())
                for path in ready:
                    await loop.run_in_executor(None, self._intake_file, path)
            except Exception:
                log.exception("Fehler im Scan-Loop")
            try:
                await asyncio.wait_for(
                    self._wake.wait(), timeout=self.settings.poll_interval_seconds
                )
            except TimeoutError:
                pass
            self._wake.clear()

    async def _process_loop(self) -> None:
        loop = asyncio.get_running_loop()
        while not self._stop.is_set():
            try:
                doc_id = await asyncio.wait_for(self.queue.get(), timeout=1.0)
            except TimeoutError:
                continue
            try:
                await loop.run_in_executor(
                    self._executor,
                    run_pipeline,
                    doc_id,
                    self.repo,
                    self.settings,
                    self.adapter,
                )
            except Exception:
                log.exception("Pipeline-Ausführung für Dokument %s abgebrochen", doc_id)
            finally:
                self._inflight.discard(doc_id)
                self.queue.task_done()

    async def _retry_loop(self) -> None:
        while not self._stop.is_set():
            try:
                for doc in self.repo.claim_due_retries():
                    self._enqueue(doc.id)
            except Exception:
                log.exception("Fehler im Retry-Loop")
            await asyncio.sleep(_RETRY_POLL_SECONDS)

    async def _retention_loop(self) -> None:
        loop = asyncio.get_running_loop()
        while not self._stop.is_set():
            try:
                await loop.run_in_executor(
                    None,
                    purge_processed,
                    self.settings.processed_dir,
                    self.settings.processed_retention_days,
                )
                await loop.run_in_executor(
                    None,
                    purge_chunk_cache,
                    self.repo,
                    self.settings.chunk_cache_retention_days,
                )
            except Exception:
                log.exception("Fehler im Retention-Loop")
            await asyncio.sleep(_RETENTION_POLL_SECONDS)

    async def _paperless_loop(self) -> None:
        assert self.paperless_sync is not None
        while not self._stop.is_set():
            try:
                await self.paperless_sync.sync_once()
            except Exception:
                log.exception("Fehler im Paperless-Sync-Loop")
            await asyncio.sleep(self.settings.paperless_sync_interval_seconds)
