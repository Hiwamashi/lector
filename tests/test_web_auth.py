"""Web-Zugang (Change paperless-anmeldung): Sitzung, Zugangsprüfung, Anmeldeseite,
Herkunftsprüfung, Schutz-Header, entfernte Schnittstellenbeschreibung."""

from __future__ import annotations

import asyncio
import base64
import importlib
import json
import logging
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner
from test_web import _setup_test_environment

import app.config
import app.main
from app.paperless import LoginResult
from app.repository import Repository

PASSWORT = "geheimes-passwort-4711"
HTML = {"Accept": "text/html"}
EIGENE_HERKUNFT = {"Origin": "http://testserver"}


@contextmanager
def _make_client(tmp_path, monkeypatch, *, mode="paperless", secret="geheimnis-a", secure=False):
    """Startet die App frisch (Reload, wie die Fixture `client` in test_web.py) und liefert
    ``(TestClient, app, fake)``. ``fake.result`` steuert ``obtain_token``, ``fake.calls``
    protokolliert die Aufrufe."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    _setup_test_environment(monkeypatch, tmp_path)
    monkeypatch.setenv("AUTH_MODE", mode)
    monkeypatch.setenv("PAPERLESS_URL", "http://paperless.invalid")
    monkeypatch.setenv("LECTOR_SECRET_KEY", secret)
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "true" if secure else "false")
    app.config.get_settings.cache_clear()
    importlib.reload(app.main)

    fake = SimpleNamespace(result=LoginResult.OK, calls=[])

    async def fake_obtain_token(base_url, username, password, code=None, **kwargs):
        fake.calls.append((base_url, username, password, code))
        return fake.result

    monkeypatch.setattr(app.main, "obtain_token", fake_obtain_token)
    with TestClient(app.main.app) as c:
        yield c, app.main.app, fake


def _login(c, username="sascha", **extra):
    return c.post(
        "/login",
        data={"username": username, "password": PASSWORT, **extra},
        headers=EIGENE_HERKUNFT,
        follow_redirects=False,
    )


@pytest.fixture
def auth_client(tmp_path, monkeypatch):
    """AUTH_MODE=paperless, angemeldet als `sascha` (obtain_token gemockt)."""
    with _make_client(tmp_path, monkeypatch) as (c, application, fake):
        assert _login(c).status_code == 303
        fake.calls.clear()
        yield c, application, fake


@pytest.fixture
def anon_client(tmp_path, monkeypatch):
    """AUTH_MODE=paperless, nicht angemeldet."""
    with _make_client(tmp_path, monkeypatch) as triple:
        yield triple


@pytest.fixture
def plain_client(tmp_path, monkeypatch):
    """AUTH_MODE=none (Standard)."""
    with _make_client(tmp_path, monkeypatch, mode="none") as triple:
        yield triple


# --- Zugangsprüfung ----------------------------------------------------------------------


def test_offene_pfade_ohne_sitzung(anon_client):
    c, _, _ = anon_client
    assert c.get("/healthz").status_code == 200
    assert c.get("/static/app.css").status_code == 200
    assert c.get("/login").status_code == 200


def test_seite_ohne_sitzung_leitet_mit_next_zur_anmeldung(anon_client):
    c, _, _ = anon_client
    resp = c.get("/invoices?status=done", headers=HTML, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login?next=%2Finvoices%3Fstatus%3Ddone"


def test_fragment_und_events_ohne_sitzung_401(anon_client):
    c, _, _ = anon_client
    for path in ("/fragment/history", "/events", "/auth/status"):
        # Auch mit Browser-Accept: diese Pfade antworten immer 401 ohne Inhalt.
        resp = c.get(path, headers=HTML, follow_redirects=False)
        assert resp.status_code == 401, path
        assert resp.content == b""


def test_nicht_html_anfrage_ohne_sitzung_401(anon_client):
    c, _, _ = anon_client
    resp = c.get("/", headers={"Accept": "application/json"}, follow_redirects=False)
    assert resp.status_code == 401


def test_post_aktion_ohne_sitzung_wird_nicht_ausgefuehrt(anon_client, tmp_path):
    c, _, _ = anon_client
    resp = c.post(
        "/upload",
        files=[("files", ("scan.pdf", b"%PDF-1.4 x", "application/pdf"))],
        headers={**HTML, **EIGENE_HERKUNFT},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"
    assert list((tmp_path / "scan-in").iterdir()) == []


def test_auth_status_angemeldet_204(auth_client):
    c, _, _ = auth_client
    assert c.get("/auth/status").status_code == 204


def test_seite_mit_sitzung_erreichbar(auth_client):
    c, _, _ = auth_client
    assert c.get("/", headers=HTML).status_code == 200
    assert c.get("/fragment/history").status_code == 200


# --- Herkunftsprüfung --------------------------------------------------------------------


def test_post_mit_fremder_herkunft_403(auth_client):
    c, _, _ = auth_client
    resp = c.post(
        "/logout",
        headers={"Origin": "https://paperless.nerd-wg.eu"},
        follow_redirects=False,
    )
    assert resp.status_code == 403
    # Die Sitzung besteht weiter.
    assert c.get("/auth/status").status_code == 204


def test_post_ohne_origin_und_referer_403(auth_client):
    c, _, _ = auth_client
    assert c.post("/logout", follow_redirects=False).status_code == 403


def test_login_mit_fremder_herkunft_403(anon_client):
    c, _, fake = anon_client
    resp = c.post(
        "/login",
        data={"username": "sascha", "password": PASSWORT},
        headers={"Origin": "https://paperless.nerd-wg.eu"},
        follow_redirects=False,
    )
    assert resp.status_code == 403
    assert fake.calls == []


def test_post_mit_eigener_herkunft_funktioniert(auth_client, tmp_path):
    c, _, _ = auth_client
    resp = c.post(
        "/upload",
        files=[("files", ("scan.pdf", b"%PDF-1.4 x", "application/pdf"))],
        headers=EIGENE_HERKUNFT,
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert [p.name for p in (tmp_path / "scan-in").iterdir()] == ["scan.pdf"]


def test_post_mit_eigenem_referer_funktioniert(auth_client):
    c, _, _ = auth_client
    resp = c.post(
        "/logout", headers={"Referer": "http://testserver/invoices"}, follow_redirects=False
    )
    assert resp.status_code == 303


# --- Anmeldung ---------------------------------------------------------------------------


def test_login_erfolg_setzt_sitzung_und_leitet_zu_next(anon_client):
    c, _, fake = anon_client
    resp = _login(c, next="/invoices?page=2")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/invoices?page=2"
    assert fake.calls == [("http://paperless.invalid", "sascha", PASSWORT, None)]
    assert c.get("/auth/status").status_code == 204


def test_login_ohne_next_landet_auf_startseite(anon_client):
    c, _, _ = anon_client
    assert _login(c).headers["location"] == "/"


@pytest.mark.parametrize(
    "next_value",
    [
        "//evil.example",
        "https://evil.example",
        "/\\evil.example",
        "evil",
        "/a\nb",
        # Rücksprung auf die Anmeldung selbst würde next endlos verschachteln.
        "/login",
        "/login?next=%2F",
        "/logout",
    ],
)
def test_login_fremdes_next_wird_ersetzt(anon_client, next_value):
    c, _, _ = anon_client
    assert _login(c, next=next_value).headers["location"] == "/"


def test_login_reicht_mfa_code_weiter(anon_client):
    c, _, fake = anon_client
    _login(c, code=" 123456 ")
    assert fake.calls[0][3] == "123456"


def test_login_mfa_erforderlich(anon_client):
    c, _, fake = anon_client
    fake.result = LoginResult.MFA_REQUIRED
    resp = _login(c, next="/invoices")
    assert resp.status_code == 200
    assert "MFA-Code eingeben" in resp.text
    assert 'value="sascha"' in resp.text  # Nutzername vorbefüllt
    assert 'value="/invoices"' in resp.text  # next bleibt erhalten
    assert PASSWORT not in resp.text
    assert c.get("/auth/status").status_code == 401


def test_login_falsche_daten_einheitliche_meldung(anon_client, caplog):
    c, _, fake = anon_client
    fake.result = LoginResult.INVALID
    with caplog.at_level(logging.INFO):
        resp = _login(c)
    assert resp.status_code == 200
    assert "Anmeldung fehlgeschlagen" in resp.text
    assert PASSWORT not in resp.text
    assert c.get("/auth/status").status_code == 401
    warnungen = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("testclient" in m and "sascha" in m for m in warnungen)
    assert PASSWORT not in caplog.text


def test_login_paperless_nicht_erreichbar(anon_client):
    c, _, fake = anon_client
    fake.result = LoginResult.UNAVAILABLE
    resp = _login(c)
    assert resp.status_code == 200
    assert "Paperless ist nicht erreichbar" in resp.text
    assert "Anmeldung fehlgeschlagen" not in resp.text


def test_sperre_nach_fuenf_fehlversuchen_ohne_paperless(anon_client, caplog):
    c, _, fake = anon_client
    fake.result = LoginResult.INVALID
    for _ in range(5):
        assert "Anmeldung fehlgeschlagen" in _login(c).text
    assert len(fake.calls) == 5

    fake.result = LoginResult.OK  # selbst gültige Angaben werden jetzt abgewiesen
    with caplog.at_level(logging.INFO):
        resp = _login(c)
    assert "Zu viele Fehlversuche" in resp.text
    assert len(fake.calls) == 5
    assert c.get("/auth/status").status_code == 401
    assert PASSWORT not in caplog.text
    assert any("gebremst" in r.getMessage() for r in caplog.records)


def test_unavailable_zaehlt_nicht_als_fehlversuch(anon_client):
    c, _, fake = anon_client
    fake.result = LoginResult.UNAVAILABLE
    for _ in range(7):
        assert "Paperless ist nicht erreichbar" in _login(c).text
    assert len(fake.calls) == 7


def test_mfa_required_zaehlt_als_fehlversuch(anon_client):
    """Sonst wäre die MFA-Aufforderung ein kostenloses Passwort-Orakel."""
    c, _, fake = anon_client
    fake.result = LoginResult.MFA_REQUIRED
    for _ in range(5):
        resp = _login(c)
        assert "MFA-Code eingeben" in resp.text  # Aufforderung bleibt sichtbar
    assert len(fake.calls) == 5
    assert "Zu viele Fehlversuche" in _login(c).text
    assert len(fake.calls) == 5


def _gleichzeitig(application, fake, namen, *, ergebnis=LoginResult.INVALID):
    """Schickt alle Anmeldungen gleichzeitig; ``obtain_token`` bleibt kurz offen, damit sich
    die Versuche überlappen."""
    import httpx

    async def langsam(base_url, username, password, code=None, **kwargs):
        fake.calls.append((base_url, username, password, code))
        await asyncio.sleep(0.05)
        return ergebnis

    async def run():
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            return await asyncio.gather(
                *(
                    ac.post(
                        "/login",
                        data={"username": n, "password": PASSWORT},
                        headers=EIGENE_HERKUNFT,
                    )
                    for n in namen
                )
            )

    return langsam, run


def test_parallele_anmeldungen_umgehen_die_sperre_nicht(anon_client, monkeypatch):
    c, application, fake = anon_client
    langsam, run = _gleichzeitig(application, fake, [f"nutzer{i}" for i in range(30)])
    monkeypatch.setattr(app.main, "obtain_token", langsam)
    antworten = asyncio.run(run())
    assert len(fake.calls) <= 5  # max_failures, trotz 30 gleichzeitiger Versuche
    assert sum("Zu viele Fehlversuche" in r.text for r in antworten) >= 25


def test_ein_gleichzeitiger_versuch_je_nutzername(anon_client, monkeypatch):
    c, application, fake = anon_client
    langsam, run = _gleichzeitig(application, fake, ["Anna"] * 10)
    monkeypatch.setattr(app.main, "obtain_token", langsam)
    antworten = asyncio.run(run())
    assert len(fake.calls) == 1
    assert sum("Zu viele Fehlversuche" in r.text for r in antworten) == 9


def test_reservierung_wird_bei_ausnahme_freigegeben(anon_client, monkeypatch):
    c, application, fake = anon_client

    async def kaputt(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(app.main, "obtain_token", kaputt)
    with pytest.raises(RuntimeError):
        _login(c)
    monkeypatch.setattr(app.main, "obtain_token", lambda *a, **k: asyncio.sleep(0, LoginResult.OK))
    assert _login(c).status_code == 303  # Nutzer ist nicht dauerhaft "in Arbeit"


def test_leere_angaben_fragen_paperless_nicht(anon_client):
    c, _, fake = anon_client
    resp = c.post(
        "/login", data={"username": "", "password": ""}, headers=EIGENE_HERKUNFT
    )
    assert resp.status_code == 200
    assert fake.calls == []


def test_login_seite_mit_sitzung_leitet_zur_startseite(auth_client):
    c, _, _ = auth_client
    resp = c.get("/login", headers=HTML, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"


def test_login_seite_gibt_next_ins_formular_und_ignoriert_fremdes(anon_client):
    c, _, _ = anon_client
    assert 'name="next" value="/invoices"' in c.get("/login?next=/invoices").text
    assert 'name="next" value=""' in c.get("/login?next=//evil.example").text


def test_login_seite_ohne_navigation_und_ohne_inline_code(anon_client):
    c, _, _ = anon_client
    html = c.get("/login").text
    assert "topnav" not in html
    assert "<script>" not in html and ' style="' not in html
    assert 'autocomplete="username"' in html
    assert 'autocomplete="current-password"' in html
    assert 'autocomplete="one-time-code"' in html and 'inputmode="numeric"' in html
    assert "optional" in html
    assert "Abmelden" not in html


def test_login_seite_laedt_kein_app_js(anon_client):
    """app.js öffnet /events; ohne Sitzung führte dessen 401 auf der Anmeldeseite zu einer
    Umleitungsschleife mit endlos verschachteltem next (431 Request Header Fields Too Large)."""
    c, _, _ = anon_client
    assert "app.js" not in c.get("/login").text
    _login(c)
    assert "app.js" in c.get("/").text


def test_abmelden(auth_client):
    c, _, _ = auth_client
    resp = c.post("/logout", headers=EIGENE_HERKUNFT, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"
    cookie = resp.headers["set-cookie"].lower()
    assert "max-age=0" in cookie
    assert c.get("/auth/status").status_code == 401
    assert c.get("/", headers=HTML, follow_redirects=False).status_code == 303


# --- Sitzung -----------------------------------------------------------------------------


def _session_cookies(resp):
    return [h for h in resp.headers.get_list("set-cookie") if h.startswith("lector_session=")]


def test_angemeldete_antwort_erneuert_cookie_und_hat_attribute(auth_client):
    c, _, _ = auth_client
    resp = c.get("/", headers=HTML)
    (cookie,) = _session_cookies(resp)
    lowered = cookie.lower()
    assert "max-age=2592000" in lowered  # 30 Tage
    assert "httponly" in lowered
    assert "samesite=strict" in lowered
    assert "path=/" in lowered
    assert "secure" not in lowered  # SESSION_COOKIE_SECURE aus


def test_ohne_sitzung_kein_cookie(anon_client):
    c, _, _ = anon_client
    assert _session_cookies(c.get("/login")) == []
    assert _session_cookies(c.get("/", headers=HTML, follow_redirects=False)) == []


def test_manipuliertes_cookie_ist_keine_sitzung(auth_client):
    c, _, _ = auth_client
    gueltig = c.cookies.get("lector_session")
    assert gueltig
    for kaputt in (gueltig[:-3] + "xyz", "selbstgebaut", gueltig + "x"):
        c.cookies.clear()
        c.cookies.set("lector_session", kaputt)
        assert c.get("/auth/status").status_code == 401


def test_anderes_geheimnis_macht_cookie_ungueltig(tmp_path, monkeypatch):
    with _make_client(tmp_path / "a", monkeypatch, secret="geheimnis-a") as (c, _, _):
        _login(c)
        cookie = c.cookies.get("lector_session")
        assert c.get("/auth/status").status_code == 204
    # Die Sitzungsliste liegt in der DB: gleiche Daten, nur das Geheimnis unterscheidet sich.
    with _make_client(tmp_path / "a", monkeypatch, secret="geheimnis-a") as (c, _, _):
        c.cookies.set("lector_session", cookie)
        assert c.get("/auth/status").status_code == 204  # gleiches Geheimnis = gültig
    with _make_client(tmp_path / "a", monkeypatch, secret="geheimnis-b") as (c, _, _):
        c.cookies.set("lector_session", cookie)
        assert c.get("/auth/status").status_code == 401


def test_secure_cookie_nur_mit_schalter(tmp_path, monkeypatch):
    with _make_client(tmp_path, monkeypatch, secure=True) as (c, _, fake):
        resp = _login(c)
        (cookie,) = _session_cookies(resp)
        assert "secure" in cookie.lower()
        assert "httponly" in cookie.lower() and "samesite=strict" in cookie.lower()


def test_hinweis_bei_secure_cookie_ueber_http(tmp_path, monkeypatch):
    with _make_client(tmp_path, monkeypatch, secure=True) as (c, _, _):
        assert "http</code> geöffnet" in c.get("/login").text
    with _make_client(tmp_path / "x", monkeypatch, secure=False) as (c, _, _):
        assert "http</code> geöffnet" not in c.get("/login").text


# --- Topbar ------------------------------------------------------------------------------


def test_topbar_zeigt_nutzer_und_abmelden_im_modus_paperless(auth_client):
    c, _, _ = auth_client
    html = c.get("/", headers=HTML).text
    assert "sascha" in html
    assert 'action="/logout"' in html and "Abmelden" in html


def test_topbar_ohne_abmelden_im_modus_none(plain_client):
    c, _, _ = plain_client
    html = c.get("/").text
    assert "Abmelden" not in html and "/logout" not in html


# --- Modus none bleibt unverändert -------------------------------------------------------


def test_modus_none_ohne_sitzung_cookie_oder_schluesseldatei(plain_client, tmp_path):
    c, _, _ = plain_client
    resp = c.get("/")
    assert resp.status_code == 200
    assert "set-cookie" not in resp.headers
    assert not (tmp_path / "data" / "session.key").exists()


def test_modus_none_keine_herkunftspruefung(plain_client):
    c, _, _ = plain_client
    resp = c.post("/upload", files=[], follow_redirects=False)
    assert resp.status_code != 403
    assert c.get("/fragment/history").status_code == 200


@pytest.mark.parametrize("path", ["/login", "/auth/status"])
def test_modus_none_auth_pfade_nicht_vorhanden(plain_client, path):
    c, _, _ = plain_client
    assert c.get(path).status_code == 404


def test_modus_none_logout_nicht_vorhanden(plain_client):
    c, _, _ = plain_client
    assert c.post("/logout", follow_redirects=False).status_code == 404


# --- Schnittstellenbeschreibung ----------------------------------------------------------


@pytest.mark.parametrize("mode", ["none", "paperless"])
@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_keine_schnittstellenbeschreibung(tmp_path, monkeypatch, mode, path):
    with _make_client(tmp_path, monkeypatch, mode=mode) as (c, _, _):
        if mode == "paperless":
            _login(c)
        assert c.get(path, headers=HTML, follow_redirects=False).status_code == 404


# --- Schutz-Header -----------------------------------------------------------------------


def _assert_standard_header(resp):
    csp = resp.headers["content-security-policy"]
    assert csp.startswith("default-src 'self'")
    assert "frame-ancestors 'none'" in csp and "style-src-attr 'unsafe-inline'" in csp
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["referrer-policy"] == "same-origin"
    assert resp.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize("path", ["/", "/fragment/history", "/healthz", "/static/app.css"])
def test_schutz_header_modus_none(plain_client, path):
    c, _, _ = plain_client
    _assert_standard_header(c.get(path))


def test_schutz_header_auch_auf_zugangsantworten(anon_client):
    c, _, _ = anon_client
    _assert_standard_header(c.get("/", headers=HTML, follow_redirects=False))  # 303
    _assert_standard_header(c.get("/events"))  # 401
    _assert_standard_header(c.post("/logout", follow_redirects=False))  # 403


def test_schutz_header_auf_events_ohne_puffern(plain_client):
    """/events streamt endlos; ein TestClient-Aufruf würde hängen. Deshalb die App direkt
    per ASGI ansprechen und nach dem Antwortkopf abbrechen."""
    _, application, _ = plain_client

    class Fertig(Exception):
        pass

    gesehen: dict = {}

    async def run():
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/events",
            "raw_path": b"/events",
            "root_path": "",
            "query_string": b"",
            "headers": [(b"host", b"testserver")],
            "client": ("testclient", 1),
            "server": ("testserver", 80),
        }

        async def receive():
            await asyncio.sleep(3600)

        async def send(message):
            if message["type"] == "http.response.start":
                gesehen.update({k.decode(): v.decode() for k, v in message["headers"]})
                raise Fertig

        with pytest.raises(Fertig):
            await application(scope, receive, send)

    asyncio.run(run())
    assert gesehen["content-type"].startswith("text/event-stream")
    assert gesehen["content-security-policy"].startswith("default-src 'self'")
    assert gesehen["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize("mode", ["none", "paperless"])
def test_vorschau_behaelt_eigene_frame_header(tmp_path, monkeypatch, mode):
    with _make_client(tmp_path, monkeypatch, mode=mode) as (c, application, _):
        if mode == "paperless":
            _login(c)

        async def fake_preview(invoice_id):
            return b"%PDF-1.4 x", "application/pdf"

        monkeypatch.setattr(application.state.sync, "fetch_preview", fake_preview)
        resp = c.get("/invoices/1/preview")
        assert resp.status_code == 200
        csp = resp.headers["content-security-policy"]
        assert "frame-ancestors 'self'" in csp
        assert "script-src 'none'" in csp
        assert resp.headers["x-frame-options"] == "SAMEORIGIN"
        assert resp.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize(
    "content_type", ["application/pdf", "image/png", "image/jpeg", "image/tiff; x=1"]
)
def test_vorschau_laesst_dokumenttypen_durch(tmp_path, monkeypatch, content_type):
    with _make_client(tmp_path, monkeypatch, mode="none") as (c, application, _):

        async def fake_preview(invoice_id):
            return b"daten", content_type

        monkeypatch.setattr(application.state.sync, "fetch_preview", fake_preview)
        assert c.get("/invoices/1/preview").status_code == 200


@pytest.mark.parametrize(
    "content_type",
    ["text/html", "text/html; charset=utf-8", "image/svg+xml", "application/xhtml+xml"],
)
def test_vorschau_weist_aktive_inhalte_ab(tmp_path, monkeypatch, content_type):
    with _make_client(tmp_path, monkeypatch, mode="none") as (c, application, _):

        async def fake_preview(invoice_id):
            return b"<script>alert(1)</script>", content_type

        monkeypatch.setattr(application.state.sync, "fetch_preview", fake_preview)
        resp = c.get("/invoices/1/preview")
        assert resp.status_code == 415
        assert resp.text == "Vorschau nicht verfügbar"
        assert "<script>" not in resp.text


# --- Serverseitige Sitzungsliste (design.md D10) -----------------------------------------


def _signiert(secret, payload):
    raw = base64.b64encode(json.dumps(payload).encode("utf-8"))
    return TimestampSigner(secret).sign(raw).decode("utf-8")


def _ts(delta):
    return (datetime.now(UTC) - delta).strftime("%Y-%m-%d %H:%M:%S")


def _sid(c):
    # Mehrere gleichnamige Cookies (selbst gesetzt ohne Domain, vom Server mit Domain) möglich:
    # maßgeblich ist das zuletzt vom Server gesetzte.
    werte = [ck.value for ck in c.cookies.jar if ck.name == "lector_session" and ck.domain]
    data = TimestampSigner("geheimnis-a").unsign(werte[-1].encode())
    return json.loads(base64.b64decode(data))["sid"]


def test_cookie_traegt_nur_die_sid(auth_client):
    c, application, _ = auth_client
    data = TimestampSigner("geheimnis-a").unsign(c.cookies.get("lector_session").encode())
    cookie = json.loads(base64.b64decode(data))
    assert list(cookie) == ["sid"]
    assert application.state.repo.get_web_session(cookie["sid"])[0] == "sascha"


def test_kopiertes_cookie_nach_abmelden_ist_ungueltig(auth_client):
    c, _, _ = auth_client
    kopie = c.cookies.get("lector_session")
    assert c.post("/logout", headers=EIGENE_HERKUNFT, follow_redirects=False).status_code == 303
    c.cookies.clear()
    c.cookies.set("lector_session", kopie)
    assert c.get("/auth/status").status_code == 401
    assert c.get("/", headers=HTML, follow_redirects=False).status_code == 303


def test_zweites_geraet_bleibt_nach_abmelden_angemeldet(auth_client):
    c, application, _ = auth_client
    erstes = c.cookies.get("lector_session")
    c.cookies.clear()
    assert _login(c).status_code == 303
    zweites = c.cookies.get("lector_session")
    assert zweites != erstes
    c.cookies.clear()
    c.cookies.set("lector_session", erstes)
    assert c.post("/logout", headers=EIGENE_HERKUNFT, follow_redirects=False).status_code == 303
    c.cookies.clear()
    c.cookies.set("lector_session", zweites)
    assert c.get("/auth/status").status_code == 204
    assert c.post("/logout", headers=EIGENE_HERKUNFT, follow_redirects=False).status_code == 303


def test_absolute_grenze_90_tage_trotz_frischer_nutzung(auth_client):
    c, application, _ = auth_client
    sid = _sid(c)
    conn = application.state.repo._conn
    assert c.get("/auth/status").status_code == 204
    conn.execute(
        "UPDATE web_sessions SET created_at = ?, last_seen_at = ? WHERE id = ?",
        (_ts(timedelta(days=91)), _ts(timedelta(seconds=5)), sid),
    )
    conn.commit()
    assert c.get("/auth/status").status_code == 401
    # Knapp darunter gilt sie noch.
    conn.execute(
        "UPDATE web_sessions SET created_at = ? WHERE id = ?", (_ts(timedelta(days=89)), sid)
    )
    conn.commit()
    c.cookies.set("lector_session", _signiert("geheimnis-a", {"sid": sid}))
    assert c.get("/auth/status").status_code == 204


def test_leerlauf_30_tage_beendet_sitzung(auth_client):
    c, application, _ = auth_client
    sid = _sid(c)
    conn = application.state.repo._conn
    conn.execute(
        "UPDATE web_sessions SET last_seen_at = ? WHERE id = ?", (_ts(timedelta(days=31)), sid)
    )
    conn.commit()
    resp = c.get("/", headers=HTML, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/login")
    # Das ungültige Cookie wird gelöscht, nicht erneuert.
    (cookie,) = _session_cookies(resp)
    assert "max-age=0" in cookie.lower()


def test_erfundene_sid_mit_gueltiger_signatur_ist_keine_sitzung(auth_client):
    c, _, _ = auth_client
    c.cookies.clear()
    c.cookies.set("lector_session", _signiert("geheimnis-a", {"sid": "erfunden"}))
    assert c.get("/auth/status").status_code == 401
    # Altes Format (Nutzer im Cookie) zählt ebenfalls nicht.
    c.cookies.set("lector_session", _signiert("geheimnis-a", {"user": "sascha"}))
    assert c.get("/auth/status").status_code == 401


def test_login_vergibt_neue_sid_und_uebernimmt_mitgebrachte_nicht(auth_client):
    c, application, _ = auth_client
    repo = application.state.repo
    alt = _sid(c)
    assert _login(c).status_code == 303  # mit bestehender Sitzung erneut anmelden
    neu = _sid(c)
    assert neu != alt
    assert repo.get_web_session(alt) is None  # Rotation: alte Zeile gelöscht
    assert repo.get_web_session(neu) is not None
    # Erfundene sid mitgebracht: nach dem Login steht eine frische sid im Cookie.
    c.cookies.clear()
    c.cookies.set("lector_session", _signiert("geheimnis-a", {"sid": "fixiert"}))
    assert _login(c).status_code == 303
    assert _sid(c) not in ("fixiert", neu)
    assert repo.get_web_session("fixiert") is None


def test_neustart_erhaelt_sitzung(tmp_path, monkeypatch):
    with _make_client(tmp_path, monkeypatch) as (c, _, _):
        _login(c)
        cookie = c.cookies.get("lector_session")
    with _make_client(tmp_path, monkeypatch) as (c, _, _):
        c.cookies.set("lector_session", cookie)
        assert c.get("/auth/status").status_code == 204


def test_last_seen_wird_gedrosselt_geschrieben(auth_client):
    c, application, _ = auth_client
    repo = application.state.repo
    sid = _sid(c)
    conn = repo._conn
    frisch = _ts(timedelta(seconds=10))
    conn.execute("UPDATE web_sessions SET last_seen_at = ? WHERE id = ?", (frisch, sid))
    conn.commit()
    for _ in range(3):
        assert c.get("/auth/status").status_code == 204
    assert repo.get_web_session(sid)[2] == frisch  # unter 60 s: nicht neu geschrieben
    alt = _ts(timedelta(minutes=5))
    conn.execute("UPDATE web_sessions SET last_seen_at = ? WHERE id = ?", (alt, sid))
    conn.commit()
    assert c.get("/auth/status").status_code == 204
    assert repo.get_web_session(sid)[2] > alt


def test_sitzungen_loesen_keinen_sse_token_aus(tmp_path):
    tokens = []
    repo = Repository(tmp_path / "t.db", notifier=tokens.append)
    sid = repo.create_web_session("sascha")
    repo.touch_web_session(sid)
    repo.delete_web_session(sid)
    repo.purge_web_sessions()
    assert tokens == []


def test_purge_entfernt_nur_abgelaufene_sitzungen(tmp_path):
    repo = Repository(tmp_path / "t.db")
    jetzt = datetime.now(UTC)
    frisch = repo.create_web_session("a", jetzt)
    leerlauf = repo.create_web_session("b", jetzt - timedelta(days=60))
    repo.touch_web_session(leerlauf, jetzt - timedelta(days=31))
    zu_alt = repo.create_web_session("c", jetzt - timedelta(days=91))
    repo.touch_web_session(zu_alt, jetzt)
    grenze = repo.create_web_session("d", jetzt - timedelta(days=89))
    repo.touch_web_session(grenze, jetzt)
    assert repo.purge_web_sessions(jetzt) == 2
    assert repo.get_web_session(frisch) and repo.get_web_session(grenze)
    assert repo.get_web_session(leerlauf) is None and repo.get_web_session(zu_alt) is None


def test_modus_none_legt_keine_sitzungen_an(plain_client):
    c, application, _ = plain_client
    c.get("/", headers=HTML)
    c.post("/login", data={"username": "x", "password": "y"}, headers=EIGENE_HERKUNFT)
    n = application.state.repo._conn.execute("SELECT COUNT(*) FROM web_sessions").fetchone()[0]
    assert n == 0


# --- Zugangsschlüssel der App (Change ios-app, design.md D3) -----------------------------


def _api_login(c, username="sascha"):
    """Meldet sich über die Schnittstelle an (ohne Cookie) und liefert den Schlüssel."""
    resp = c.post(
        "/api/v1/login",
        json={"username": username, "password": PASSWORT},
        headers={"Origin": "https://fremd.example"},  # Herkunft ist für den Login ohne Belang
    )
    assert resp.status_code == 200, resp.text
    c.cookies.clear()
    return resp.json()["token"]


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_post_mit_schluessel_ohne_origin_wird_ausgefuehrt(anon_client, tmp_path):
    c, _, _ = anon_client
    token = _api_login(c)
    resp = c.post(
        "/upload",
        files=[("files", ("scan.pdf", b"%PDF-1.4 x", "application/pdf"))],
        headers=_bearer(token),
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert [p.name for p in (tmp_path / "scan-in").iterdir()] == ["scan.pdf"]


def test_post_mit_cookie_ohne_origin_bleibt_403(auth_client, tmp_path):
    c, _, _ = auth_client
    resp = c.post(
        "/upload",
        files=[("files", ("scan.pdf", b"%PDF-1.4 x", "application/pdf"))],
        follow_redirects=False,
    )
    assert resp.status_code == 403
    assert list((tmp_path / "scan-in").iterdir()) == []


def test_schluessel_sitzung_kommt_ohne_cookie_aus_und_setzt_keins(anon_client):
    c, _, _ = anon_client
    token = _api_login(c)
    resp = c.get("/auth/status", headers=_bearer(token))
    assert resp.status_code == 204
    assert "set-cookie" not in resp.headers


def test_ungueltiger_schluessel_neben_gueltigem_cookie_401(auth_client):
    """Schickt die Anfrage einen Schlüssel mit, entscheidet allein er: kein Rückfall auf das
    (gültige) Cookie."""
    c, _, _ = auth_client
    assert c.get("/auth/status").status_code == 204
    resp = c.get("/auth/status", headers=_bearer("kein-gueltiger-schluessel"))
    assert resp.status_code == 401
    assert "set-cookie" not in resp.headers
    resp = c.get("/api/v1/documents", headers=_bearer("kein-gueltiger-schluessel"))
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "not_authenticated"


def test_cookie_wert_als_schluessel_wird_abgelehnt(auth_client):
    c, _, _ = auth_client
    cookie = c.cookies.get("lector_session")
    assert c.get("/auth/status", headers=_bearer(cookie)).status_code == 401


def test_api_ohne_sitzung_401_json_ohne_umleitung(anon_client):
    c, _, _ = anon_client
    for headers in ({}, HTML):  # auch mit Browser-Accept keine Umleitung
        resp = c.get("/api/v1/documents", headers=headers, follow_redirects=False)
        assert resp.status_code == 401
        assert "location" not in resp.headers
        assert resp.headers["content-type"].startswith("application/json")
        assert resp.json()["error"]["code"] == "not_authenticated"
        assert resp.json()["error"]["message"]
    resp = c.post("/api/v1/upload", follow_redirects=False)
    assert resp.status_code == 401


def test_options_ohne_cors_freigabe(anon_client):
    c, _, _ = anon_client
    token = _api_login(c)
    for headers in (
        {},
        _bearer(token),
        {"Origin": "https://fremd.example", "Access-Control-Request-Method": "GET"},
    ):
        resp = c.options("/api/v1/documents", headers=headers)
        assert not [h for h in resp.headers if h.lower().startswith("access-control-allow")]
    resp = c.get("/api/info", headers={"Origin": "https://fremd.example"})
    assert not [h for h in resp.headers if h.lower().startswith("access-control-allow")]


async def _asgi_get(application, path, headers):
    """Ruft die App direkt per ASGI auf und bricht nach dem ersten Körperblock ab (ein
    TestClient-Aufruf von /events würde hängen). Liefert Status, Header und den Block."""
    gesehen: dict = {}

    class Fertig(Exception):
        pass

    async def receive():
        await asyncio.sleep(3600)

    async def send(message):
        if message["type"] == "http.response.start":
            gesehen["status"] = message["status"]
            gesehen["headers"] = {k.decode(): v.decode() for k, v in message["headers"]}
        elif message["type"] == "http.response.body":
            gesehen["body"] = message["body"]
            raise Fertig

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": [(b"host", b"testserver"), *headers],
        "client": ("testclient", 1),
        "server": ("testserver", 80),
    }
    with pytest.raises(Fertig):
        await application(scope, receive, send)
    return gesehen


def test_events_mit_schluessel_oeffnet_den_strom(anon_client):
    """200 und Ereignisstrom mit Zugangsschlüssel, ohne Cookie; ohne Schlüssel 401."""
    c, application, _ = anon_client
    token = _api_login(c)

    mit = asyncio.run(
        _asgi_get(application, "/events", [(b"authorization", f"Bearer {token}".encode())])
    )
    assert mit["status"] == 200
    assert mit["headers"]["content-type"].startswith("text/event-stream")
    assert "set-cookie" not in mit["headers"]
    assert mit["body"] == b": connected\n\n"

    ohne = asyncio.run(_asgi_get(application, "/events", []))
    assert ohne["status"] == 401
