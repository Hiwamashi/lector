import asyncio

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from app.config import Settings
from app.events import EventBus
from app.ocr.base import OcrAdapter
from app.paperless_sync import PaperlessSync
from app.repository import Repository
from app.worker import TaskState, Worker


class _Adapter(OcrAdapter):
    """Attrappe — die Pipeline läuft in diesen Tests nie."""

    name = "fake"

    @property
    def page_limit(self):
        return 15

    def process(self, pages, progress=None):  # pragma: no cover - nie aufgerufen
        raise AssertionError("darf nicht laufen")


def _make_worker(tmp_path, *, paperless_sync=None) -> Worker:
    settings = Settings(_env_file=None)
    repo = Repository(tmp_path / "lector.db")
    return Worker(settings, repo, _Adapter(), EventBus(), paperless_sync=paperless_sync)


async def _finish(*tasks: asyncio.Task) -> None:
    """Wartet, bis alle Tasks beendet sind — ohne eine Ausnahme/Abbruch weiterzureichen."""
    if tasks:
        await asyncio.wait(tasks)


async def test_fuenf_laufende_tasks_werden_als_laufend_gemeldet(tmp_path):
    """4.1: An einem Worker mit fünf laufenden Tasks meldet jede Hintergrundarbeit 'läuft'."""
    settings = Settings(
        _env_file=None,
        FEATURE_PAPERLESS_SYNC="true",
        PAPERLESS_URL="http://paperless.invalid",
        PAPERLESS_TOKEN="token",
    )
    repo = Repository(tmp_path / "lector.db")
    sync = PaperlessSync(settings, repo)
    assert sync.enabled is True
    worker = Worker(settings, repo, _Adapter(), EventBus(), paperless_sync=sync)
    names = ("scan", "process", "retry", "retention", "paperless-sync")
    worker._tasks = [asyncio.create_task(asyncio.sleep(10), name=name) for name in names]
    try:
        states = worker.background_task_states()
        assert {s.name for s in states} == set(names)
        assert all(s.state == TaskState.RUNNING for s in states)
        assert all(s.error is None for s in states)
    finally:
        for task in worker._tasks:
            task.cancel()
        await _finish(*worker._tasks)


async def test_abgebrochene_task_wird_gemeldet_statt_zu_werfen(tmp_path):
    """4.2: `task.exception()` wirft `CancelledError` auf einer abgebrochenen Task — die
    Auskunft muss das abfangen und antworten, statt selbst zu reißen."""
    worker = _make_worker(tmp_path)
    task = asyncio.create_task(asyncio.sleep(10), name="scan")
    worker._tasks = [task]
    task.cancel()
    await _finish(task)
    assert task.done()

    states = worker.background_task_states()  # darf nicht werfen

    scan_status = next(s for s in states if s.name == "scan")
    assert scan_status.state == TaskState.STOPPED
    assert scan_status.error is not None


async def test_abgeschaltete_paperless_schleife_gilt_nicht_als_beendet(tmp_path):
    """4.3: Ohne wirksames Feature legt `start()` diese Task gar nicht erst an — das ist
    kein Fehler, jede Standardinstallation läuft so."""
    settings = Settings(_env_file=None)  # FEATURE_PAPERLESS_SYNC default: aus
    repo = Repository(tmp_path / "lector.db")
    sync = PaperlessSync(settings, repo)
    assert sync.enabled is False
    worker = Worker(settings, repo, _Adapter(), EventBus(), paperless_sync=sync)
    worker._tasks = [
        asyncio.create_task(asyncio.sleep(10), name=name)
        for name in ("scan", "process", "retry", "retention")
    ]
    try:
        states = worker.background_task_states()
        paperless_status = next(s for s in states if s.name == "paperless-sync")
        assert paperless_status.state == TaskState.NOT_STARTED
        assert paperless_status.error is None
    finally:
        for task in worker._tasks:
            task.cancel()
        await _finish(*worker._tasks)


