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
