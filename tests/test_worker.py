import asyncio

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
        assert all(s.state == TaskState.LAUFEND for s in states)
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
    assert scan_status.state == TaskState.BEENDET
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
        assert paperless_status.state == TaskState.NICHT_GESTARTET
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
    assert process_status.state == TaskState.BEENDET
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
    assert all(s.state == TaskState.BEENDET for s in core)
    assert all(s.error is not None for s in core)

    paperless_status = next(s for s in states if s.name == "paperless-sync")
    assert paperless_status.state == TaskState.NICHT_GESTARTET
