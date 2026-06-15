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

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import get_settings
from .events import EventBus
from .girocode import PaymentData, qr_svg
from .models import DocStatus, GiroStatus, SevdeskStatus
from .ocr import get_adapter
from .paperless_sync import PaperlessSync
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


SEVDESK_LABELS = {
    SevdeskStatus.NONE: "—",
    SevdeskStatus.QUEUED: "Vorgemerkt",
    SevdeskStatus.EXPORTING: "Wird exportiert",
    SevdeskStatus.EXPORTED: "Exportiert",
    SevdeskStatus.FAILED: "Fehler",
    SevdeskStatus.UNCERTAIN: "Unklar – prüfen",
}

GIRO_LABELS = {
    GiroStatus.NONE: "—",
    GiroStatus.READY: "Bereit",
    GiroStatus.EDITED: "Bearbeitet",
    GiroStatus.FAILED: "Unvollständig",
}


def _payment_from_invoice(inv) -> PaymentData:
    return PaymentData(
        creditor_name=inv.creditor_name,
        iban=inv.iban,
        bic=inv.bic,
        amount=inv.amount,
        currency=inv.currency,
        purpose=inv.purpose,
    )


def _giro_svg(inv) -> str | None:
    payment = _payment_from_invoice(inv)
    if not payment.is_payable:
        return None
    try:
        return qr_svg(payment)
    except ValueError:
        return None


def _parse_amount(value: str | None) -> float | None:
    if not value:
        return None
    cleaned = value.strip().replace(" ", "").replace(",", ".")
    try:
        return round(float(cleaned), 2)
    except ValueError:
        return None


templates.env.filters["fmt_dt"] = _fmt_dt
templates.env.globals["status_labels"] = STATUS_LABELS
templates.env.globals["sevdesk_labels"] = SEVDESK_LABELS
templates.env.globals["giro_labels"] = GIRO_LABELS


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.ensure_dirs()
    bus = EventBus()
    repo = Repository(settings.db_path, notifier=bus.publish_threadsafe)
    adapter = get_adapter(settings)
    sync = PaperlessSync(settings, repo)
    worker = Worker(settings, repo, adapter, bus, paperless_sync=sync)
    app.state.settings = settings
    app.state.repo = repo
    app.state.bus = bus
    app.state.sync = sync
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


def _invoice_filters(sevdesk: str | None, q: str | None):
    status_enum = None
    if sevdesk:
        try:
            status_enum = SevdeskStatus(sevdesk)
        except ValueError:
            status_enum = None
    return status_enum, (q or None)


@app.get("/invoices", response_class=HTMLResponse)
async def invoices(
    request: Request,
    sevdesk: str | None = Query(None),
    q: str | None = Query(None),
):
    repo: Repository = request.app.state.repo
    settings = request.app.state.settings
    status_enum, search = _invoice_filters(sevdesk, q)
    items = repo.list_invoices(sevdesk_status=status_enum, search=search)
    return templates.TemplateResponse(
        request,
        "invoices.html",
        {
            "invoices": items,
            "filters": {"sevdesk": sevdesk or "", "q": q or ""},
            "feature_sync": settings.feature_paperless_sync,
            "feature_sevdesk": settings.feature_sevdesk_export,
        },
    )


@app.get("/fragment/invoices", response_class=HTMLResponse)
async def invoices_fragment(
    request: Request,
    sevdesk: str | None = Query(None),
    q: str | None = Query(None),
):
    repo: Repository = request.app.state.repo
    status_enum, search = _invoice_filters(sevdesk, q)
    items = repo.list_invoices(sevdesk_status=status_enum, search=search)
    return templates.TemplateResponse(
        request, "partials/invoice_rows.html", {"invoices": items}
    )


def _invoice_detail_context(request: Request, invoice_id: int):
    repo: Repository = request.app.state.repo
    settings = request.app.state.settings
    inv = repo.get_invoice(invoice_id)
    if inv is None:
        return None
    return {
        "inv": inv,
        "giro_svg": _giro_svg(inv),
        "events": repo.list_invoice_events(invoice_id),
        "feature_sevdesk": settings.feature_sevdesk_export,
    }


@app.get("/invoices/{invoice_id}", response_class=HTMLResponse)
async def invoice_detail(request: Request, invoice_id: int):
    ctx = _invoice_detail_context(request, invoice_id)
    if ctx is None:
        return HTMLResponse("Rechnung nicht gefunden", status_code=404)
    return templates.TemplateResponse(request, "invoice_detail.html", ctx)


@app.get("/fragment/invoices/{invoice_id}", response_class=HTMLResponse)
async def invoice_detail_fragment(request: Request, invoice_id: int):
    ctx = _invoice_detail_context(request, invoice_id)
    if ctx is None:
        return HTMLResponse("", status_code=404)
    return templates.TemplateResponse(request, "partials/invoice_detail_body.html", ctx)


@app.post("/invoices/{invoice_id}/giro")
async def invoice_save_giro(
    request: Request,
    invoice_id: int,
    creditor_name: str = Form(""),
    iban: str = Form(""),
    bic: str = Form(""),
    amount: str = Form(""),
    purpose: str = Form(""),
):
    sync: PaperlessSync = request.app.state.sync
    await sync.save_giro_edits(
        invoice_id,
        creditor_name=creditor_name.strip() or None,
        iban=iban.strip() or None,
        bic=bic.strip() or None,
        amount=_parse_amount(amount),
        purpose=purpose.strip() or None,
    )
    return RedirectResponse(f"/invoices/{invoice_id}", status_code=303)


@app.post("/invoices/{invoice_id}/export")
async def invoice_export(request: Request, invoice_id: int):
    sync: PaperlessSync = request.app.state.sync
    await sync.export_invoice(invoice_id)
    return RedirectResponse(f"/invoices/{invoice_id}", status_code=303)


@app.post("/invoices/{invoice_id}/paid")
async def invoice_paid(request: Request, invoice_id: int, paid: str = Form("true")):
    sync: PaperlessSync = request.app.state.sync
    await sync.set_paid(invoice_id, paid.lower() in ("1", "true", "on", "yes"))
    return RedirectResponse(f"/invoices/{invoice_id}", status_code=303)


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
