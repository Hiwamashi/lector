"""FastAPI-App: Web-UI, interne API, SSE-Stream und Hintergrund-Worker (siehe PRD §4.1, §5).

Ein Prozess bedient UI/API; im Lifespan wird der Worker gestartet, der Watch-Folder, Queue,
Retry und Retention betreut. Live-Updates laufen über Server-Sent Events.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import tempfile
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

import httpx
from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import ConfigurationRejectedError, Settings, get_settings, validate_settings
from .decisions import DecisionResult, discard_document, release_document
from .events import EventBus
from .girocode import PaymentData, qr_svg
from .models import DocStatus, GiroStatus, RecipientStatus, SevdeskStatus
from .ocr import get_adapter
from .paperless_sync import PaperlessSync
from .recovery import resolve_stale_processing
from .repository import Repository
from .worker import Worker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("lector.main")

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


STATUS_LABELS = {
    DocStatus.PENDING: "Wartet",
    DocStatus.PROCESSING: "In Arbeit",
    DocStatus.BLOCKED: "Angehalten",
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


STATIC_DIR = BASE_DIR / "static"


def static_url(name: str) -> str:
    """URL einer statischen Datei mit Inhalts-Fingerabdruck (``?v=…``).

    Ohne diesen Zusatz liefert Starlette ``/static/app.css`` zwar mit ``ETag`` und
    ``Last-Modified`` aus, aber **ohne** ``Cache-Control``. Browser wenden dann
    heuristisches Caching an (RFC 9111 §4.2.2) und benutzen die alte Datei stundenlang
    weiter, ohne zu revalidieren. Nach einem Deploy sieht der Anwender dadurch frisches
    HTML mit altem CSS/JS — die Ursache dafuer, dass Fixes an ``app.js`` scheinbar
    wirkungslos blieben und der Fortschrittsbalken unsichtbar war.

    Der Fingerabdruck wird beim ersten Zugriff aus dem Dateiinhalt gebildet und im
    Prozess gehalten: Ein neues Image bedeutet einen neuen Prozess und damit eine neue
    URL, eine unveraenderte Datei behaelt ihre URL (und bleibt im Cache nutzbar).
    """
    if name not in _static_versions:
        try:
            digest = hashlib.sha256((STATIC_DIR / name).read_bytes()).hexdigest()[:10]
        except OSError:
            # Fehlende Datei nicht zum Startfehler machen — ohne Fingerabdruck ausliefern.
            digest = ""
        _static_versions[name] = digest
    version = _static_versions[name]
    return f"/static/{name}?v={version}" if version else f"/static/{name}"


_static_versions: dict[str, str] = {}


templates.env.filters["fmt_dt"] = _fmt_dt
templates.env.filters["fmt_date"] = _fmt_date
templates.env.globals["status_labels"] = STATUS_LABELS
templates.env.globals["sevdesk_labels"] = SEVDESK_LABELS
templates.env.globals["giro_labels"] = GIRO_LABELS
templates.env.globals["recipient_status_labels"] = RECIPIENT_STATUS_LABELS
templates.env.globals["static_url"] = static_url


def _reject_startup(problems: list[str]) -> None:
    """Bricht den Start ab: protokolliert alle Beanstandungen zuerst als zusammenhängenden
    Block über `log.error`, wirft danach die Ausnahme. Trüge nur die Ausnahme die Meldung,
    erschiene sie lediglich als Teil eines Tracebacks zwischen Starlette- und
    uvicorn-Rahmen — die eigene Protokollzeile steht davor und ist die erste Zeile, die man
    beim Lesen von `docker logs` findet (design.md D3)."""
    block = "\n".join(f"  {p}" for p in problems)
    log.error("Konfiguration unvollständig — der Dienst startet nicht:\n%s", block)
    raise ConfigurationRejectedError(problems)


def _check_writable_paths(settings: Settings) -> list[str]:
    """Schreibprobe für die vier Arbeitsordner und das Verzeichnis von `DB_PATH`: legt in
    jedem tatsächlich eine Datei an und entfernt sie wieder, statt `os.access` zu befragen.

    Der Prozess läuft im Container als root, und `os.access` beantwortet die Frage für
    root fast immer mit 'ja' — auch auf einem schreibgeschützt eingehängten Volume. Gegen
    falsche Berechtigungen hilft das als root ohnehin nicht; der Fall, den diese Probe
    fängt, ist der falsch eingehängte Ordner (`:ro`, fehlendes Volume, vollgelaufenes
    Volume) — und das ist der Fall, der im Compose-Stack passiert (design.md D4)."""
    directories = {
        "WATCH_DIR": settings.watch_dir,
        "CONSUME_DIR": settings.consume_dir,
        "PROCESSED_DIR": settings.processed_dir,
        "ERROR_DIR": settings.error_dir,
        "Verzeichnis von DB_PATH": settings.db_path.parent,
    }
    problems: list[str] = []
    for env_name, directory in directories.items():
        try:
            with tempfile.NamedTemporaryFile(dir=directory, prefix=".lector-schreibprobe-"):
                pass
        except OSError as exc:
            problems.append(f"{env_name} ({directory}) ist nicht beschreibbar: {exc}")
    return problems


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    problems = validate_settings(settings)
    if problems:
        _reject_startup(problems)
    settings.ensure_dirs()
    problems = _check_writable_paths(settings)
    if problems:
        _reject_startup(problems)
    bus = EventBus()
    repo = Repository(settings.db_path, notifier=bus.publish_threadsafe)
    stale = repo.reset_stale_exports()
    if stale:
        log.warning("%s verwaiste SevDesk-Exporte auf 'uncertain' zurückgesetzt", stale)
    resolved = resolve_stale_processing(repo, settings)
    if resolved:
        log.warning("%s unterbrochene Vorgänge nach Neustart aufgelöst", resolved)
    adapter = get_adapter(settings)
    sync = PaperlessSync(settings, repo)
    worker = Worker(settings, repo, adapter, bus, paperless_sync=sync)
    app.state.settings = settings
    app.state.repo = repo
    app.state.bus = bus
    app.state.sync = sync
    app.state.worker = worker
    await worker.start()
    try:
        yield
    finally:
        await worker.stop()
        # Ein laufender Empfänger-Batch muss VOR repo.close() enden — sonst könnte der
        # Hintergrund-Task bei einem SIGTERM mitten im Lauf auf die bereits geschlossene
        # SQLite-Verbindung zugreifen.
        await sync.shutdown()
        repo.close()


app = FastAPI(title="Lector", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

@app.exception_handler(httpx.HTTPError)
async def paperless_unavailable(request: Request, exc: httpx.HTTPError) -> Response:
    """Faengt jeden fehlgeschlagenen Paperless-Aufruf ab, der bis zur Route durchschlaegt.

    Typischer Fall: Der Compose-Stack startet und Paperless ist noch nicht bereit — dann
    liefert httpx einen ConnectError. Ohne diesen Handler sieht der Anwender einen
    Internal Server Error samt Stacktrace, obwohl schlicht ein Dienst fehlt.

    Fragmente (per fetch nachgeladen) bekommen bewusst nur einen kurzen Hinweis statt einer
    kompletten Seite: Ihr Inhalt wird per innerHTML eingesetzt: eine ganze Fehlerseite
    wuerde die Tabelle zerschiessen.
    """
    log.warning("Paperless nicht erreichbar (%s): %s", request.url.path, exc)
    hinweis = (
        "Paperless ist derzeit nicht erreichbar. Laeuft der Container schon? "
        "Beim Start des Stacks dauert es einen Moment, bis Paperless antwortet."
    )
    if request.url.path.startswith("/fragment/"):
        return HTMLResponse(f'<p class="alert">{hinweis}</p>', status_code=503)
    return templates.TemplateResponse(
        request, "unavailable.html", {"hinweis": hinweis}, status_code=503
    )


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


def _health_status(
    worker: Worker, repo: Repository
) -> tuple[bool, dict[str, dict[str, str | None]]]:
    """Baut die Prüfungen des Health-Endpunkts aus den fertigen Zustandsauskünften von
    `Worker` (fünf Hintergrundarbeiten + Watchdog-Observer) und `Repository` (Datenbank)
    zusammen — rein lesend, keine der aufgerufenen Methoden verändert einen Zustand.

    Bewertet jede Prüfung über deren `state.healthy`-Eigenschaft, nicht durch einen
    eigenen Vergleich gegen einzelne Enum-Werte: `NOT_STARTED` (abgeschaltete
    Paperless-Schleife, Standardfall) und `BUSY` (benutzte, nicht kaputte Datenbank)
    gelten beide als gesund — die Bewertung liegt bewusst am Enum, nicht hier.
    """
    checks: dict[str, dict[str, str | None]] = {}
    healthy = True
    for status in (*worker.background_task_states(), worker.observer_state()):
        checks[status.name] = {"state": status.state.value, "error": status.error}
        healthy = healthy and status.state.healthy
    db_health = repo.check_health()
    checks["database"] = {"state": db_health.state.value, "error": db_health.error}
    healthy = healthy and db_health.state.healthy
    return healthy, checks


@app.get("/healthz")
async def healthz(request: Request) -> JSONResponse:
    """Meldet die tatsächliche Betriebsbereitschaft: je Hintergrundarbeit, Observer und
    Datenbank ein Eintrag in der Antwort. `200` nur wenn alle Prüfungen gesund sind,
    sonst `503` — nicht `500`, weil keine fehlerhafte Anfrage vorliegt, sondern eine
    vorübergehend fehlende Bereitschaft, und weil ein Container-Zustandstest ohnehin nur
    den Statuscode auswertet.

    Rein lesend: startet keine beendete Arbeit neu, stößt keinen Vorgang an und schreibt
    keinen Zustand. Prüft ausdrücklich nicht die Erreichbarkeit fremder Dienste
    (Texterkennung, Paperless, SevDesk) — nur die eigene Betriebsbereitschaft.
    """
    healthy, checks = _health_status(request.app.state.worker, request.app.state.repo)
    return JSONResponse(checks, status_code=200 if healthy else 503)


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


def _page_limit(request: Request) -> int:
    return request.app.state.settings.max_pages_per_document


def _decision_response(result: DecisionResult, document_id: int) -> Response:
    """Übersetzt den Ausgang einer Entscheidung in eine Antwort.

    Eine wirkungslose Entscheidung (der Vorgang steht nicht mehr auf `blocked`) wird als
    Konflikt beantwortet statt still weiterzuleiten — sonst sähe ein Doppelklick aus wie
    ein zweiter Erfolg. Ein unbekannter Vorgang ist davon zu unterscheiden: Das ist kein
    Konflikt, sondern schlicht nicht vorhanden.
    """
    if result == DecisionResult.NOT_FOUND:
        return HTMLResponse("Dokument nicht gefunden", status_code=404)
    if result == DecisionResult.NOT_BLOCKED:
        return HTMLResponse(
            "Der Vorgang ist nicht (mehr) angehalten — die Entscheidung wurde nicht "
            "ausgeführt.",
            status_code=409,
        )
    if result == DecisionResult.DISCARD_FAILED:
        return HTMLResponse(
            "Das Original ließ sich nicht in den Fehlerordner verschieben. Der Vorgang "
            "bleibt angehalten und kann erneut entschieden werden; die Meldung steht im "
            "Verlauf.",
            status_code=500,
        )
    return RedirectResponse(f"/documents/{document_id}", status_code=303)


@app.get("/documents/{document_id}", response_class=HTMLResponse)
async def document_detail(request: Request, document_id: int):
    repo: Repository = request.app.state.repo
    doc = repo.get_document(document_id)
    if doc is None:
        return HTMLResponse("Dokument nicht gefunden", status_code=404)
    events = repo.list_events(document_id)
    return templates.TemplateResponse(
        request,
        "detail.html",
        {"doc": doc, "events": events, "page_limit": _page_limit(request)},
    )


@app.get("/fragment/documents/{document_id}", response_class=HTMLResponse)
async def document_fragment(request: Request, document_id: int):
    repo: Repository = request.app.state.repo
    doc = repo.get_document(document_id)
    if doc is None:
        return HTMLResponse("", status_code=404)
    events = repo.list_events(document_id)
    return templates.TemplateResponse(
        request,
        "partials/detail_body.html",
        {"doc": doc, "events": events, "page_limit": _page_limit(request)},
    )


# Beide Entscheidungen fassen das Dateisystem an (Existenzprüfung bzw. Verschieben in den
# Fehlerordner). Im Eventloop ausgeführt, würde ein geräteübergreifendes Verschieben eines
# grossen Scans — auf dem NAS liegen Eingang und Fehlerordner auf verschiedenen Volumes —
# den gesamten Dienst anhalten: Watcher, Retry-Schleife, SSE-Streams und jede weitere
# Anfrage. Deshalb in einen Thread ausgelagert.
@app.post("/documents/{document_id}/release")
async def document_release(request: Request, document_id: int):
    """Gibt einen angehaltenen Vorgang frei — er läuft trotz überschrittener Grenze."""
    result = await asyncio.to_thread(
        release_document, document_id, request.app.state.repo, request.app.state.settings
    )
    return _decision_response(result, document_id)


@app.post("/documents/{document_id}/discard")
async def document_discard(request: Request, document_id: int):
    """Verwirft einen angehaltenen Vorgang — Original in den Fehlerordner."""
    result = await asyncio.to_thread(
        discard_document, document_id, request.app.state.repo, request.app.state.settings
    )
    return _decision_response(result, document_id)


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


def _clamp_batch_limit(raw: str, maximum: int) -> int:
    """Hält die gewünschte Menge in 1..maximum.

    Ein fehlendes oder unlesbares Feld (leeres Formularfeld — ein
    ``<input type="number">`` ohne ``required`` lässt sich leer abschicken, HTML5
    blockt das nicht) darf **niemals** den Maximallauf auslösen. Der Rückfall ist
    daher die konservative Vorbelegung (höchstens 100, nie über der Obergrenze) statt
    ``maximum`` — sonst löst ein versehentlich geleertes Feld einen Lauf über
    ``RECIPIENT_BATCH_MAX`` Dokumente aus.
    """
    fallback = min(100, maximum)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return fallback
    return max(1, min(value, maximum))


async def _batch_status_context(
    request: Request, page: int = 1, q: str | None = None, missing: bool = False
) -> dict:
    """Kontext der Batch-Toolbar.

    ``missing_total`` zählt Dokumente **ohne gesetzten Empfänger** (Paperless-Feld leer).
    Das ist bewusst nicht dieselbe Menge, die ein Lauf tatsächlich verarbeitet: Der Batch
    überspringt zusätzlich Dokumente, die bereits einen KI-Vorschlag/-Cache-Eintrag haben
    (Vorschlag unter der Konfidenzschwelle oder „unbekannt" setzt das Feld nicht). Ein
    exakter Abgleich bräuchte bei jedem Seitenaufruf einen Vollscan und ist zu teuer — die
    Anzeige benennt daher präzise, was sie zählt, statt eine 1:1-Deckung zu suggerieren.

    ``missing_total_unknown`` unterscheidet „Bestand ist 0" von „Bestand konnte nicht
    ermittelt werden" (z.B. Paperless-Aussetzer): Im Fehlerfall bleibt ``missing_total``
    zwar 0, das Template darf daraus aber **nicht** ableiten, dass nichts zu tun ist, und
    den Start-Button nicht deaktivieren — sonst bleibt der Button nach einem einzigen
    Aussetzer beim Nachladen des Fragments dauerhaft grau, bis die Seite neu geladen wird.

    ``page``/``q``/``missing`` sind die aktuellen Filter der Listenansicht. Die Formulare
    im Partial tragen sie als Hidden-Felder mit, damit der Redirect nach dem Start/Stopp
    eines Laufs auf dieselbe Seite mit denselben Filtern zurückführt statt auf Seite 1
    ohne Filter zu springen. Diese Funktion liefert den Kontext sowohl für den vollen
    Seitenaufbau als auch für die eigenständige Fragment-Route
    ``/fragment/empfaenger/batch-status`` — deshalb müssen die Werte hier und nicht nur
    in ``_recipient_context`` gesetzt werden.
    """
    sync: PaperlessSync = request.app.state.sync
    settings = sync.settings
    missing_total = 0
    missing_total_unknown = False
    # Nur ermitteln, wenn der Wert auch angezeigt wird (batch_status.html blendet den
    # Block sonst ohnehin aus) — spart den Netzwerkaufruf bei jedem Laden von /empfaenger,
    # wenn Paperless zwar verbunden, das KI-Feature aber deaktiviert ist.
    if sync.recipient_enabled and sync.recipient_llm_enabled:
        try:
            missing_total = await sync.count_missing_recipients()
        except Exception:
            log.exception("Bestand ohne Empfänger konnte nicht ermittelt werden")
            missing_total_unknown = True
    return {
        "progress": sync.batch_progress,
        "missing_total": missing_total,
        "missing_total_unknown": missing_total_unknown,
        "default_limit": min(missing_total, 100, settings.recipient_batch_max) or 1,
        "batch_max": settings.recipient_batch_max,
        "feature_llm": sync.recipient_llm_enabled,
        "recipient_enabled": sync.recipient_enabled,
        "page": page,
        "filters": {"q": q or "", "missing": missing},
        "batch_fragment_query": urlencode(
            {"page": page, "q": q or "", "missing": "1" if missing else ""}
        ),
    }


async def _recipient_context(
    request: Request, page: int, q: str | None, missing: bool, *, with_batch_status: bool = True
) -> dict:
    sync: PaperlessSync = request.app.state.sync
    rows, page_obj, field = await sync.list_recipient_documents(
        page=page, search=q, only_missing=missing
    )
    frag = {"q": q or "", "missing": "1" if missing else "", "page": page_obj.page}
    ctx = {
        "rows": rows,
        "options": field.labels if field else [],
        "field_present": field is not None,
        "total_pages": page_obj.total_pages,
        "count": page_obj.count,
        "fragment_query": urlencode(frag),
        "feature_llm": sync.recipient_llm_enabled,
        "recipient_enabled": sync.recipient_enabled,
        # Grundkontext, den BEIDE Templates brauchen — auch das Zeilen-Fragment ohne
        # Batch-Status. Lag früher nur im Batch-Kontext und fehlte dadurch dem Fragment.
        "page": page_obj.page,
        "filters": {"q": q or "", "missing": missing},
    }
    # ``partials/recipient_rows.html`` (das Zeilen-Fragment unter /fragment/empfaenger)
    # nutzt weder missing_total noch progress — der Batch-Kontext würde dort nur einen
    # ungenutzten Paperless-Zählaufruf bezahlen. Nur der volle Seitenaufbau braucht ihn.
    if with_batch_status:
        # page_obj.page statt des rohen page-Parameters: Falls Paperless die Seite klemmt,
        # sollen Hidden-Felder und Pager dieselbe, tatsächlich angezeigte Seite tragen.
        ctx.update(await _batch_status_context(request, page_obj.page, q, missing))
    return ctx


@app.get("/empfaenger", response_class=HTMLResponse)
async def recipients(
    request: Request,
    page: int = Query(1, ge=1),
    q: str | None = Query(None),
    missing: str | None = Query(None),
):
    sync: PaperlessSync = request.app.state.sync
    if not sync.recipient_enabled:
        ctx = await _batch_status_context(request, page, q or None, bool(missing))
        ctx["rows"] = []
        return templates.TemplateResponse(request, "recipients.html", ctx)
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
    ctx = await _recipient_context(request, page, q or None, bool(missing), with_batch_status=False)
    return templates.TemplateResponse(request, "partials/recipient_rows.html", ctx)


@app.get("/fragment/empfaenger/batch-status", response_class=HTMLResponse)
async def recipients_batch_status(
    request: Request,
    page: int = Query(1, ge=1),
    q: str | None = Query(None),
    missing: str | None = Query(None),
):
    ctx = await _batch_status_context(request, page, q or None, bool(missing))
    return templates.TemplateResponse(request, "partials/batch_status.html", ctx)


# Muss VOR /empfaenger/{paperless_id} stehen: Starlette matcht Routen in
# Registrierungsreihenfolge, sonst faengt die parametrisierte Route "suggest-batch"
# als paperless_id ab und die Anfrage scheitert mit 422 (int_parsing).
@app.post("/empfaenger/suggest-batch")
async def recipient_suggest_batch(
    request: Request,
    limit: str = Form(""),
    page: int = Form(1),
    q: str = Form(""),
    missing: str = Form(""),
):
    sync: PaperlessSync = request.app.state.sync
    sync.start_batch(_clamp_batch_limit(limit, sync.settings.recipient_batch_max))
    return RedirectResponse(_recipient_redirect(page, q or None, bool(missing)), status_code=303)


@app.post("/empfaenger/suggest-batch/stop")
async def recipient_suggest_batch_stop(
    request: Request,
    page: int = Form(1),
    q: str = Form(""),
    missing: str = Form(""),
):
    sync: PaperlessSync = request.app.state.sync
    sync.stop_batch()
    return RedirectResponse(_recipient_redirect(page, q or None, bool(missing)), status_code=303)


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
