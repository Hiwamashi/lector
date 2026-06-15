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
