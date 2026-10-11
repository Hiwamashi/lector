"""Bausteine für die Paperless-Anmeldung: Login-Drosselung, Herkunftsprüfung, Sitzung und
Zugangsprüfung.

Drosselung und Herkunftsprüfung sind reine Logik und isoliert testbar. Sitzung, Zugangsprüfung
und Schutz-Header sind reine ASGI-Middleware (kein ``BaseHTTPMiddleware``), damit der
SSE-Strom ``/events`` nicht gepuffert wird.
"""

from __future__ import annotations

import base64
import ipaddress
import json
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote, urlsplit

from itsdangerous import BadSignature, TimestampSigner
from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .repository import WEB_SESSION_ABSOLUTE, WEB_SESSION_IDLE, WEB_SESSION_TS_FORMAT

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _ip_key(ip: str) -> str:
    """Schlüssel für den IP-Zähler: IPv6 wird auf das /64-Präfix normalisiert (ein Angreifer
    bekommt typischerweise ein ganzes /64), IPv4-gemappte Adressen auf ihre IPv4-Form.
    Ungültige Werte (z. B. ``unbekannt``) bleiben unverändert."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if isinstance(addr, ipaddress.IPv6Address):
        if addr.ipv4_mapped is not None:
            return str(addr.ipv4_mapped)
        return str(ipaddress.ip_network(f"{addr}/64", strict=False).network_address)
    return str(addr)


class LoginThrottle:
    """Gleitfenster-Drosselung für Fehlversuche, je Client-IP und je Nutzername.

    Zustand liegt nur im Speicher; ein Neustart setzt alles zurück. Die Schlüsselzahl ist je
    Zähler auf ``max_keys`` begrenzt: verdrängt wird nach letzter Aktivität (zuletzt genutzte
    Schlüssel bleiben), Schlüssel mit aktiver Sperre werden bevorzugt behalten.

    Wegen der ``await``-Lücke zwischen Prüfung und Ergebnis reservieren ``try_begin`` und
    ``finish`` laufende Versuche: Sie zählen wie Fehlversuche, sonst ließe sich die Sperre
    mit parallelen Anfragen umgehen.
    """

    def __init__(
        self,
        max_failures: int = 5,
        window_seconds: float = 900,
        max_keys: int = 10000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_failures = max_failures
        self._window = window_seconds
        self._max_keys = max_keys
        self._clock = clock
        self._by_ip: OrderedDict[str, deque[float]] = OrderedDict()
        self._by_user: OrderedDict[str, deque[float]] = OrderedDict()
        self._active_ip: dict[str, int] = {}
        self._active_user: dict[str, int] = {}

    @staticmethod
    def _norm(username: str) -> str:
        return username.strip().lower()

    def _count(self, store: OrderedDict[str, deque[float]], key: str) -> int:
        """Verwirft abgelaufene Zeitstempel und liefert die Zahl aktueller Fehlversuche."""
        stamps = store.get(key)
        if stamps is None:
            return 0
        cutoff = self._clock() - self._window
        while stamps and stamps[0] <= cutoff:
            stamps.popleft()
        if not stamps:
            del store[key]
            return 0
        return len(stamps)

    def _add(self, store: OrderedDict[str, deque[float]], key: str) -> None:
        self._count(store, key)  # abgelaufene Einträge verwerfen
        store.setdefault(key, deque()).append(self._clock())
        store.move_to_end(key)  # zuletzt aktiver Schlüssel steht hinten
        while len(store) > self._max_keys:
            # Ältesten (am längsten inaktiven) Schlüssel ohne aktive Sperre verdrängen; sind
            # alle gesperrt, trifft es den ältesten.
            victim = next(iter(store))
            for candidate in list(store):
                if self._count(store, candidate) < self._max_failures:
                    victim = candidate
                    break
            store.pop(victim, None)

    @staticmethod
    def _bump(active: dict[str, int], key: str, delta: int) -> None:
        value = active.get(key, 0) + delta
        if value > 0:
            active[key] = value
        else:
            active.pop(key, None)

    def is_blocked(self, ip: str, username: str) -> bool:
        return (
            self._count(self._by_ip, _ip_key(ip)) >= self._max_failures
            or self._count(self._by_user, self._norm(username)) >= self._max_failures
        )

    def try_begin(self, ip: str, username: str) -> bool:
        """Reserviert einen Versuch, falls erlaubt. Pflicht: danach ``finish`` aufrufen.

        Abgewiesen wird, wenn Fehlversuche plus laufende Versuche je IP oder je Nutzername
        das Limit erreichen, oder wenn für denselben Nutzernamen schon ein Versuch läuft.
        """
        ip_key = _ip_key(ip)
        user_key = self._norm(username)
        if self._active_user.get(user_key, 0) >= 1:
            return False
        if (
            self._count(self._by_ip, ip_key) + self._active_ip.get(ip_key, 0)
            >= self._max_failures
        ):
            return False
        if (
            self._count(self._by_user, user_key) + self._active_user.get(user_key, 0)
            >= self._max_failures
        ):
            return False
        self._bump(self._active_ip, ip_key, 1)
        self._bump(self._active_user, user_key, 1)
        return True

    def finish(self, ip: str, username: str, failed: bool) -> None:
        """Gibt die Reservierung frei; ``failed=True`` zählt zusätzlich als Fehlversuch."""
        self._bump(self._active_ip, _ip_key(ip), -1)
        self._bump(self._active_user, self._norm(username), -1)
        if failed:
            self.record_failure(ip, username)

    def record_failure(self, ip: str, username: str) -> None:
        self._add(self._by_ip, _ip_key(ip))
        self._add(self._by_user, self._norm(username))

    def record_success(self, username: str) -> None:
        """Setzt nur den Nutzernamen-Zähler zurück, nicht den der IP."""
        self._by_user.pop(self._norm(username), None)


def origin_allowed(
    method: str, scheme: str, host: str, origin: str | None, referer: str | None
) -> bool:
    """Herkunftsprüfung für zustandsändernde Anfragen (Schutz vor Schwester-Subdomains).

    ``GET``/``HEAD``/``OPTIONS`` sind immer erlaubt. Sonst muss ``Origin`` (ersatzweise
    Schema+Host des ``Referer``) der eigenen Herkunft entsprechen; fehlen beide, wird abgelehnt.
    """
    if method.upper() in _SAFE_METHODS:
        return True
    own = f"{scheme}://{host}".lower()
    if origin is not None:
        if origin.strip().lower() == "null":
            return False
        return origin.strip().lower() == own
    if referer:
        parts = urlsplit(referer)
        if not parts.scheme or not parts.netloc:
            return False
        return f"{parts.scheme}://{parts.netloc}".lower() == own
    return False


SESSION_COOKIE = "lector_session"
SESSION_MAX_AGE = 30 * 24 * 3600  # 30 Tage, gleitend (bei jeder angemeldeten Antwort neu)
# `last_seen_at` höchstens einmal pro Minute je Sitzung schreiben (SSE/Fragment-Polling).
LAST_SEEN_WRITE_INTERVAL = timedelta(seconds=60)

# Ohne Sitzung zugänglich (design.md D3). `/login` gilt für GET und POST.
_OPEN_PATHS = {"/healthz", "/login"}
_OPEN_PREFIXES = ("/static/",)

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; style-src 'self'; "
        "style-src-attr 'unsafe-inline'; frame-ancestors 'none'; base-uri 'self'; "
        "form-action 'self'"
    ),
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "X-Content-Type-Options": "nosniff",
}


def auth_context(scope: Scope) -> tuple[Any, str] | None:
    """Liefert ``(settings, secret)``, wenn die Anmeldung für diese App aktiv ist.

    Die App wird beim Import erzeugt, die Settings stehen aber erst im Lifespan fest. Die
    Middleware ist deshalb immer eingehängt und entscheidet pro Anfrage am ``app.state``
    (vom Lifespan gesetzt). Fehlt der Zustand (Start fehlgeschlagen) oder gilt
    ``AUTH_MODE=none``, ist sie vollständig durchlässig.
    """
    state = getattr(scope.get("app"), "state", None)
    settings = getattr(state, "settings", None)
    secret = getattr(state, "session_secret", None)
    if settings is None or not secret or settings.auth_mode != "paperless":
        return None
    return settings, secret


def auth_active(request: Request) -> bool:
    return auth_context(request.scope) is not None


def safe_next(value: str | None) -> str:
    """Rücksprungziel: nur Pfade des eigenen Dienstes, sonst die Startseite."""
    if (
        value
        and value.startswith("/")
        and not value.startswith("//")
        and "\\" not in value
        and value.isprintable()
    ):
        return value
    return "/"


def _parse_ts(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, WEB_SESSION_TS_FORMAT).replace(tzinfo=UTC)
    except ValueError:
        return None


def _load_session(request: Request, secret: str, repo: Any) -> dict[str, Any]:
    """Liest das Cookie und gleicht die `sid` mit der Sitzungsliste ab (design.md D10).

    Ohne gültige Signatur, ohne Zeile in ``web_sessions``, nach 30 Tagen Leerlauf oder
    90 Tagen seit der Anmeldung gilt die Anfrage als ohne Sitzung. Gültig: ``{"sid", "user"}``.
    """
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw or repo is None:
        return {}
    try:
        data = TimestampSigner(secret).unsign(raw.encode("utf-8"), max_age=SESSION_MAX_AGE)
        cookie = json.loads(base64.b64decode(data))
    except (BadSignature, ValueError):
        return {}
    sid = cookie.get("sid") if isinstance(cookie, dict) else None
    if not isinstance(sid, str) or not sid:
        return {}
    row = repo.get_web_session(sid)
    if row is None:
        return {}
    username, created_raw, seen_raw = row
    created, seen = _parse_ts(created_raw), _parse_ts(seen_raw)
    now = datetime.now(UTC)
    if (
        created is None
        or seen is None
        or now - seen > WEB_SESSION_IDLE
        or now - created > WEB_SESSION_ABSOLUTE
    ):
        return {}
    if now - seen > LAST_SEEN_WRITE_INTERVAL:
        repo.touch_web_session(sid, now)
    return {"sid": sid, "user": username}


def _cookie_header(value: str, *, secure: bool, max_age: int, expired: bool = False) -> str:
    parts = [f"{SESSION_COOKIE}={value}", "path=/", f"Max-Age={max_age}"]
    if expired:
        parts.append("expires=Thu, 01 Jan 1970 00:00:00 GMT")
    parts += ["httponly", "samesite=strict"]
    if secure:
        parts.append("secure")
    return "; ".join(parts)


class AuthMiddleware:
    """Signierte Sitzung (Cookie) plus Zugangs- und Herkunftsprüfung (design.md D1, D3, D5).

    Eigene Variante statt ``starlette.middleware.sessions.SessionMiddleware``: deren Secret
    muss beim Einhängen feststehen, hier kommt es erst aus dem Lifespan. Format und Verhalten
    sind ähnlich (``TimestampSigner``, base64-JSON, bei jeder angemeldeten Antwort neu
    signiert = gleitende Laufzeit), aber das Cookie trägt nur die ``sid``; gültig ist eine
    Sitzung nur, solange sie in ``web_sessions`` steht (D10). Die Sitzung liegt in
    ``scope["session"]`` (``user`` und ``sid``) und ist über ``request.session`` lesbar.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        ctx = auth_context(scope)
        if ctx is None:
            await self.app(scope, receive, send)
            return
        settings, secret = ctx
        if scope["type"] == "websocket":
            # Es gibt keine WebSockets; deny by default.
            await send({"type": "websocket.close", "code": 1008})
            return

        request = Request(scope)
        path = scope["path"]
        method = scope["method"]

        if not origin_allowed(
            method,
            request.url.scheme,
            request.headers.get("host", ""),
            request.headers.get("origin"),
            request.headers.get("referer"),
        ):
            await Response("", status_code=403)(scope, receive, send)
            return

        repo = getattr(scope["app"].state, "repo", None)
        had_cookie = SESSION_COOKIE in request.cookies
        session = _load_session(request, secret, repo)
        scope["session"] = session

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                if session.get("sid"):
                    # Das Cookie trägt nur die sid; der Nutzername liegt serverseitig.
                    payload = base64.b64encode(json.dumps({"sid": session["sid"]}).encode("utf-8"))
                    signed = TimestampSigner(secret).sign(payload).decode("utf-8")
                    headers.append(
                        "Set-Cookie",
                        _cookie_header(
                            signed,
                            secure=settings.session_cookie_secure,
                            max_age=SESSION_MAX_AGE,
                        ),
                    )
                elif had_cookie:  # ungültiges, abgelaufenes oder abgemeldetes Cookie
                    headers.append(
                        "Set-Cookie",
                        _cookie_header(
                            "null",
                            secure=settings.session_cookie_secure,
                            max_age=0,
                            expired=True,
                        ),
                    )
            await send(message)

        if not session.get("user") and not (
            path in _OPEN_PATHS or path.startswith(_OPEN_PREFIXES)
        ):
            await self._deny(request, path, method)(scope, receive, send_wrapper)
            return

        await self.app(scope, receive, send_wrapper)

    @staticmethod
    def _deny(request: Request, path: str, method: str) -> Response:
        accept = request.headers.get("accept", "").lower()
        if (
            path.startswith("/fragment/")
            or path in ("/events", "/auth/status")
            or "text/html" not in accept
        ):
            return Response("", status_code=401)
        if method in _SAFE_METHODS:
            query = request.url.query
            target = path + (f"?{query}" if query else "")
            return Response(
                "", status_code=303, headers={"Location": f"/login?next={quote(target, safe='')}"}
            )
        # Formular-POST nach abgelaufener Sitzung: nicht wiederholen, bewusst neu auslösen.
        return Response("", status_code=303, headers={"Location": "/login"})


class SecurityHeadersMiddleware:
    """Setzt die Schutz-Header (design.md D7), sofern die Antwort sie nicht schon mitbringt.

    Reine ASGI-Middleware mit ``send``-Wrapper: Der Antwortkörper wird nicht angefasst, ein
    Strom wie ``/events`` bleibt ungepuffert.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS.items():
                    if name not in headers:
                        headers[name] = value
            await send(message)

        await self.app(scope, receive, send_wrapper)
