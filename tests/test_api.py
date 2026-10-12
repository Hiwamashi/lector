"""App-Schnittstelle (Change ios-app, design.md D1–D8): Selbstauskunft, Anmeldung, Vorgangsliste,
Detail, Entscheidungen, Upload und Ende-zu-Ende mit dem echten Worker."""

from __future__ import annotations

import hashlib
import io
import logging
import re
import threading
import time
from datetime import UTC, datetime

import pikepdf
import pytest
from reportlab.pdfgen import canvas
from test_web import _blocked_document
from test_web_auth import EIGENE_HERKUNFT, PASSWORT, _login, _make_client

from app.models import DocStatus, EventType
from app.paperless import LoginResult

ZEITSTEMPEL = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
ALLE_ZUSTAENDE = {
    "pending",
    "processing",
    "blocked",
    "done",
    "skipped_erechnung",
    "failed",
}


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _api_login(c, username="sascha", password=PASSWORT, **extra):
    return c.post(
        "/api/v1/login", json={"username": username, "password": password, **extra}
    )


@pytest.fixture
def api(tmp_path, monkeypatch):
    """AUTH_MODE=paperless; der Client trägt den Zugangsschlüssel als Standard-Header und
    kein Cookie. Liefert ``(client, app, fake)``."""
    with _make_client(tmp_path, monkeypatch) as (c, application, fake):
        resp = _api_login(c)
        assert resp.status_code == 200
        c.cookies.clear()
        c.headers.update(_bearer(resp.json()["token"]))
        fake.calls.clear()
        yield c, application, fake


@pytest.fixture
def anon(tmp_path, monkeypatch):
    """AUTH_MODE=paperless, ohne Sitzung."""
    with _make_client(tmp_path, monkeypatch) as triple:
        yield triple


@pytest.fixture
def plain(tmp_path, monkeypatch):
    """AUTH_MODE=none."""
    with _make_client(tmp_path, monkeypatch, mode="none") as triple:
        yield triple


def _seed(application, name, status=DocStatus.DONE, **fields):
    repo = application.state.repo
    doc_id = repo.create_document(original_filename=name, source_path=f"/intern/{name}")
    repo.update_document(doc_id, status=status, **fields)
    return doc_id


# --- 2.1 Grundlagen: Fehlerformat, Zeitangaben, keine Pfade ------------------------------


def test_ungueltige_anfrage_unter_api_ist_invalid_request(api):
    c, _, _ = api
    resp = c.get("/api/v1/documents", params={"limit": "viele"})
    assert resp.status_code == 422
    fehler = resp.json()["error"]
    assert fehler["code"] == "invalid_request"
    assert fehler["message"]
    assert set(resp.json()) == {"error"}
    resp = c.get("/api/v1/documents/abc")
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "invalid_request"


def test_validierungsfehler_ausserhalb_von_api_bleiben_unveraendert(plain):
    c, _, _ = plain
    resp = c.get("/documents/abc")
    assert resp.status_code == 422
    assert "detail" in resp.json()


