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
from urllib.parse import urlencode

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import get_settings
from .events import EventBus
from .girocode import PaymentData, qr_svg
from .models import DocStatus, GiroStatus, RecipientStatus, SevdeskStatus
from .ocr import get_adapter
from .paperless_sync import PaperlessSync
from .repository import Repository
from .worker import Worker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("lector.main")

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


def _fmt_date(value: datetime | None) -> str:
    if value is None:
        return "—"
    return value.astimezone().strftime("%d.%m.%Y")


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


RECIPIENT_STATUS_LABELS = {
    RecipientStatus.NONE: "",
    RecipientStatus.SUGGESTED: "Vorschlag",
    RecipientStatus.APPLIED: "Gesetzt",
    RecipientStatus.UNKNOWN: "Unklar",
}


templates.env.filters["fmt_dt"] = _fmt_dt
templates.env.filters["fmt_date"] = _fmt_date
templates.env.globals["status_labels"] = STATUS_LABELS
templates.env.globals["sevdesk_labels"] = SEVDESK_LABELS
templates.env.globals["giro_labels"] = GIRO_LABELS
templates.env.globals["recipient_status_labels"] = RECIPIENT_STATUS_LABELS


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.ensure_dirs()
    bus = EventBus()
    repo = Repository(settings.db_path, notifier=bus.publish_threadsafe)
    stale = repo.reset_stale_exports()
    if stale:
        log.warning("%s verwaiste SevDesk-Exporte auf 'uncertain' zurückgesetzt", stale)
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


def _invoice_sort(sort: str | None, direction: str | None) -> tuple[str, bool]:
    """Validiert Sortierspalte (Whitelist) und -richtung; Default: Datum absteigend."""
    key = sort if sort in Repository.INVOICE_SORT_COLUMNS else "date"
    descending = (direction or "desc").lower() != "asc"
    return key, descending


@app.get("/invoices", response_class=HTMLResponse)
async def invoices(
    request: Request,
    sevdesk: str | None = Query(None),
    q: str | None = Query(None),
    sort: str | None = Query(None),
    dir: str | None = Query(None),
):
    repo: Repository = request.app.state.repo
    settings = request.app.state.settings
    status_enum, search = _invoice_filters(sevdesk, q)
    sort_key, descending = _invoice_sort(sort, dir)
    items = repo.list_invoices(
        sevdesk_status=status_enum, search=search, sort=sort_key, descending=descending
    )
    return templates.TemplateResponse(
        request,
        "invoices.html",
        {
            "invoices": items,
            "filters": {"sevdesk": sevdesk or "", "q": q or ""},
            "sort": {"key": sort_key, "dir": "desc" if descending else "asc"},
            "feature_sync": settings.feature_paperless_sync,
            "feature_sevdesk": settings.feature_sevdesk_export,
        },
    )


@app.get("/fragment/invoices", response_class=HTMLResponse)
async def invoices_fragment(
    request: Request,
    sevdesk: str | None = Query(None),
    q: str | None = Query(None),
    sort: str | None = Query(None),
    dir: str | None = Query(None),
):
    repo: Repository = request.app.state.repo
    status_enum, search = _invoice_filters(sevdesk, q)
    sort_key, descending = _invoice_sort(sort, dir)
    items = repo.list_invoices(
        sevdesk_status=status_enum, search=search, sort=sort_key, descending=descending
    )
    return templates.TemplateResponse(
        request, "partials/invoice_rows.html", {"invoices": items}
    )


