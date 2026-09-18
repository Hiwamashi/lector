import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WATCH_DIR", str(tmp_path / "scan-in"))
    monkeypatch.setenv("CONSUME_DIR", str(tmp_path / "consume"))
    monkeypatch.setenv("PROCESSED_DIR", str(tmp_path / "processed"))
    monkeypatch.setenv("ERROR_DIR", str(tmp_path / "error"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "data" / "lector.db"))

    import app.config
    import app.main

    app.config.get_settings.cache_clear()
    importlib.reload(app.main)
    with TestClient(app.main.app) as c:
        yield c, app.main.app


def test_healthz(client):
    c, _ = client
    assert c.get("/healthz").json() == {"status": "ok"}


def test_dashboard_empty(client):
    c, _ = client
    resp = c.get("/")
    assert resp.status_code == 200
    assert "Lector" in resp.text
    assert "Keine Dokumente." in resp.text


def test_dashboard_shows_document_and_detail(client):
    c, application = client
    repo = application.state.repo
    doc_id = repo.create_document(
        original_filename="rechnung.pdf", source_path="/scan-in/rechnung.pdf"
    )

    resp = c.get("/")
    assert "rechnung.pdf" in resp.text

    detail = c.get(f"/documents/{doc_id}")
    assert detail.status_code == 200
    assert "rechnung.pdf" in detail.text
    assert "Verlauf" in detail.text


def test_history_fragment_filter_by_status(client):
    c, application = client
    repo = application.state.repo
    from app.models import DocStatus

    a = repo.create_document(original_filename="a.pdf", source_path="/x/a.pdf")
    repo.create_document(original_filename="b.pdf", source_path="/x/b.pdf")
    repo.set_status(a, DocStatus.DONE)

    frag = c.get("/fragment/history", params={"status": "done"})
    assert "a.pdf" in frag.text
    assert "b.pdf" not in frag.text


def test_detail_404(client):
    c, _ = client
    assert c.get("/documents/99999").status_code == 404


def test_invoices_list_shows_date_and_sort_headers(client):
    c, application = client
    repo = application.state.repo
    repo.upsert_invoice(
        paperless_id=1, title="Strom", correspondent="Stadtwerke", document_date="2026-06-06"
    )

    resp = c.get("/invoices")
    assert resp.status_code == 200
    assert "Datum" in resp.text
    assert "sort-arrow" in resp.text
    assert "06.06.2026" in resp.text


def test_invoices_sorting_changes_order(client):
    c, application = client
    repo = application.state.repo
    repo.upsert_invoice(
        paperless_id=1, title="Beta", correspondent=None, document_date="2026-03-01"
    )
    repo.upsert_invoice(
        paperless_id=2, title="Alpha", correspondent=None, document_date="2026-01-01"
    )

    frag = c.get("/fragment/invoices", params={"sort": "title", "dir": "asc"})
    assert frag.text.index("Alpha") < frag.text.index("Beta")


def test_sort_links_url_encode_filters(client):
    c, _ = client
    # Suchbegriff mit Sonderzeichen, die einen Query-String zerstören würden.
    resp = c.get("/invoices", params={"q": "Müller & Co=1"})
    assert resp.status_code == 200
    # Roh eingesetzt würde "&" einen zusätzlichen Parameter erzeugen → muss kodiert sein.
    assert "q=M%C3%BCller%20%26%20Co%3D1" in resp.text or "q=M%C3%BCller+%26+Co%3D1" in resp.text
    assert "&q=Müller & Co=1" not in resp.text


def test_invoice_detail_shows_document_date(client):
    c, application = client
    repo = application.state.repo
    inv_id = repo.upsert_invoice(
        paperless_id=7, title="Miete", correspondent=None, document_date="2026-06-06"
    )

    detail = c.get(f"/invoices/{inv_id}")
    assert detail.status_code == 200
    assert "Dokumentdatum" in detail.text
    assert "06.06.2026" in detail.text


def test_recipients_page_without_paperless_shows_hint(client):
    # Ohne PAPERLESS_URL/TOKEN ist das Feature deaktiviert → Hinweis statt Fehler.
    c, _ = client
    resp = c.get("/empfaenger")
    assert resp.status_code == 200
    assert "Paperless-Anbindung fehlt" in resp.text


