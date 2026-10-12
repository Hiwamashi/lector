"""Tests für Login-Drosselung und Herkunftsprüfung."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta

import pytest
from itsdangerous import TimestampSigner

from app.auth import LoginThrottle, _ip_key, load_app_session, origin_allowed, sign_app_token
from app.repository import Repository


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _throttle(clock: _Clock, **kw) -> LoginThrottle:
    return LoginThrottle(clock=clock, **kw)


def test_sperre_je_ip():
    clock = _Clock()
    t = _throttle(clock)
    for i in range(5):
        assert not t.is_blocked("1.1.1.1", f"user{i}")
        t.record_failure("1.1.1.1", f"user{i}")
    assert t.is_blocked("1.1.1.1", "ganz-neu")
    assert not t.is_blocked("2.2.2.2", "ganz-neu")


def test_sperre_je_nutzer_ueber_ips():
    clock = _Clock()
    t = _throttle(clock)
    for i in range(5):
        t.record_failure(f"10.0.0.{i}", "  Anna ")
    assert t.is_blocked("9.9.9.9", "anna")
    assert not t.is_blocked("9.9.9.9", "bert")


def test_fenster_laeuft_ab():
    clock = _Clock()
    t = _throttle(clock)
    for _ in range(5):
        t.record_failure("1.1.1.1", "anna")
    assert t.is_blocked("1.1.1.1", "anna")
    clock.now += 901
    assert not t.is_blocked("1.1.1.1", "anna")


def test_reset_nach_erfolg_nur_nutzer():
    clock = _Clock()
    t = _throttle(clock)
    for _ in range(5):
        t.record_failure("1.1.1.1", "anna")
    t.record_success("Anna")
    assert not t.is_blocked("2.2.2.2", "anna")
    assert t.is_blocked("1.1.1.1", "bert")  # IP-Zähler bleibt


def test_schluesselzahl_gekappt():
    clock = _Clock()
    t = _throttle(clock, max_keys=3)
    for i in range(10):
        clock.now += 1
        t.record_failure(f"ip{i}", f"user{i}")
    assert len(t._by_ip) == 3
    assert len(t._by_user) == 3
    assert "ip9" in t._by_ip and "ip0" not in t._by_ip


def test_laufende_versuche_zaehlen_wie_fehlversuche():
    t = _throttle(_Clock())
    for i in range(5):
        assert t.try_begin("1.1.1.1", f"user{i}")  # noch nichts abgeschlossen
    assert not t.try_begin("1.1.1.1", "user99")  # IP-Limit durch laufende Versuche erreicht
    assert t.try_begin("2.2.2.2", "user99")


def test_hoechstens_ein_laufender_versuch_je_nutzername():
    t = _throttle(_Clock())
    assert t.try_begin("1.1.1.1", "Anna")
    assert not t.try_begin("2.2.2.2", " anna ")
    t.finish("1.1.1.1", "Anna", failed=False)
    assert t.try_begin("2.2.2.2", "anna")


def test_finish_zaehlt_fehlversuch_und_gibt_frei():
    t = _throttle(_Clock())
    for _ in range(5):
        assert t.try_begin("1.1.1.1", "anna")
        t.finish("1.1.1.1", "anna", failed=True)
    assert not t.try_begin("1.1.1.1", "anna")
    assert t._active_ip == {} and t._active_user == {}


def test_finish_ohne_fehler_zaehlt_nicht():
    t = _throttle(_Clock())
    for _ in range(20):
        assert t.try_begin("1.1.1.1", "anna")
        t.finish("1.1.1.1", "anna", failed=False)
    assert not t.is_blocked("1.1.1.1", "anna")


async def test_gleichzeitige_versuche_hoechstens_max_failures():
    import asyncio

    t = _throttle(_Clock())
    aufrufe = 0

    async def login(i: int) -> None:
        nonlocal aufrufe
        if not t.try_begin("1.1.1.1", f"user{i}"):
            return
        try:
            aufrufe += 1
            await asyncio.sleep(0.01)  # wie obtain_token: die Lücke zwischen Prüfung und Zählung
        finally:
            t.finish("1.1.1.1", f"user{i}", failed=True)

    await asyncio.gather(*(login(i) for i in range(50)))
    assert aufrufe == 5


def test_ipv6_wird_auf_64_normalisiert():
    assert _ip_key("2001:db8:1:2:aaaa:bbbb:cccc:dddd") == _ip_key("2001:db8:1:2::1")
    assert _ip_key("2001:db8:1:2::1") != _ip_key("2001:db8:1:3::1")
    assert _ip_key("::ffff:10.1.2.3") == "10.1.2.3"
    assert _ip_key("10.1.2.3") == "10.1.2.3"
    assert _ip_key("unbekannt") == "unbekannt"
    assert _ip_key("testclient") == "testclient"


def test_sperre_gilt_fuer_ganzes_ipv6_64er_praefix():
    t = _throttle(_Clock())
    for i in range(5):
        t.record_failure(f"2001:db8:1:2::{i + 1}", f"user{i}")
    assert t.is_blocked("2001:db8:1:2:ffff::9", "neu")
    assert not t.is_blocked("2001:db8:1:3::1", "neu")


def test_verdraengung_nach_letzter_aktivitaet():
    clock = _Clock()
    t = _throttle(clock, max_keys=3)
    for name in ("a", "b", "c"):
        clock.now += 1
        t.record_failure("ip-" + name, name)
    clock.now += 1
    t.record_failure("ip-a", "a")  # a ist wieder aktiv, b jetzt am längsten inaktiv
    clock.now += 1
    t.record_failure("ip-d", "d")
    assert "ip-b" not in t._by_ip and "b" not in t._by_user
    assert "ip-a" in t._by_ip and "a" in t._by_user


def test_gesperrter_schluessel_wird_bevorzugt_behalten():
    clock = _Clock()
    t = _throttle(clock, max_keys=3)
    for _ in range(5):
        t.record_failure("angreifer", "opfer")  # am ältesten, aber gesperrt
    for name in ("x", "y", "z"):
        clock.now += 1
        t.record_failure("ip-" + name, name)
    assert "angreifer" in t._by_ip and "opfer" in t._by_user
    assert t.is_blocked("angreifer", "egal")
    assert len(t._by_ip) == 3


# ---- origin_allowed -----------------------------------------------------

HOST = "lector.nerd-wg.eu"


def test_eigene_herkunft():
    assert origin_allowed("POST", "https", HOST, "https://lector.nerd-wg.eu", None)
    assert origin_allowed("POST", "https", HOST, "https://LECTOR.nerd-wg.eu", None)


def test_schwester_subdomain_abgelehnt():
    assert not origin_allowed("POST", "https", HOST, "https://paperless.nerd-wg.eu", None)


def test_fremdes_schema_abgelehnt():
    assert not origin_allowed("POST", "https", HOST, "http://lector.nerd-wg.eu", None)


def test_nur_referer():
    assert origin_allowed("POST", "https", HOST, None, "https://lector.nerd-wg.eu/login?x=1")
    assert not origin_allowed("POST", "https", HOST, None, "https://paperless.nerd-wg.eu/x")


def test_port_im_host():
    assert origin_allowed("POST", "http", "nas:8080", "http://nas:8080", None)
    assert not origin_allowed("POST", "http", "nas:8080", "http://nas:9090", None)


def test_kein_header_und_null_origin():
    assert not origin_allowed("POST", "https", HOST, None, None)
    assert not origin_allowed("POST", "https", HOST, "null", "https://lector.nerd-wg.eu/")


def test_get_immer_erlaubt():
    for m in ("GET", "HEAD", "OPTIONS"):
        assert origin_allowed(m, "https", HOST, None, None)
        assert origin_allowed(m, "https", HOST, "https://evil.example", None)


# --- Zugangsschlüssel der App (ios-app D2) -----------------------------------------------

SECRET = "geheimnis-a"


@pytest.fixture
def repo(tmp_path):
    r = Repository(tmp_path / "lector.db")
    yield r
    r.close()


def _token_fuer(repo, *, created=None, seen=None):
    """Legt eine Sitzung an (optional mit zurückdatierten Zeitpunkten) und liefert
    ``(sid, schluessel)``."""
    now = datetime.now(UTC)
    sid = repo.create_web_session("sascha", now=created or now)
    if seen is not None:
        repo.touch_web_session(sid, seen)
    return sid, sign_app_token(SECRET, sid)


def test_schluessel_gueltig(repo):
    sid, token = _token_fuer(repo)
    assert load_app_session(token, SECRET, repo) == {"sid": sid, "user": "sascha"}


def test_schluessel_veraendert_wird_abgelehnt(repo):
    _, token = _token_fuer(repo)
    assert load_app_session(token[:-2] + "xx", SECRET, repo) == {}
    assert load_app_session("x" + token, SECRET, repo) == {}
    assert load_app_session("", SECRET, repo) == {}
    # Selbst erstellt: nur die sid, ohne Signatur.
    sid = token.split(".")[0]
    assert load_app_session(sid, SECRET, repo) == {}


def test_cookie_wert_taugt_nicht_als_schluessel(repo):
    """Eigenes Salt: Ein abgegriffenes Cookie ist als Header-Schlüssel wertlos."""
    sid, _ = _token_fuer(repo)
    payload = base64.b64encode(json.dumps({"sid": sid}).encode("utf-8"))
    cookie_wert = TimestampSigner(SECRET).sign(payload).decode("utf-8")
    assert load_app_session(cookie_wert, SECRET, repo) == {}
    # Auch eine mit dem Cookie-Salt signierte nackte sid wird abgelehnt.
    assert load_app_session(TimestampSigner(SECRET).sign(sid).decode(), SECRET, repo) == {}


def test_gewechseltes_geheimnis_macht_schluessel_ungueltig(repo):
    _, token = _token_fuer(repo)
    assert load_app_session(token, "anderes-geheimnis", repo) == {}


def test_geloeschte_sitzung_macht_schluessel_ungueltig(repo):
    sid, token = _token_fuer(repo)
    repo.delete_web_session(sid)
    assert load_app_session(token, SECRET, repo) == {}


def test_leerlauf_grenze(repo):
    now = datetime.now(UTC)
    _, frisch = _token_fuer(repo, created=now - timedelta(days=40), seen=now - timedelta(days=29))
    assert load_app_session(frisch, SECRET, repo) != {}
    _, alt = _token_fuer(repo, created=now - timedelta(days=40), seen=now - timedelta(days=31))
    assert load_app_session(alt, SECRET, repo) == {}


def test_absolute_grenze_trotz_regelmaessiger_nutzung(repo):
    """Auch ein eben noch benutzter Schlüssel endet 90 Tage nach der Anmeldung — und die
    Signatur selbst läuft nie ab (kein `max_age`): Ein 100 Tage alter Schlüssel einer
    jungen, aktiven Sitzung bliebe gültig."""
    now = datetime.now(UTC)
    _, zu_alt = _token_fuer(repo, created=now - timedelta(days=91), seen=now - timedelta(hours=1))
    assert load_app_session(zu_alt, SECRET, repo) == {}
    _, noch_gut = _token_fuer(repo, created=now - timedelta(days=89), seen=now)
    assert load_app_session(noch_gut, SECRET, repo) != {}


def test_signatur_ohne_altersgrenze(repo, monkeypatch):
    """Die App erneuert den Schlüssel nie: Der Signaturzeitstempel darf keine Rolle spielen."""
    sid, _ = _token_fuer(repo)
    alt = TimestampSigner(SECRET, salt="lector-app-token")
    vor_400_tagen = int(datetime.now(UTC).timestamp()) - 400 * 86400
    with monkeypatch.context() as m:
        m.setattr(TimestampSigner, "get_timestamp", lambda self: vor_400_tagen)
        token = alt.sign(sid).decode()
    assert load_app_session(token, SECRET, repo) == {"sid": sid, "user": "sascha"}


def test_last_seen_hoechstens_einmal_pro_minute(repo):
    now = datetime.now(UTC)
    sid, token = _token_fuer(repo, seen=now - timedelta(seconds=30))
    vorher = repo.get_web_session(sid)[2]
    assert load_app_session(token, SECRET, repo) != {}
    assert repo.get_web_session(sid)[2] == vorher  # unter einer Minute: nicht geschrieben

    sid2, token2 = _token_fuer(repo, seen=now - timedelta(minutes=5))
    vorher2 = repo.get_web_session(sid2)[2]
    assert load_app_session(token2, SECRET, repo) != {}
    assert repo.get_web_session(sid2)[2] > vorher2