async def test_beendete_task_mit_ausnahme_meldet_die_ursache(tmp_path):
    """4.4: Endet eine Task mit einer Ausnahme, gehört deren Ursache in die Auskunft —
    sonst beginnt die Fehlersuche bei 'process beendet' und sonst nichts."""
    worker = _make_worker(tmp_path)

    async def _boom():
        raise RuntimeError("Pipeline kaputt")

    task = asyncio.create_task(_boom(), name="process")
    worker._tasks = [task]
    await _finish(task)
    assert task.done()

    states = worker.background_task_states()

    process_status = next(s for s in states if s.name == "process")
    assert process_status.state == TaskState.STOPPED
    assert process_status.error is not None
    assert "RuntimeError" in process_status.error
    assert "Pipeline kaputt" in process_status.error


def test_leere_tasks_liste_ist_ein_fehlerfall(tmp_path):
    """Läuft `start()` überhaupt nicht, ist das kein 'nicht gestartet, weil
    abgeschaltet' — der Worker sollte laufen. Die vier Kern-Tasks gelten als beendet;
    nur die Paperless-Schleife bleibt 'nicht gestartet', weil sie ihr eigenes,
    abschaltbares Feature hat."""
    worker = _make_worker(tmp_path)  # start() wurde nie aufgerufen, _tasks bleibt leer

    states = worker.background_task_states()

    core = [s for s in states if s.name != "paperless-sync"]
    assert len(core) == 4
    assert all(s.state == TaskState.STOPPED for s in core)
    assert all(s.error is not None for s in core)

    paperless_status = next(s for s in states if s.name == "paperless-sync")
    assert paperless_status.state == TaskState.NOT_STARTED


def _running_observer(tmp_path) -> Observer:
    observer = Observer()
    observer.schedule(FileSystemEventHandler(), str(tmp_path), recursive=False)
    observer.daemon = True
    observer.start()
    return observer


def test_kein_observer_ist_ein_fehlerfall(tmp_path):
    """Important 1: `self._observer is None` (z.B. `start()` lief nie) ist kein
    'nicht gestartet, weil abgeschaltet' — der Beobachter hat kein abschaltbares
    Feature, das Fehlen ist ein struktureller Fehler, analog zu `_core_task_status`."""
    worker = _make_worker(tmp_path)

    status = worker.observer_state()

    assert status.state == TaskState.STOPPED
    assert status.error is not None


async def test_laufender_observer_wird_als_laufend_gemeldet(tmp_path):
    """Important 1: ein tatsächlich laufender Watchdog-Thread meldet 'läuft'."""
    worker = _make_worker(tmp_path)
    observer = _running_observer(tmp_path)
    worker._observer = observer
    try:
        assert observer.is_alive()

        status = worker.observer_state()

        assert status.state == TaskState.RUNNING
        assert status.error is None
    finally:
        observer.stop()
        observer.join(timeout=5)


async def test_beendeter_observer_thread_wird_gemeldet(tmp_path):
    """Important 1: der Thread wird wirklich beendet (nicht nur `_observer = None`
    gesetzt) — sonst bleibt der eigentlich interessante Pfad (`is_alive() is False`)
    ungedeckt."""
    worker = _make_worker(tmp_path)
    observer = _running_observer(tmp_path)
    worker._observer = observer
    assert observer.is_alive()

    observer.stop()
    observer.join(timeout=5)
    assert not observer.is_alive()

    status = worker.observer_state()

    assert status.state == TaskState.STOPPED
    assert status.error is not None


def test_task_state_healthy_unterscheidet_gesund_von_ungesund():
    """Minor 3: die Bewertung 'gesund' steht am Typ, nicht nur in Prosa — ein
    naheliegendes `all(s.state == RUNNING)` an der Verbrauchsstelle (Gruppe 5) würde
    sonst jede Standardinstallation mit abgeschaltetem Feature als ungesund einstufen."""
    assert TaskState.RUNNING.healthy is True
    assert TaskState.NOT_STARTED.healthy is True
    assert TaskState.STOPPED.healthy is False
