"""FastAPI-App: Web-UI, interne API, SSE-Stream und Hintergrund-Worker (siehe PRD §4.1, §5).

Ein Prozess bedient UI/API; im Lifespan wird der Worker gestartet, der Watch-Folder, Queue,
Retry und Retention betreut. Live-Updates laufen über Server-Sent Events.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import get_settings
from .events import EventBus
from .models import DocStatus
from .ocr import get_adapter
from .repository import Repository
from .worker import Worker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

STATUS_LABELS = {
    DocStatus.PENDING: "Wartet",
    DocStatus.PROCESSING: "In Arbeit",
    DocStatus.DONE: "Fertig",
    DocStatus.SKIPPED_ERECHNUNG: "E-Rechnung",
    DocStatus.FAILED: "Fehler",
}


def _fmt_dt(value: datetime | None) -> str:
    if value is None:
        return "—"
    return value.astimezone().strftime("%d.%m.%Y %H:%M")


templates.env.filters["fmt_dt"] = _fmt_dt
templates.env.globals["status_labels"] = STATUS_LABELS


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.ensure_dirs()
    bus = EventBus()
    repo = Repository(settings.db_path, notifier=bus.publish_threadsafe)
    adapter = get_adapter(settings)
    worker = Worker(settings, repo, adapter, bus)
    app.state.settings = settings
    app.state.repo = repo
    app.state.bus = bus
    await worker.start()
    try:
        yield
    finally:
        await worker.stop()
        repo.close()


app = FastAPI(title="Lector", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


def _parse_since(period: str | None) -> datetime | None:
    if period == "24h":
        return datetime.now(UTC) - timedelta(hours=24)
    if period == "7d":
        return datetime.now(UTC) - timedelta(days=7)
    if period == "30d":
        return datetime.now(UTC) - timedelta(days=30)
    return None


def _filters(status: str | None, q: str | None, period: str | None):
    status_enum = None
    if status:
        try:
            status_enum = DocStatus(status)
        except ValueError:
            status_enum = None
    return status_enum, (q or None), _parse_since(period)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    status: str | None = Query(None),
    q: str | None = Query(None),
    period: str | None = Query(None),
):
    repo: Repository = request.app.state.repo
    status_enum, search, since = _filters(status, q, period)
    documents = repo.list_documents(status=status_enum, search=search, since=since)
    counts = repo.status_counts()
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "documents": documents,
            "counts": counts,
            "filters": {"status": status or "", "q": q or "", "period": period or ""},
        },
    )


@app.get("/fragment/history", response_class=HTMLResponse)
async def history_fragment(
    request: Request,
    status: str | None = Query(None),
    q: str | None = Query(None),
    period: str | None = Query(None),
):
    repo: Repository = request.app.state.repo
    status_enum, search, since = _filters(status, q, period)
    documents = repo.list_documents(status=status_enum, search=search, since=since)
    return templates.TemplateResponse(
        request, "partials/history_rows.html", {"documents": documents}
    )


@app.get("/documents/{document_id}", response_class=HTMLResponse)
async def document_detail(request: Request, document_id: int):
    repo: Repository = request.app.state.repo
    doc = repo.get_document(document_id)
    if doc is None:
        return HTMLResponse("Dokument nicht gefunden", status_code=404)
    events = repo.list_events(document_id)
    return templates.TemplateResponse(
        request, "detail.html", {"doc": doc, "events": events}
    )


@app.get("/fragment/documents/{document_id}", response_class=HTMLResponse)
async def document_fragment(request: Request, document_id: int):
    repo: Repository = request.app.state.repo
    doc = repo.get_document(document_id)
    if doc is None:
        return HTMLResponse("", status_code=404)
    events = repo.list_events(document_id)
    return templates.TemplateResponse(
        request, "partials/detail_body.html", {"doc": doc, "events": events}
    )


@app.get("/events")
async def sse(request: Request):
    bus: EventBus = request.app.state.bus
    queue = bus.subscribe()

    async def stream():
        try:
            # Initiales Kommentar-Event hält die Verbindung offen.
            yield ": connected\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    document_id = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"data: {document_id}\n\n"
                except TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            bus.unsubscribe(queue)

    return StreamingResponse(stream(), media_type="text/event-stream")
