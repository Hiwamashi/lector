"""App-Schnittstelle (Change ios-app, design.md D1, D4–D8): dieselben Daten und Aktionen wie die
Weboberfläche, maschinenlesbar.

Eine dünne Schicht über dem bestehenden Kern: Anmeldung (`main.authenticate`), Filter
(`main._filters`), Entscheidungen (`decisions`) und Upload (`main.accept_uploads`) teilen sich
ihre Logik mit den HTML-Routen. Der Zugangsschlüssel wird in `auth.AuthMiddleware` geprüft; hier
steht nur, was die Routen selbst tun. Verbindlicher Vertrag: „Anhang: Schnittstellenvertrag v1“
in `openspec/changes/ios-app/design.md`.

`main` wird erst in den Routen importiert: `main` bindet diesen Router ein, ein Import auf
Modulebene wäre zirkulär. Dort liegen auch `obtain_token`, `store_upload` & Co., die Tests über
`app.main` ersetzen.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, PlainSerializer

from .auth import auth_active, sign_app_token
from .decisions import DecisionResult, discard_document, release_document
from .models import DocStatus, Document
from .paperless import LoginResult
from .repository import Repository

API_VERSION = 1
# Obergrenze je Abruf der Vorgangsliste (wie `Repository.list_documents`, Standard 200).
MAX_LIMIT = 200
# Größte Kennung bzw. größter Offset, den SQLite als INTEGER fasst; darüber löst der
# Treiber einen OverflowError aus.
MAX_ID = 2**63 - 1

log = logging.getLogger("lector.api")

router = APIRouter()


# ---- Fehlerformat (D5) ------------------------------------------------------------------


class ApiError(Exception):
    """Fehler der Schnittstelle: HTTP-Status, fester Code (D5) und deutsche Meldung."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status_code)


async def api_error_handler(request: Request, exc: ApiError) -> Response:
    return error_response(exc.status_code, exc.code, exc.message)


async def api_validation_handler(request: Request, exc: RequestValidationError) -> Response:
    """Ersetzt FastAPIs Validierungsantwort unter `/api/` durch `invalid_request` (422).
    Alle anderen Pfade behalten die Standardantwort."""
    if request.url.path.startswith("/api/"):
        return error_response(
            422, "invalid_request", "Die Anfrage ist ungültig. Bitte Angaben prüfen."
        )
    return await request_validation_exception_handler(request, exc)


async def api_internal_error_handler(request: Request, exc: Exception) -> Response:
    """Unerwartete Fehler unter `/api/` als JSON-500 `internal_error` (und protokolliert);
    andere Pfade behalten die Standardantwort."""
    if request.url.path.startswith("/api/"):
        log.error("Unerwarteter Fehler in %s", request.url.path, exc_info=exc)
        return error_response(
            500, "internal_error", "Interner Fehler. Bitte später erneut versuchen."
        )
    return Response("Internal Server Error", status_code=500, media_type="text/plain")


# ---- Maskierung von Pfaden in Freitexten ------------------------------------------------

_TRAILING = ".,;:)]}"


def make_path_masker(settings: Any) -> Callable[[str | None, Document | None], str | None]:
    """Liefert eine Funktion, die in Freitexten (Fehlermeldung, Verlaufsmeldung) Pfade des NAS
    durch den bloßen Dateinamen ersetzt. Nur für die Ausgabe der Schnittstelle: Die gespeicherten
    Texte und die Weboberfläche bleiben unverändert. Ersetzt werden `source_path`/`output_path`
    des Vorgangs (auch mit Leerzeichen im Namen) und jeder absolute Pfad unter den
    konfigurierten Ordnern (Eingang, consume, processed, error, Datenbankordner)."""
    roots = {
        str(d).rstrip("/")
        for d in (
            settings.watch_dir,
            settings.consume_dir,
            settings.processed_dir,
            settings.error_dir,
            Path(settings.db_path).parent,
        )
    }
    roots.discard("")
    pattern = None
    if roots:
        alternatives = "|".join(re.escape(r) for r in sorted(roots, key=len, reverse=True))
        pattern = re.compile(rf"(?:{alternatives})(?=[/\s'\"<>.,;:)\]}}]|$)(?:/([^\s'\"<>]*))?")

    def _replace(match: re.Match[str]) -> str:
        rest = match.group(1)
        whole = match.group(0)
        if rest is None:
            return Path(whole).name
        body = rest.rstrip(_TRAILING)
        return Path(body).name + rest[len(body) :]

    def mask(text: str | None, doc: Document | None = None) -> str | None:
        if not text:
            return text
        if doc is not None:
            for path in sorted(
                {p for p in (doc.source_path, doc.output_path) if p}, key=len, reverse=True
            ):
                text = text.replace(path, Path(path).name)
        return pattern.sub(_replace, text) if pattern else text

    return mask