def test_zeitstempel_enden_auf_z_und_keine_pfade(api):
    c, application, _ = api
    doc_id = _seed(application, "a.pdf")
    application.state.repo.add_event(doc_id, EventType.DONE, "fertig")
    for dokument in (
        c.get("/api/v1/documents").json()["documents"][0],
        c.get(f"/api/v1/documents/{doc_id}").json()["document"],
    ):
        assert ZEITSTEMPEL.match(dokument["created_at"])
        assert "source_path" not in dokument and "output_path" not in dokument
        assert dokument["started_at"] is None
    ereignis = c.get(f"/api/v1/documents/{doc_id}").json()["events"][0]
    assert ZEITSTEMPEL.match(ereignis["timestamp"])
    # Die Datenbank hält UTC: derselbe Zeitpunkt, nur mit Z markiert.
    gelesen = datetime.strptime(ereignis["timestamp"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    assert abs((datetime.now(UTC) - gelesen).total_seconds()) < 60


def test_dokument_hat_genau_die_felder_des_vertrags(api):
    c, application, _ = api
    _seed(application, "a.pdf")
    dokument = c.get("/api/v1/documents").json()["documents"][0]
    assert set(dokument) == {
        "id",
        "original_filename",
        "status",
        "doc_type",
        "total_pages",
        "processed_pages",
        "attempt_count",
        "next_retry_at",
        "error_message",
        "page_limit_approved",
        "created_at",
        "started_at",
        "finished_at",
    }


# --- 2.2 Selbstauskunft ------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["none", "paperless"])
def test_info_ohne_sitzung_in_beiden_modi(tmp_path, monkeypatch, mode):
    with _make_client(tmp_path, monkeypatch, mode=mode) as (c, _, _):
        resp = c.get("/api/info")
        assert resp.status_code == 200
        assert resp.json() == {"service": "lector", "api_version": 1, "auth_mode": mode}


# --- 2.3 Anmeldung und Abmeldung ---------------------------------------------------------


def test_login_erfolg_schluessel_funktioniert_danach(anon):
    c, _, fake = anon
    resp = _api_login(c, code=" 123456 ")
    assert resp.status_code == 200
    assert set(resp.json()) == {"token", "username"}
    assert resp.json()["username"] == "sascha"
    assert fake.calls == [("http://paperless.invalid", "sascha", PASSWORT, "123456")]
    assert "set-cookie" not in resp.headers
    c.cookies.clear()
    assert c.get("/api/v1/documents").status_code == 401
    ok = c.get("/api/v1/documents", headers=_bearer(resp.json()["token"]))
    assert ok.status_code == 200


def test_login_ohne_code_reicht_none_weiter(anon):
    c, _, fake = anon
    assert _api_login(c).status_code == 200
    assert fake.calls[0][3] is None


def test_login_falsche_angaben(anon, caplog):
    c, _, fake = anon
    fake.result = LoginResult.INVALID
    with caplog.at_level(logging.INFO):
        resp = _api_login(c)
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "invalid_credentials"
    assert "token" not in resp.text
    assert PASSWORT not in caplog.text and PASSWORT not in resp.text


def test_login_mfa_erforderlich_ohne_schluessel(anon):
    c, _, fake = anon
    fake.result = LoginResult.MFA_REQUIRED
    resp = _api_login(c)
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "mfa_required"
    assert "token" not in resp.text


def test_login_paperless_nicht_erreichbar_zaehlt_nicht_als_fehlversuch(anon):
    c, _, fake = anon
    fake.result = LoginResult.UNAVAILABLE
    for _ in range(7):
        resp = _api_login(c)
        assert resp.status_code == 503
        assert resp.json()["error"]["code"] == "paperless_unavailable"
    assert len(fake.calls) == 7


def test_login_leere_angaben_ohne_rueckfrage_bei_paperless(anon):
    c, _, fake = anon
    resp = _api_login(c, username="  ", password="x")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "invalid_credentials"
    assert fake.calls == []


def test_login_gemeinsame_bremse_mit_der_anmeldeseite(anon):
    """Drei Fehlversuche über das Formular plus zwei über die Schnittstelle erreichen das
    gemeinsame Limit; danach wird über beide Wege abgewiesen, ohne Paperless zu befragen."""
    c, _, fake = anon
    fake.result = LoginResult.INVALID
    for _ in range(3):
        assert "Anmeldung fehlgeschlagen" in _login(c).text
    for _ in range(2):
        assert _api_login(c).status_code == 401
    assert len(fake.calls) == 5

    fake.result = LoginResult.OK  # selbst gültige Angaben werden jetzt abgewiesen
    resp = _api_login(c)
    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "throttled"
    assert "Zu viele Fehlversuche" in _login(c).text
    assert len(fake.calls) == 5


def test_login_formular_content_type_415(anon):
    c, _, fake = anon
    resp = c.post("/api/v1/login", data={"username": "sascha", "password": PASSWORT})
    assert resp.status_code == 415
    assert resp.json()["error"]["code"] == "invalid_request"
    resp = c.post("/api/v1/login", content=b'{"username":"a","password":"b"}')
    assert resp.status_code == 415
    assert fake.calls == []


def test_login_ohne_pflichtfeld_oder_mit_kaputtem_json_ist_422(anon):
    c, _, fake = anon
    assert c.post("/api/v1/login", json={"username": "sascha"}).status_code == 422
    resp = c.post(
        "/api/v1/login", content=b"{kaputt", headers={"Content-Type": "application/json"}
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "invalid_request"
    assert fake.calls == []


def test_login_ohne_herkunftsangabe_funktioniert(anon):
    c, _, _ = anon
    assert _api_login(c).status_code == 200  # kein Origin-Header


def test_logout_beendet_nur_diese_sitzung(anon):
    c, application, _ = anon
    # Browser-Sitzung derselben Person.
    assert _login(c).status_code == 303
    assert c.get("/auth/status").status_code == 204
    token = _api_login(c).json()["token"]
    assert len(_sitzungen(application)) == 2

    resp = c.post("/api/v1/logout", headers=_bearer(token))  # ohne Origin
    assert resp.status_code == 204
    assert resp.content == b""
    assert c.get("/api/v1/documents", headers=_bearer(token)).status_code == 401
    assert c.get("/auth/status").status_code == 204  # Browser-Sitzung bleibt


def _sitzungen(application):
    repo = application.state.repo
    with repo._lock:
        return repo._conn.execute("SELECT id FROM web_sessions").fetchall()


def test_logout_ohne_schluessel_ist_nicht_angemeldet(anon):
    c, _, _ = anon
    resp = c.post("/api/v1/logout")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "not_authenticated"


def test_login_und_logout_im_modus_none_404(plain):
    c, _, fake = plain
    resp = _api_login(c)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"
    assert c.post("/api/v1/logout").status_code == 404
    assert fake.calls == []


# --- 2.4 Vorgangsliste -------------------------------------------------------------------


def test_liste_neueste_zuerst_mit_zaehlern(api):
    c, application, _ = api
    a = _seed(application, "alt.pdf", DocStatus.DONE)
    b = _seed(application, "mitte.pdf", DocStatus.FAILED)
    n = _seed(application, "neu.pdf", DocStatus.PENDING)
    body = c.get("/api/v1/documents").json()
    assert [d["id"] for d in body["documents"]] == [n, b, a]
    assert body["limit"] == 200 and body["offset"] == 0
    assert body["counts"] == {s: 0 for s in ALLE_ZUSTAENDE} | {
        "done": 1,
        "failed": 1,
        "pending": 1,
    }
    assert body["documents"][0]["status"] == "pending"


def test_liste_leerer_bestand_nennt_alle_zustaende(api):
    c, _, _ = api
    body = c.get("/api/v1/documents").json()
    assert body["documents"] == []
    assert body["counts"] == {s: 0 for s in ALLE_ZUSTAENDE}


def test_liste_filter_zustand_und_suche_mit_ungefilterten_zaehlern(api):
    c, application, _ = api
    _seed(application, "rechnung-1.pdf", DocStatus.FAILED)
    treffer = _seed(application, "Rechnung-2.pdf", DocStatus.FAILED)
    _seed(application, "brief.pdf", DocStatus.FAILED)
    _seed(application, "rechnung-3.pdf", DocStatus.DONE)
    body = c.get("/api/v1/documents", params={"status": "failed", "q": "Rechnung-2"}).json()
    assert [d["id"] for d in body["documents"]] == [treffer]
    assert body["counts"]["failed"] == 3 and body["counts"]["done"] == 1

    body = c.get("/api/v1/documents", params={"status": "failed", "q": "rechnung"}).json()
    assert {d["original_filename"] for d in body["documents"]} == {
        "rechnung-1.pdf",
        "Rechnung-2.pdf",
    }


def test_liste_zeitraum_filter(api):
    c, application, _ = api
    alt = _seed(application, "alt.pdf")
    _seed(application, "neu.pdf")
    repo = application.state.repo
    with repo._lock:
        repo._conn.execute(
            "UPDATE documents SET created_at = '2000-01-01 00:00:00' WHERE id = ?", (alt,)
        )
        repo._conn.commit()
    assert len(c.get("/api/v1/documents").json()["documents"]) == 2
    nur_neu = c.get("/api/v1/documents", params={"period": "24h"}).json()["documents"]
    assert [d["original_filename"] for d in nur_neu] == ["neu.pdf"]


def test_liste_zweite_seite_ohne_ueberschneidung(api):
    c, application, _ = api
    for i in range(205):
        _seed(application, f"d{i:03}.pdf")
    erste = c.get("/api/v1/documents").json()
    zweite = c.get("/api/v1/documents", params={"offset": 200}).json()
    assert len(erste["documents"]) == 200 and len(zweite["documents"]) == 5
    ids_1 = {d["id"] for d in erste["documents"]}
    ids_2 = [d["id"] for d in zweite["documents"]]
    assert not ids_1 & set(ids_2)
    assert max(ids_2) < min(ids_1)  # die folgenden, älteren Vorgänge
    assert zweite["offset"] == 200
    assert sum(erste["counts"].values()) == 205


def test_liste_seitenweise_mit_kleinem_limit(api):
    c, application, _ = api
    ids = [_seed(application, f"d{i}.pdf") for i in range(5)]
    erste = c.get("/api/v1/documents", params={"limit": 2}).json()
    zweite = c.get("/api/v1/documents", params={"limit": 2, "offset": 2}).json()
    assert [d["id"] for d in erste["documents"] + zweite["documents"]] == ids[::-1][:4]
    assert erste["limit"] == 2


def test_liste_unbekannter_zustand_wie_ohne_filter(api):
    c, application, _ = api
    _seed(application, "a.pdf", DocStatus.DONE)
    _seed(application, "b.pdf", DocStatus.FAILED)
    ohne = c.get("/api/v1/documents").json()
    mit = c.get("/api/v1/documents", params={"status": "gibt-es-nicht"}).json()
    assert mit == ohne and len(mit["documents"]) == 2


def test_liste_limit_und_offset_werden_begrenzt(api):
    c, application, _ = api
    for i in range(3):
        _seed(application, f"d{i}.pdf")
    zu_gross = c.get("/api/v1/documents", params={"limit": 5000}).json()
    assert zu_gross["limit"] == 200 and len(zu_gross["documents"]) == 3
    zu_klein = c.get("/api/v1/documents", params={"limit": 0}).json()
    assert zu_klein["limit"] == 1 and len(zu_klein["documents"]) == 1
    negativ = c.get("/api/v1/documents", params={"limit": -4, "offset": -9}).json()
    assert negativ["limit"] == 1 and negativ["offset"] == 0


# --- 2.5 Vorgangsdetail ------------------------------------------------------------------


def test_detail_done_mit_verlauf_in_zeitlicher_reihenfolge(api):
    c, application, _ = api
    repo = application.state.repo
    doc_id = _seed(application, "a.pdf", DocStatus.DONE, total_pages=3, processed_pages=3)
    repo.add_event(doc_id, EventType.DETECTED, "erkannt")
    repo.add_event(doc_id, EventType.OCR_CHUNK, "Block 1")
    repo.add_event(doc_id, EventType.DONE, None)
    resp = c.get(f"/api/v1/documents/{doc_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"document", "events", "page_limit", "retry_max"}
    assert body["document"]["id"] == doc_id and body["document"]["status"] == "done"
    assert body["document"]["total_pages"] == 3
    assert [e["event_type"] for e in body["events"]] == ["detected", "ocr_chunk", "done"]
    assert [e["message"] for e in body["events"]] == ["erkannt", "Block 1", None]
    assert [e["id"] for e in body["events"]] == sorted(e["id"] for e in body["events"])
    settings = application.state.settings
    assert body["retry_max"] == settings.retry_max
    assert body["page_limit"] == settings.max_pages_per_document


def test_detail_blocked_nennt_seitenzahl_und_grenze(api):
    c, application, _ = api
    doc_id, _ = _blocked_document(application, pages=42)
    body = c.get(f"/api/v1/documents/{doc_id}").json()
    assert body["document"]["status"] == "blocked"
    assert body["document"]["total_pages"] == 42
    assert body["page_limit"] == application.state.settings.max_pages_per_document


def test_detail_unbekannte_kennung_404(api):
    c, _, _ = api
    resp = c.get("/api/v1/documents/99999")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


# --- 2.6 Entscheidungen ------------------------------------------------------------------


def test_freigeben(api):
    c, application, _ = api
    doc_id, _ = _blocked_document(application)
    resp = c.post(f"/api/v1/documents/{doc_id}/release")  # ohne Origin
    assert resp.status_code == 200
    assert set(resp.json()) == {"document"}
    assert resp.json()["document"]["status"] == "pending"
    assert resp.json()["document"]["page_limit_approved"] is True
    doc = application.state.repo.get_document(doc_id)
    assert doc.status == DocStatus.PENDING and doc.page_limit_approved


def test_verwerfen(api):
    c, application, _ = api
    doc_id, src = _blocked_document(application)
    resp = c.post(f"/api/v1/documents/{doc_id}/discard")
    assert resp.status_code == 200
    assert resp.json()["document"]["status"] == "failed"
    assert not src.exists()
    assert (application.state.settings.error_dir / src.name).exists()


@pytest.mark.parametrize("zweite", ["release", "discard"])
def test_doppelte_entscheidung_409_und_unveraendert(api, zweite):
    c, application, _ = api
    doc_id, _ = _blocked_document(application)
    assert c.post(f"/api/v1/documents/{doc_id}/release").status_code == 200
    vorher = application.state.repo.get_document(doc_id)
    ereignisse = len(application.state.repo.list_events(doc_id))

    resp = c.post(f"/api/v1/documents/{doc_id}/{zweite}")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "not_blocked"
    assert application.state.repo.get_document(doc_id) == vorher
    assert len(application.state.repo.list_events(doc_id)) == ereignisse


def test_verwerfen_scheitert_500_und_vorgang_bleibt_angehalten(api, monkeypatch):
    c, application, _ = api

    def boom(*args, **kwargs):
        raise OSError("Platte voll")

    monkeypatch.setattr("app.decisions.move_into", boom)
    doc_id, src = _blocked_document(application)
    resp = c.post(f"/api/v1/documents/{doc_id}/discard")
    assert resp.status_code == 500
    assert resp.json()["error"]["code"] == "discard_failed"
    assert application.state.repo.get_document(doc_id).status == DocStatus.BLOCKED
    assert src.exists()


@pytest.mark.parametrize("aktion", ["release", "discard"])
def test_entscheidung_unbekannte_kennung_404(api, aktion):
    c, _, _ = api
    resp = c.post(f"/api/v1/documents/99999/{aktion}")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_entscheidung_ohne_sitzung_401_und_nichts_veraendert(anon):
    c, application, _ = anon
    doc_id, _ = _blocked_document(application)
    for aktion in ("release", "discard"):
        resp = c.post(f"/api/v1/documents/{doc_id}/{aktion}", headers=EIGENE_HERKUNFT)
        assert resp.status_code == 401
    assert application.state.repo.get_document(doc_id).status == DocStatus.BLOCKED


# --- 2.7 Upload --------------------------------------------------------------------------

PDF = b"%PDF-1.4\n% Testinhalt \x00\xff\xfe\n%%EOF\n"


def _multipart(dateiname: str, inhalt: bytes) -> dict:
    grenze = "testgrenze"
    body = (
        f"--{grenze}\r\n"
        f'Content-Disposition: form-data; name="files"; filename="{dateiname}"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode() + inhalt + f"\r\n--{grenze}--\r\n".encode()
    return {
        "content": body,
        "headers": {"content-type": f"multipart/form-data; boundary={grenze}"},
    }


def _upload(c, *dateien, **kwargs):
    return c.post(
        "/api/v1/upload",
        files=[("files", (name, inhalt, "application/octet-stream")) for name, inhalt in dateien],
        **kwargs,
    )


def test_upload_pdf_angenommen_und_byte_genau(api, tmp_path):
    c, _, _ = api
    resp = _upload(c, ("Beleg.pdf", PDF))  # ohne Origin
    assert resp.status_code == 200
    assert resp.json() == {
        "results": [
            {"filename": "Beleg.pdf", "accepted": True, "reason": None, "stored_as": "Beleg.pdf"}
        ]
    }
    abgelegt = list((tmp_path / "scan-in").iterdir())
    assert [p.name for p in abgelegt] == ["Beleg.pdf"]
    assert hashlib.sha256(abgelegt[0].read_bytes()).digest() == hashlib.sha256(PDF).digest()


def test_upload_gleicher_name_wird_nicht_ueberschrieben(api, tmp_path):
    c, _, _ = api
    erste = _upload(c, ("Beleg.pdf", PDF)).json()["results"][0]
    zweite = _upload(c, ("Beleg.pdf", PDF + b"2")).json()["results"][0]
    assert zweite["accepted"] and zweite["stored_as"] != erste["stored_as"]
    assert len(list((tmp_path / "scan-in").iterdir())) == 2


def test_upload_gemischt_nennt_nicht_unterstuetztes_format(api, tmp_path):
    c, _, _ = api
    resp = _upload(c, ("a.pdf", PDF), ("notiz.docx", b"x"), ("b.xml", b"<x/>"))
    assert resp.status_code == 200
    ergebnis = {r["filename"]: r for r in resp.json()["results"]}
    assert ergebnis["a.pdf"]["accepted"] and ergebnis["b.xml"]["accepted"]
    assert ergebnis["notiz.docx"] == {
        "filename": "notiz.docx",
        "accepted": False,
        "reason": "unsupported_format",
        "stored_as": None,
    }
    assert sorted(p.name for p in (tmp_path / "scan-in").iterdir()) == ["a.pdf", "b.xml"]


def test_upload_unbrauchbarer_name(api, tmp_path):
    c, _, _ = api
    resp = _upload(c, ("..", PDF))
    assert resp.status_code == 200
    ergebnis = resp.json()["results"][0]
    assert ergebnis["accepted"] is False and ergebnis["reason"] == "unusable_name"
    assert list((tmp_path / "scan-in").iterdir()) == []


def test_upload_pfadbestandteile_im_namen_verlassen_den_eingang_nicht(api, tmp_path):
    c, _, _ = api
    resp = _upload(c, ("../../boese.pdf", PDF))
    assert resp.json()["results"][0]["stored_as"] == "boese.pdf"
    assert [p.name for p in (tmp_path / "scan-in").iterdir()] == ["boese.pdf"]
    assert not (tmp_path / "boese.pdf").exists()


def test_upload_schreibfehler_store_failed_ohne_datei(api, tmp_path, monkeypatch):
    c, _, _ = api

    def kaputt(*args, **kwargs):
        raise OSError("Platte voll")

    # Scheitert erst beim Umbenennen: store_upload hat dann schon geschrieben und muss die
    # Zwischendatei wieder entfernen.
    monkeypatch.setattr("app.fileops.os.replace", kaputt)
    resp = _upload(c, ("a.pdf", PDF))
    assert resp.status_code == 200
    ergebnis = resp.json()["results"][0]
    assert ergebnis["accepted"] is False and ergebnis["reason"] == "store_failed"
    assert ergebnis["stored_as"] is None
    assert list((tmp_path / "scan-in").iterdir()) == []


def test_upload_ein_fehler_stoppt_die_uebrigen_nicht(api, tmp_path, monkeypatch):
    c, _, _ = api
    import app.main

    original = app.main.store_upload

    def erste_scheitert(source, directory, filename, **kwargs):
        if filename == "a.pdf":
            raise OSError("kaputt")
        return original(source, directory, filename, **kwargs)

    monkeypatch.setattr(app.main, "store_upload", erste_scheitert)
    ergebnis = _upload(c, ("a.pdf", PDF), ("b.pdf", PDF)).json()["results"]
    assert [(r["filename"], r["accepted"], r["reason"]) for r in ergebnis] == [
        ("a.pdf", False, "store_failed"),
        ("b.pdf", True, None),
    ]


def test_upload_ohne_datei_400_no_files(api):
    c, _, _ = api
    resp = c.post("/api/v1/upload")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "no_files"
    # Nicht-Auswahl, wie ein Browser sie sendet: Part mit leerem Dateinamen und leerem Inhalt
    # (httpx lässt `filename=""` weg, darum von Hand gebaut).
    leer = c.post("/api/v1/upload", **_multipart("", b""))
    assert leer.status_code == 400
    assert leer.json()["error"]["code"] == "no_files"


def test_upload_leerer_name_mit_inhalt_ist_unbrauchbarer_name(api, tmp_path):
    c, _, _ = api
    resp = c.post("/api/v1/upload", **_multipart("", PDF))
    assert resp.status_code == 200
    ergebnis = resp.json()["results"][0]
    assert ergebnis["accepted"] is False and ergebnis["reason"] == "unusable_name"
    assert list((tmp_path / "scan-in").iterdir()) == []


def test_upload_ohne_sitzung_401_und_keine_datei(anon, tmp_path):
    c, _, _ = anon
    for headers in ({}, {"Authorization": "Bearer ungueltig"}, EIGENE_HERKUNFT):
        resp = _upload(c, ("a.pdf", PDF), headers=headers)
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "not_authenticated"
    assert list((tmp_path / "scan-in").iterdir()) == []


def test_upload_im_modus_none_ohne_anmeldung(plain, tmp_path):
    c, _, _ = plain
    resp = _upload(c, ("a.pdf", PDF))
    assert resp.status_code == 200 and resp.json()["results"][0]["accepted"] is True
    assert [p.name for p in (tmp_path / "scan-in").iterdir()] == ["a.pdf"]


# --- 2.8 Ende zu Ende: ZUGFeRD über die Schnittstelle, Worker, Ereignisstrom --------------

CII_INVOICE = """<?xml version="1.0" encoding="UTF-8"?>
<rsm:CrossIndustryInvoice xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100">
  <rsm:ExchangedDocument/>
</rsm:CrossIndustryInvoice>"""


async def _asgi_stream(application, path, headers, zeilen, verbunden):
    """Liest einen Ereignisstrom direkt per ASGI im Loop der App, bis die Task abgebrochen
    wird. Sammelt die Zeilen und meldet über `verbunden` den ersten Körperblock."""
    import asyncio

    async def receive():
        await asyncio.sleep(3600)

    async def send(message):
        if message["type"] == "http.response.body" and message.get("body"):
            zeilen.extend(message["body"].decode().splitlines())
            verbunden.set()

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
        "headers": [
            (b"host", b"testserver"),
            *[(k.lower().encode(), v.encode()) for k, v in headers.items()],
        ],
        "client": ("testclient", 1),
        "server": ("testserver", 80),
    }
    await application(scope, receive, send)


def _zugferd_pdf() -> bytes:
    """PDF mit eingebettetem `factur-x.xml` (wie in tests/test_detection.py)."""
    seite = io.BytesIO()
    pdf = canvas.Canvas(seite)
    pdf.drawString(72, 720, "Rechnung")
    pdf.save()
    seite.seek(0)
    ziel = io.BytesIO()
    with pikepdf.open(seite) as doc:
        doc.attachments["factur-x.xml"] = pikepdf.AttachedFileSpec(
            doc, CII_INVOICE.encode("utf-8"), mime_type="text/xml"
        )
        doc.save(ziel)
    return ziel.getvalue()


def test_zugferd_ueber_die_schnittstelle_endet_als_skipped_erechnung(tmp_path, monkeypatch):
    """Anmeldung, Upload mit Zugangsschlüssel (ohne Cookie und Origin), echter Worker (Scan,
    Stabilitätsprüfung, Pipeline) und ein offener Ereignisstrom, der die Kennung des neuen
    Vorgangs liefert. Nur die Wartezeiten des Workers sind verkürzt, die OCR wird nicht
    erreicht (E-Rechnungen laufen deterministisch vorbei)."""
    monkeypatch.setenv("POLL_INTERVAL_SECONDS", "0.1")
    monkeypatch.setenv("STABILITY_WINDOW_SECONDS", "0.3")
    inhalt = _zugferd_pdf()

    with _make_client(tmp_path, monkeypatch) as (c, application, _):
        token = _api_login(c).json()["token"]
        c.cookies.clear()

        # Ereignisstrom im Loop der App öffnen (Worker und EventBus laufen dort).
        zeilen: list[str] = []
        verbunden = threading.Event()
        leser = c.portal.start_task_soon(
            _asgi_stream, application, "/events", _bearer(token), zeilen, verbunden
        )
        assert verbunden.wait(5), "Ereignisstrom hat sich nicht geöffnet"

        resp = _upload(c, ("zugferd.pdf", inhalt), headers=_bearer(token))
        assert resp.status_code == 200
        assert resp.json()["results"][0]["accepted"] is True

        repo = application.state.repo
        ende = time.monotonic() + 15
        doc = None
        while time.monotonic() < ende:
            alle = repo.list_documents()
            if alle and alle[0].status == DocStatus.SKIPPED_ERECHNUNG:
                doc = alle[0]
                break
            time.sleep(0.1)
        leser.cancel()

        assert doc is not None, (
            f"Vorgang endete nicht als skipped_erechnung: {repo.list_documents()}"
        )
        assert doc.original_filename == "zugferd.pdf"
        # Unverändert nach consume, Original nach processed.
        settings = application.state.settings
        assert (settings.consume_dir / "zugferd.pdf").read_bytes() == inhalt
        assert (settings.processed_dir / "zugferd.pdf").read_bytes() == inhalt
        assert not (settings.watch_dir / "zugferd.pdf").exists()
        # Über die Schnittstelle sichtbar, samt Verlauf.
        detail = c.get(f"/api/v1/documents/{doc.id}", headers=_bearer(token)).json()
        assert detail["document"]["status"] == "skipped_erechnung"
        assert detail["document"]["doc_type"] == "erechnung_pdf"
        assert "skipped_erechnung" in [e["event_type"] for e in detail["events"]]
        # Ereignisstrom: Kennung des neuen Vorgangs (Token-Form `doc:<id>`, siehe Bericht).
        assert f"data: doc:{doc.id}" in zeilen


# --- Pfade in Freitexten werden maskiert, Überlauf und unerwartete Fehler ------------------


def test_pfade_in_fehlermeldung_und_verlauf_werden_maskiert(api):
    c, application, _ = api
    settings = application.state.settings
    repo = application.state.repo
    quelle = settings.watch_dir / "Mein Beleg.pdf"
    doc_id = _seed(
        application,
        "Mein Beleg.pdf",
        DocStatus.FAILED,
        error_message=f"Original zuletzt bekannt unter {quelle}",
    )
    repo.update_document(doc_id, source_path=str(quelle))
    repo.add_event(doc_id, EventType.FAILED, f"Fehler bei {quelle}.")
    repo.add_event(
        doc_id,
        EventType.FAILED,
        f"[Errno 13] Permission denied: '{settings.error_dir}/x.pdf' und {settings.consume_dir}/"
        f"y.pdf, DB in {settings.db_path.parent}",
    )

    detail = c.get(f"/api/v1/documents/{doc_id}").json()
    assert detail["document"]["error_message"] == "Original zuletzt bekannt unter Mein Beleg.pdf"
    meldungen = [e["message"] for e in detail["events"]]
    assert meldungen[0] == "Fehler bei Mein Beleg.pdf."
    assert "x.pdf" in meldungen[1] and "y.pdf" in meldungen[1]
    liste = c.get("/api/v1/documents").json()["documents"][0]
    assert liste["error_message"] == "Original zuletzt bekannt unter Mein Beleg.pdf"
    wurzel = str(settings.watch_dir.parent)
    assert wurzel not in c.get(f"/api/v1/documents/{doc_id}").text
    assert wurzel not in c.get("/api/v1/documents").text
    # Gespeichert bleibt der Originaltext.
    assert str(quelle) in repo.get_document(doc_id).error_message


GROSS = 99999999999999999999


def test_ueberlauf_offset_wird_begrenzt(api):
    c, application, _ = api
    _seed(application, "a.pdf")
    resp = c.get("/api/v1/documents", params={"offset": GROSS})
    assert resp.status_code == 200
    assert resp.json()["offset"] == 2**63 - 1 and resp.json()["documents"] == []


@pytest.mark.parametrize("kennung", [GROSS, 2**63, 0, -5])
def test_kennung_ausserhalb_des_bereichs_ist_404(api, kennung):
    c, _, _ = api
    for antwort in (
        c.get(f"/api/v1/documents/{kennung}"),
        c.post(f"/api/v1/documents/{kennung}/release"),
        c.post(f"/api/v1/documents/{kennung}/discard"),
    ):
        assert antwort.status_code == 404
        assert antwort.json()["error"]["code"] == "not_found"


def test_kennung_obergrenze_wird_noch_gefragt(api):
    c, _, _ = api
    assert c.get(f"/api/v1/documents/{2**63 - 1}").status_code == 404


def test_unerwarteter_fehler_unter_api_ist_json_500_und_wird_protokolliert(
    api, monkeypatch, caplog
):
    c, application, _ = api

    def kaputt(*args, **kwargs):
        raise RuntimeError("unerwartet")

    monkeypatch.setattr(application.state.repo, "list_documents", kaputt)
    c._transport.raise_server_exceptions = False
    with caplog.at_level(logging.ERROR, logger="lector.api"):
        resp = c.get("/api/v1/documents")
    assert resp.status_code == 500
    assert resp.json()["error"]["code"] == "internal_error"
    assert resp.json()["error"]["message"]
    assert "unerwartet" not in resp.text
    assert "unerwartet" in caplog.text