def _invoice_detail_context(request: Request, invoice_id: int):
    repo: Repository = request.app.state.repo
    settings = request.app.state.settings
    inv = repo.get_invoice(invoice_id)
    if inv is None:
        return None
    public_url = (settings.paperless_public_url or settings.paperless_url).rstrip("/")
    document_url = f"{public_url}/documents/{inv.paperless_id}/details" if public_url else ""
    return {
        "inv": inv,
        "giro_svg": _giro_svg(inv),
        "events": repo.list_invoice_events(invoice_id),
        "feature_sevdesk": settings.feature_sevdesk_export,
        "document_url": document_url,
        "preview_enabled": bool(settings.paperless_url and settings.paperless_token),
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


@app.get("/invoices/{invoice_id}/preview")
async def invoice_preview(request: Request, invoice_id: int):
    """Reicht die Paperless-Dokumentvorschau über Lectors eigene Origin durch.

    So funktioniert die eingebettete Vorschau ohne Paperless-Session im Browser und
    ohne X-Frame-Options-/CORS-Probleme — die Token-Auth läuft serverseitig.
    """
    sync: PaperlessSync = request.app.state.sync
    try:
        result = await sync.fetch_preview(invoice_id)
    except Exception:
        log.exception("Vorschau für Rechnung %s konnte nicht geladen werden", invoice_id)
        return Response("Vorschau nicht verfügbar", status_code=502)
    if result is None:
        return Response("Vorschau nicht verfügbar", status_code=404)
    content, content_type = result
    return Response(content, media_type=content_type, headers={"X-Frame-Options": "SAMEORIGIN"})


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


def _recipient_redirect(page: int, q: str | None, missing: bool) -> str:
    params = {"page": page}
    if q:
        params["q"] = q
    if missing:
        params["missing"] = "1"
    return f"/empfaenger?{urlencode(params)}"


async def _recipient_context(request: Request, page: int, q: str | None, missing: bool) -> dict:
    sync: PaperlessSync = request.app.state.sync
    rows, page_obj, field = await sync.list_recipient_documents(
        page=page, search=q, only_missing=missing
    )
    frag = {"q": q or "", "missing": "1" if missing else "", "page": page_obj.page}
    return {
        "rows": rows,
        "options": field.labels if field else [],
        "field_present": field is not None,
        "page": page_obj.page,
        "total_pages": page_obj.total_pages,
        "count": page_obj.count,
        "filters": {"q": q or "", "missing": missing},
        "fragment_query": urlencode(frag),
        "feature_llm": sync.recipient_llm_enabled,
        "recipient_enabled": sync.recipient_enabled,
        "batch_running": sync.batch_running,
    }


@app.get("/empfaenger", response_class=HTMLResponse)
async def recipients(
    request: Request,
    page: int = Query(1, ge=1),
    q: str | None = Query(None),
    missing: str | None = Query(None),
):
    sync: PaperlessSync = request.app.state.sync
    if not sync.recipient_enabled:
        return templates.TemplateResponse(
            request, "recipients.html", {"recipient_enabled": False, "rows": []}
        )
    ctx = await _recipient_context(request, page, q or None, bool(missing))
    return templates.TemplateResponse(request, "recipients.html", ctx)


@app.get("/fragment/empfaenger", response_class=HTMLResponse)
async def recipients_fragment(
    request: Request,
    page: int = Query(1, ge=1),
    q: str | None = Query(None),
    missing: str | None = Query(None),
):
    sync: PaperlessSync = request.app.state.sync
    if not sync.recipient_enabled:
        return HTMLResponse("", status_code=404)
    ctx = await _recipient_context(request, page, q or None, bool(missing))
    return templates.TemplateResponse(request, "partials/recipient_rows.html", ctx)


@app.post("/empfaenger/{paperless_id}")
async def recipient_set(
    request: Request,
    paperless_id: int,
    recipient: str = Form(""),
    page: int = Form(1),
    q: str = Form(""),
    missing: str = Form(""),
):
    sync: PaperlessSync = request.app.state.sync
    await sync.set_recipient(paperless_id, recipient.strip() or None)
    return RedirectResponse(_recipient_redirect(page, q or None, bool(missing)), status_code=303)


@app.post("/empfaenger/{paperless_id}/suggest")
async def recipient_suggest(
    request: Request,
    paperless_id: int,
    page: int = Form(1),
    q: str = Form(""),
    missing: str = Form(""),
):
    sync: PaperlessSync = request.app.state.sync
    try:
        await sync.suggest_recipient(paperless_id)
    except Exception:
        log.exception("KI-Empfänger-Vorschlag für Dokument %s fehlgeschlagen", paperless_id)
    return RedirectResponse(_recipient_redirect(page, q or None, bool(missing)), status_code=303)


@app.post("/empfaenger/suggest-batch")
async def recipient_suggest_batch(
    request: Request,
    page: int = Form(1),
    q: str = Form(""),
    missing: str = Form(""),
):
    sync: PaperlessSync = request.app.state.sync
    sync.start_batch()
    return RedirectResponse(_recipient_redirect(page, q or None, bool(missing)), status_code=303)


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