def test_recipients_set_without_paperless_redirects(client):
    c, _ = client
    resp = c.post("/empfaenger/5", data={"recipient": "Sascha"}, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/empfaenger")


def test_recipients_suggest_batch_route_not_shadowed(client):
    # Regression: Die parametrisierte Route /empfaenger/{paperless_id} darf die statische
    # Batch-Route nicht verschlucken. Starlette matcht in Registrierungsreihenfolge —
    # stand die parametrisierte zuerst, lief der Batch-Klick in einen 422
    # (int_parsing, input="suggest-batch") statt den Lauf zu starten.
    c, _ = client
    resp = c.post("/empfaenger/suggest-batch", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/empfaenger")


def test_recipients_stop_route_reachable(client):
    c, _ = client
    resp = c.post("/empfaenger/suggest-batch/stop", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/empfaenger")


def test_batch_status_fragment_without_paperless(client):
    c, _ = client
    resp = c.get("/fragment/empfaenger/batch-status")
    assert resp.status_code == 200


def test_batch_limit_is_clamped(client, monkeypatch):
    # Ein absurd hohes Limit darf die Obergrenze aus den Settings nicht überschreiten.
    c, application = client
    seen = {}
    monkeypatch.setattr(
        application.state.sync, "start_batch", lambda limit=None: seen.update(limit=limit)
    )
    c.post("/empfaenger/suggest-batch", data={"limit": "999999"}, follow_redirects=False)
    assert seen["limit"] == application.state.sync.settings.recipient_batch_max

    c.post("/empfaenger/suggest-batch", data={"limit": "keine-zahl"}, follow_redirects=False)
    assert seen["limit"] >= 1


def test_no_route_is_shadowed_by_a_parametrised_one():
    """Generischer Schutz gegen die 422-Falle aus dem suggest-batch-Fehler.

    Starlette matcht Routen in Registrierungsreihenfolge. Steht eine parametrisierte
    Route vor einer statischen gleicher Segmentzahl, verschluckt sie diese.
    """
    import app.main as m

    routes = []
    for r in m.app.routes:
        for method in sorted(getattr(r, "methods", []) or []):
            if method in ("HEAD", "OPTIONS"):
                continue
            routes.append((method, r.path))

    def segments(path):
        return [("*" if s.startswith("{") else s) for s in path.strip("/").split("/")]

    shadowed = []
    for i, (m1, p1) in enumerate(routes):
        for m2, p2 in routes[i + 1 :]:
            if m1 != m2:
                continue
            a, b = segments(p1), segments(p2)
            if len(a) != len(b) or a == b:
                continue
            if all(x == "*" or x == y for x, y in zip(a, b, strict=True)):
                shadowed.append(f"{m1} {p1} verdeckt {m2} {p2}")

    assert shadowed == []


async def test_batch_status_skips_missing_count_without_llm_feature(client, monkeypatch):
    """Regression (Review-Befund A): Ist Paperless verbunden, aber das KI-Feature aus,
    darf der teure Netzwerk-Zählaufruf nicht laufen — ``batch_status.html`` blendet den
    Block dann ohnehin per ``recipient_enabled and feature_llm`` aus."""
    c, application = client
    sync = application.state.sync
    monkeypatch.setattr(type(sync), "recipient_enabled", property(lambda self: True))
    monkeypatch.setattr(type(sync), "recipient_llm_enabled", property(lambda self: False))
    calls = 0

    async def spy(*_a, **_kw):
        nonlocal calls
        calls += 1
        return 42

    monkeypatch.setattr(sync, "count_missing_recipients", spy)

    resp = c.get("/fragment/empfaenger/batch-status")
    assert resp.status_code == 200
    assert calls == 0


async def test_batch_status_default_limit_never_exceeds_batch_max(client, monkeypatch):
    """Regression (Review-Befund B): Bei kleinem ``RECIPIENT_BATCH_MAX`` darf die
    Vorbelegung des Mengenfelds nicht über sein eigenes ``max`` hinausgehen — sonst
    blockiert die HTML5-Constraint-Validierung das Absenden des Formulars."""
    import app.main as m

    c, application = client
    sync = application.state.sync
    monkeypatch.setattr(type(sync), "recipient_enabled", property(lambda self: True))
    monkeypatch.setattr(type(sync), "recipient_llm_enabled", property(lambda self: True))
    monkeypatch.setattr(sync.settings, "recipient_batch_max", 50)

    async def spy(*_a, **_kw):
        return 500

    monkeypatch.setattr(sync, "count_missing_recipients", spy)

    resp = c.get("/fragment/empfaenger/batch-status")
    assert resp.status_code == 200

    class _FakeRequest:
        app = application

    ctx = await m._batch_status_context(_FakeRequest())
    assert ctx["batch_max"] == 50
    assert ctx["default_limit"] <= ctx["batch_max"]


def test_recipients_page_shows_batch_toolbar_container(client):
    # Ohne Paperless bleibt die Toolbar leer, der Container mit data-fragment
    # muss aber da sein — sonst kann das Live-Update nicht greifen.
    c, _ = client
    resp = c.get("/empfaenger")
    assert 'id="batch-status"' in resp.text
    assert 'data-fragment="/fragment/empfaenger/batch-status"' in resp.text