# ---- Ausgabemodelle (D6) ----------------------------------------------------------------


def _iso_z(value: datetime) -> str:
    """Zeitpunkt als ISO 8601 in UTC mit ``Z``. Die Datenbank hält UTC; ein naiver Wert gilt
    als UTC."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


UtcTime = Annotated[datetime, PlainSerializer(_iso_z, return_type=str)]


class DocumentOut(BaseModel):
    """Vorgang. Bewusst ohne `source_path`/`output_path`: Für die App wertlos, und sie
    verrieten die Verzeichnisstruktur des NAS."""

    id: int
    original_filename: str
    status: str
    doc_type: str | None
    total_pages: int | None
    processed_pages: int
    attempt_count: int
    next_retry_at: UtcTime | None
    error_message: str | None
    page_limit_approved: bool
    created_at: UtcTime | None
    started_at: UtcTime | None
    finished_at: UtcTime | None

    @classmethod
    def from_document(cls, doc: Document, mask: Callable) -> DocumentOut:
        return cls(
            id=doc.id,
            original_filename=doc.original_filename,
            status=str(doc.status.value),
            doc_type=str(doc.doc_type.value) if doc.doc_type is not None else None,
            total_pages=doc.total_pages,
            processed_pages=doc.processed_pages,
            attempt_count=doc.attempt_count,
            next_retry_at=doc.next_retry_at,
            error_message=mask(doc.error_message, doc),
            page_limit_approved=doc.page_limit_approved,
            created_at=doc.created_at,
            started_at=doc.started_at,
            finished_at=doc.finished_at,
        )


class EventOut(BaseModel):
    id: int
    timestamp: UtcTime
    event_type: str
    message: str | None

    @classmethod
    def from_row(cls, row: dict[str, Any], mask: Callable, doc: Document) -> EventOut:
        return cls(
            id=row["id"],
            timestamp=row["timestamp"],
            event_type=row["event_type"],
            message=mask(row["message"], doc),
        )


class DocumentListOut(BaseModel):
    documents: list[DocumentOut]
    # Zahl der Vorgänge je Zustand über den gesamten Bestand, unabhängig vom Filter; jeder
    # Zustand ist enthalten, fehlende mit 0.
    counts: dict[str, int]
    limit: int
    offset: int


class DocumentDetailOut(BaseModel):
    document: DocumentOut
    events: list[EventOut]
    page_limit: int
    retry_max: int


class DocumentResultOut(BaseModel):
    document: DocumentOut


class InfoOut(BaseModel):
    service: str
    api_version: int
    auth_mode: str


class LoginIn(BaseModel):
    username: str
    password: str
    code: str | None = None


class LoginOut(BaseModel):
    token: str
    username: str


class UploadResultOut(BaseModel):
    filename: str
    accepted: bool
    reason: str | None
    stored_as: str | None


class UploadOut(BaseModel):
    results: list[UploadResultOut]


# ---- Voraussetzungen der Routen ---------------------------------------------------------


async def _require_auth_mode(request: Request) -> None:
    """Anmeldung und Abmeldung gibt es nur im Modus `paperless`; sonst 404 (wie
    `main._auth_routes_absent`). Als Voraussetzung statt im Rumpf, damit sie vor der
    Prüfung des Körpers greift."""
    if not auth_active(request):
        raise ApiError(404, "not_found", "Diese Funktion gibt es im Modus ohne Anmeldung nicht.")


async def _require_json(request: Request) -> None:
    """Die Anmeldung verlangt `Content-Type: application/json` (D3): Ein HTML-Formular kann
    diesen Typ nicht ohne Preflight senden, eine untergeschobene Anmeldung ist so
    ausgeschlossen."""
    media_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if media_type != "application/json":
        raise ApiError(
            415, "invalid_request", "Die Anfrage muss den Inhaltstyp application/json haben."
        )


def _repo(request: Request) -> Repository:
    return request.app.state.repo


# ---- Selbstauskunft ---------------------------------------------------------------------


@router.get("/api/info", response_model=InfoOut)
async def info(request: Request) -> InfoOut:
    """Selbstauskunft ohne Anmeldung. Bewusst nicht unter `v1`: Nur so kann die App die
    Version erfragen, bevor sie weiß, welche sie sprechen muss. Sonst keine Angaben zum
    Betrieb."""
    return InfoOut(
        service="lector",
        api_version=API_VERSION,
        auth_mode=request.app.state.settings.auth_mode,
    )


# ---- Anmeldung (D4) ---------------------------------------------------------------------


def _invalid_credentials() -> ApiError:
    # Einheitliche Meldung: Es darf nicht erkennbar werden, welche Angabe falsch war.
    return ApiError(401, "invalid_credentials", "Anmeldung fehlgeschlagen. Bitte Angaben prüfen.")


@router.post(
    "/api/v1/login",
    response_model=LoginOut,
    dependencies=[Depends(_require_auth_mode), Depends(_require_json)],
)
async def login(request: Request, body: LoginIn):
    from . import main

    username = body.username.strip()
    if not username or not body.password:
        # Wie auf der Anmeldeseite: nicht gezählt und ohne Rückfrage bei Paperless.
        raise _invalid_credentials()
    result, sid = await main.authenticate(request, username, body.password, body.code)
    if result is main.THROTTLED:
        raise ApiError(
            429, "throttled", "Zu viele Fehlversuche. Bitte in einigen Minuten erneut versuchen."
        )
    if result is LoginResult.OK and sid:
        token = sign_app_token(request.app.state.session_secret, sid)
        return LoginOut(token=token, username=username)
    if result is LoginResult.MFA_REQUIRED:
        raise ApiError(401, "mfa_required", "Bitte den MFA-Code eingeben.")
    if result is LoginResult.UNAVAILABLE:
        raise ApiError(
            503,
            "paperless_unavailable",
            "Paperless ist nicht erreichbar. Bitte später erneut versuchen.",
        )
    raise _invalid_credentials()


@router.post("/api/v1/logout", status_code=204, dependencies=[Depends(_require_auth_mode)])
async def logout(request: Request) -> Response:
    """Beendet genau die Sitzung dieses Schlüssels; andere Sitzungen derselben Person (etwa im
    Browser) bleiben bestehen."""
    sid = request.session.get("sid")
    if sid:
        _repo(request).delete_web_session(sid)
    request.session.clear()
    return Response(status_code=204)


# ---- Vorgänge ---------------------------------------------------------------------------


@router.get("/api/v1/documents", response_model=DocumentListOut)
async def list_documents(
    request: Request,
    status: str | None = None,
    q: str | None = None,
    period: str | None = None,
    limit: Annotated[int, Query()] = MAX_LIMIT,
    offset: Annotated[int, Query()] = 0,
) -> DocumentListOut:
    """Liste der Vorgänge, neueste zuerst. Filter wie in der Weboberfläche (`main._filters`):
    ein unbekannter Zustand gilt als „kein Filter“. `limit` wird auf 1 bis 200 begrenzt
    (nicht abgelehnt), `offset` auf Werte ab 0; die Antwort nennt die tatsächlich
    verwendeten Werte. Die Zähler gelten ungefiltert für den ganzen Bestand."""
    from . import main

    repo = _repo(request)
    limit = max(1, min(limit, MAX_LIMIT))
    offset = max(0, min(offset, MAX_ID))
    mask = make_path_masker(request.app.state.settings)
    status_enum, search, since = main._filters(status, q, period)
    documents = repo.list_documents(
        status=status_enum, search=search, since=since, limit=limit, offset=offset
    )
    stored = repo.status_counts()
    return DocumentListOut(
        documents=[DocumentOut.from_document(d, mask) for d in documents],
        counts={s.value: stored.get(s.value, 0) for s in DocStatus},
        limit=limit,
        offset=offset,
    )


def _not_found() -> ApiError:
    return ApiError(404, "not_found", "Vorgang nicht gefunden.")


def _checked_id(document_id: int) -> int:
    """Eine Kennung außerhalb von 1..2**63-1 gibt es nie: 404, ohne die Datenbank zu fragen
    (SQLite würde mit einem OverflowError abbrechen)."""
    if not 1 <= document_id <= MAX_ID:
        raise _not_found()
    return document_id


@router.get("/api/v1/documents/{document_id}", response_model=DocumentDetailOut)
async def document_detail(request: Request, document_id: int) -> DocumentDetailOut:
    repo = _repo(request)
    doc = repo.get_document(_checked_id(document_id))
    if doc is None:
        raise _not_found()
    settings = request.app.state.settings
    mask = make_path_masker(settings)
    return DocumentDetailOut(
        document=DocumentOut.from_document(doc, mask),
        events=[EventOut.from_row(e, mask, doc) for e in repo.list_events(document_id)],
        page_limit=settings.max_pages_per_document,
        retry_max=settings.retry_max,
    )


async def _decide(request: Request, document_id: int, decide) -> DocumentResultOut:
    """Führt eine Entscheidung aus (D8) und antwortet mit dem frisch gelesenen Vorgang.

    Wie in der Weboberfläche über `asyncio.to_thread`: Beide Entscheidungen fassen das
    Dateisystem an und dürfen den Eventloop nicht anhalten."""
    repo = _repo(request)
    _checked_id(document_id)
    result = await asyncio.to_thread(decide, document_id, repo, request.app.state.settings)
    if result == DecisionResult.NOT_FOUND:
        raise _not_found()
    if result == DecisionResult.NOT_BLOCKED:
        raise ApiError(
            409,
            "not_blocked",
            "Der Vorgang ist nicht (mehr) angehalten. Die Entscheidung wurde nicht ausgeführt.",
        )
    if result == DecisionResult.DISCARD_FAILED:
        raise ApiError(
            500,
            "discard_failed",
            "Das Original ließ sich nicht in den Fehlerordner verschieben. Der Vorgang bleibt "
            "angehalten und kann erneut entschieden werden.",
        )
    # RELEASED, DISCARDED und SOURCE_MISSING (Freigabe ohne Original: der Vorgang steht dann
    # auf `failed`, wie in der Weboberfläche) enden mit dem aktuellen Vorgang.
    doc = repo.get_document(document_id)
    if doc is None:
        raise _not_found()
    return DocumentResultOut(
        document=DocumentOut.from_document(doc, make_path_masker(request.app.state.settings))
    )


@router.post("/api/v1/documents/{document_id}/release", response_model=DocumentResultOut)
async def release(request: Request, document_id: int) -> DocumentResultOut:
    return await _decide(request, document_id, release_document)


@router.post("/api/v1/documents/{document_id}/discard", response_model=DocumentResultOut)
async def discard(request: Request, document_id: int) -> DocumentResultOut:
    return await _decide(request, document_id, discard_document)


# ---- Upload (D7) ------------------------------------------------------------------------


@router.post("/api/v1/upload", response_model=UploadOut)
async def upload(
    request: Request, files: Annotated[list[UploadFile] | None, File()] = None
) -> UploadOut:
    """Übergabe von Dateien in den Eingangsordner, Rückmeldung je Datei. Status 200 auch dann,
    wenn einzelne Dateien abgewiesen werden; ohne Datei 400 `no_files`. Die Rückmeldung
    erfolgt, ohne Aufnahme oder Verarbeitung abzuwarten."""
    from . import main

    outcomes = await main.accept_uploads(files, request.app.state.settings)
    if not outcomes:
        raise ApiError(400, "no_files", "Es wurde keine Datei übergeben.")
    return UploadOut(
        results=[
            UploadResultOut(
                filename=o.filename, accepted=o.accepted, reason=o.reason, stored_as=o.stored_as
            )
            for o in outcomes
        ]
    )
