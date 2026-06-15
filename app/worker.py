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
from .retention import purge_processed
from .watcher import StabilityTracker, scan_dir

log = logging.getLogger("lector.worker")

_RETRY_POLL_SECONDS = 30.0
_RETENTION_POLL_SECONDS = 3600.0


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
