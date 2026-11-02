"""Web-Tests der Paperless-Dokumentansicht (Change paperless-dokumentansicht, Gruppen 2 und 3):
Seite, Fragment, Vorschau-Proxy, Weiterleitung der Rechnungsadresse, Leisten-Antwort der
Aktionen und die Seitenleiste der drei Listen. Paperless selbst ist durch den Stub aus
``test_web._fake_document_view`` ersetzt."""

from __future__ import annotations

import dataclasses
import importlib
import re

import httpx
import pytest
from fastapi.testclient import TestClient
from test_web import (
    _fake_document_view,
    _invoice,
    _rechnungsbereich_an,
    _setup_test_environment,
    _sevdesk_on,
)

import app.config
import app.main
from app.paperless_sync import PaperlessSync

PANEL = {"X-Lector-Panel": "1"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Frisch geladene App wie in test_web.py, mit Stub für die Paperless-Abrufe."""
    _setup_test_environment(monkeypatch, tmp_path)
    app.config.get_settings.cache_clear()
    importlib.reload(app.main)
    _fake_document_view(monkeypatch)
    with TestClient(app.main.app) as c:
        yield c, app.main.app


def _row(html: str, row_id: int) -> str:
    """Das öffnende ``<tr>`` der Zeile mit ``data-row-id``."""
    return re.search(rf'<tr data-row-id="{row_id}"[^>]*>', html).group(0)


def _panel(html: str) -> str:
    """Inhalt der Seitenleiste ``<aside id="panel">`` (leer, wenn es keine gibt)."""
    m = re.search(r'<aside id="panel".*?</aside>', html, re.S)
    return m.group(0) if m else ""


# ---- 2.1 Vorschau-Proxy -------------------------------------------------------------


def test_paperless_preview_serves_pdf_with_frame_headers_and_cache(client, monkeypatch):
    c, application = client

    async def fake_preview(paperless_id):
        assert paperless_id == 77
        return b"%PDF-1.4 x", "application/pdf"

    monkeypatch.setattr(application.state.sync, "fetch_document_preview", fake_preview)
    resp = c.get("/paperless/77/preview")
    assert resp.status_code == 200
    assert resp.content == b"%PDF-1.4 x"
    assert resp.headers["x-frame-options"] == "SAMEORIGIN"
    assert "script-src 'none'" in resp.headers["content-security-policy"]
    assert resp.headers["cache-control"] == "private, max-age=300"


def test_paperless_preview_rejects_active_content_and_maps_errors(client, monkeypatch):
    c, application = client
    sync = application.state.sync

    async def html(_):
        return b"<script>1</script>", "text/html"

    monkeypatch.setattr(sync, "fetch_document_preview", html)
    assert c.get("/paperless/1/preview").status_code == 415

    async def missing(_):
        return None

    monkeypatch.setattr(sync, "fetch_document_preview", missing)
    assert c.get("/paperless/1/preview").status_code == 404

    async def boom(_):
        raise httpx.ConnectError("weg")

    monkeypatch.setattr(sync, "fetch_document_preview", boom)
    assert c.get("/paperless/1/preview").status_code == 502


def test_paperless_preview_id_must_be_an_integer(client):
    c, _ = client
    assert c.get("/paperless/abc/preview").status_code == 404
    assert c.get("/paperless/..%2Fusers/preview").status_code == 404


def test_invoice_preview_delegates_and_carries_cache_header(client, monkeypatch):
    c, application = client

    async def fake_preview(invoice_id):
        return b"%PDF", "application/pdf"

    monkeypatch.setattr(application.state.sync, "fetch_preview", fake_preview)
    resp = c.get("/invoices/1/preview")
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "private, max-age=300"


# ---- 2.2 / 3.1 Seite und Fragment ---------------------------------------------------


def test_view_page_shows_invoice_section_tags_without_controls_and_paperless_link(
    client, monkeypatch
):
    _rechnungsbereich_an(monkeypatch)
    c, application = client
    _invoice(application.state.repo, 5, "Strom Mai", correspondent="Stadtwerke")
    application.state.settings.paperless_public_url = "https://paperless.example"

    resp = c.get("/paperless/5")
    assert resp.status_code == 200
    html = resp.text
    assert "Strom Mai" in html
    assert 'data-fragment="/fragment/paperless/5"' in html
    assert 'data="/paperless/5/preview"' in html
    assert 'href="https://paperless.example/documents/5/details"' in html
    assert "In Paperless öffnen ↗" in html
    assert 'id="context-section"' in html  # Rechnungsbereich
    assert 'data-panel-form action="/invoices/' in html
    # Tags erscheinen, aber ohne Bedienelement (kein Formular zu Tags).
    assert "steuer" in html
    assert "/tags" not in html and 'name="tags"' not in html
    # Fehlende Angaben stehen als „—“, nicht als Auslassung.
    assert "<dt>Archivnummer (ASN)</dt><dd>—</dd>" in html


def test_view_fragment_equals_page_body(client, monkeypatch):
    _rechnungsbereich_an(monkeypatch)
    c, application = client
    _invoice(application.state.repo, 5, "Strom Mai")
    frag = c.get("/fragment/paperless/5")
    assert frag.status_code == 200
    assert "<html" not in frag.text
    assert "Strom Mai" in frag.text and 'id="context-section"' in frag.text
    assert "data-panel-close" in frag.text


def test_view_without_invoice_has_no_invoice_section_but_editable_recipient(client, monkeypatch):
    c, application = client
    monkeypatch.setattr(PaperlessSync, "recipient_enabled", property(lambda self: True))
    original = PaperlessSync.load_document_view

    async def with_recipient(self, paperless_id):
        view = await original(self, paperless_id)
        return dataclasses.replace(
            view,
            recipient_field_present=True,
            recipient_options=["Familie", "Firma"],
            current_recipient="Familie",
        )

    monkeypatch.setattr(PaperlessSync, "load_document_view", with_recipient)
    html = c.get("/fragment/paperless/321").text
    assert "Dokument 321" in html
    assert 'id="context-section"' not in html and "invoice-actions" not in html
    assert 'action="/empfaenger/321"' in html
    assert "data-panel-form" in html
    assert '<option value="Familie" selected>' in html


def test_view_invoice_section_hidden_when_sync_disabled(client):
    c, application = client
    _invoice(application.state.repo, 5, "Strom Mai")
    html = c.get("/paperless/5").text  # sync.enabled ist in der Testumgebung aus
    assert "Strom Mai" in html and 'id="context-section"' not in html


def test_view_unknown_id_and_disabled_connection_are_404(client, monkeypatch):
    c, _ = client
    for url in ("/paperless/404404", "/fragment/paperless/404404"):
        assert c.get(url).status_code == 404
    assert "nicht gefunden" in c.get("/paperless/404404").text

    monkeypatch.setattr(PaperlessSync, "view_enabled", property(lambda self: False))
    assert c.get("/paperless/5").status_code == 404
    assert c.get("/fragment/paperless/5").status_code == 404
    assert c.get("/paperless/5/preview").status_code == 404


def test_view_paperless_unreachable_shows_hint(client, monkeypatch):
    c, _ = client

    async def down(self, paperless_id):
        raise httpx.ConnectError("weg")

    monkeypatch.setattr(PaperlessSync, "load_document_view", down)
    page = c.get("/paperless/5")
    assert page.status_code == 503 and "nicht erreichbar" in page.text
    frag = c.get("/fragment/paperless/5")
    assert frag.status_code == 503 and '<p class="alert">' in frag.text


def test_view_fragment_passes_ask_through(client, monkeypatch):
    _rechnungsbereich_an(monkeypatch)
    c, application = client
    _sevdesk_on(application, monkeypatch)
    inv_id = _invoice(application.state.repo, 1, "Privat", correspondent="Kita", label="Familie")
    assert "Vor dem Export klären" in c.get("/fragment/paperless/1?ask=1").text
    assert "Vor dem Export klären" not in c.get("/fragment/paperless/1").text
    assert "?ask=1" in c.get("/paperless/1?ask=1").text
    assert inv_id


# ---- 2.3 Alte Rechnungsadresse ------------------------------------------------------


def test_old_invoice_address_redirects_and_unknown_invoice_is_404(client):
    c, application = client
    inv_id = _invoice(application.state.repo, 42, "Strom")
    resp = c.get(f"/invoices/{inv_id}", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/paperless/42"
    ask = c.get(f"/invoices/{inv_id}?ask=1", follow_redirects=False)
    assert ask.headers["location"] == "/paperless/42?ask=1"
    assert c.get("/invoices/9999", follow_redirects=False).status_code == 404

    frag = c.get(f"/fragment/invoices/{inv_id}")
    assert frag.status_code == 200 and "Strom" in frag.text
    assert c.get("/fragment/invoices/9999").status_code == 404


# ---- 2.4 Leisten-Antwort der Aktionen -----------------------------------------------


def _match_setup(application, monkeypatch, inv_id):
    from app.models import InvoiceVoucherMatch, MatchKind, SevdeskVoucher

    repo = application.state.repo
    repo.replace_vouchers(
        [SevdeskVoucher(voucher_id="987", voucher_date="2026-10-04", supplier_name="AWS",
                        sum_gross=20.0, currency="EUR")]
    )
    repo.set_sevdesk_sync_success()
    repo.replace_auto_matches(
        [
            InvoiceVoucherMatch(
                invoice_id=inv_id, voucher_id="987", kind=MatchKind.SIMILAR, score=0.8
            )
        ]
    )
    monkeypatch.setattr(application.state.sync, "recompute_matches", lambda: 0)


@pytest.mark.parametrize(
    ("path", "data", "plain", "panel"),
    [
        ("/invoices/{id}/giro", {}, "/invoices/{id}", "/fragment/paperless/{pid}"),
        ("/invoices/{id}/dismiss", {}, "/invoices/{id}", "/fragment/paperless/{pid}"),
        ("/invoices/{id}/paid", {"paid": "true"}, "/invoices/{id}", "/fragment/paperless/{pid}"),
        (
            "/invoices/{id}/matches/987",
            {"decision": "confirm"},
            "/invoices/{id}",
            "/fragment/paperless/{pid}",
        ),
        (
            "/invoices/{id}/export",
            {},
            "/invoices/{id}?ask=1",
            "/fragment/paperless/{pid}?ask=1",
        ),
        (
            "/invoices/{id}/export",
            {"confirm": "1"},
            "/invoices/{id}",
            "/fragment/paperless/{pid}",
        ),
        (
            "/empfaenger/{pid}",
            {"recipient": "Familie"},
            "/empfaenger?page=1",
            "/fragment/paperless/{pid}",
        ),
        (
            "/empfaenger/{pid}",
            {"recipient": "Familie", "view": "doc"},
            "/paperless/{pid}",
            "/fragment/paperless/{pid}",
        ),
        ("/empfaenger/{pid}/suggest", {}, "/empfaenger?page=1", "/fragment/paperless/{pid}"),
    ],
)
def test_action_redirect_target_depends_on_panel_header(
    client, monkeypatch, path, data, plain, panel
):
    c, application = client
    sync = application.state.sync
    inv_id = _invoice(application.state.repo, 7, "Hosting", label="Familie", amount=20.0)
    _match_setup(application, monkeypatch, inv_id)
    _sevdesk_on(application, monkeypatch)

    async def noop(*_a, **_kw):
        return None

    async def export(invoice_id, confirmed=False):
        from app.sevdesk_export_checks import ExportOutcome, ExportStatus

        status = ExportStatus.EXPORTED if confirmed else ExportStatus.NEEDS_CONFIRMATION
        return ExportOutcome(status=status, reasons=["x"])

    for name in ("save_giro_edits", "set_paid", "set_recipient", "suggest_recipient"):
        monkeypatch.setattr(sync, name, noop)
    monkeypatch.setattr(sync, "export_invoice", export)
    path = path.format(id=inv_id, pid=7)

    without = c.post(path, data=data, follow_redirects=False)
    assert without.status_code == 303
    assert without.headers["location"] == plain.format(id=inv_id, pid=7)

    with_header = c.post(path, data=data, headers=PANEL, follow_redirects=False)
    assert with_header.status_code == 303
    assert with_header.headers["location"] == panel.format(id=inv_id, pid=7)


def test_panel_header_does_not_bypass_origin_check_in_paperless_mode(tmp_path, monkeypatch):
    from test_web_auth import EIGENE_HERKUNFT, _login, _make_client

    with _make_client(tmp_path, monkeypatch, mode="paperless") as (c, application, _):
        inv_id = _invoice(application.state.repo, 7, "Hosting")
        _login(c)
        fremd = c.post(
            f"/invoices/{inv_id}/dismiss",
            headers={**PANEL, "Origin": "https://fremd.example"},
            follow_redirects=False,
        )
        assert fremd.status_code == 403
        ohne = c.post(f"/invoices/{inv_id}/dismiss", headers=PANEL, follow_redirects=False)
        assert ohne.status_code == 403
        eigene = c.post(
            f"/invoices/{inv_id}/dismiss",
            headers={**PANEL, **EIGENE_HERKUNFT},
            follow_redirects=False,
        )
        assert eigene.status_code == 303
        assert eigene.headers["location"] == "/fragment/paperless/7"


# ---- 3.2 / 3.3 Seitenleiste der Listen ---------------------------------------------


def test_invoice_list_rows_carry_panel_attributes_and_link_to_the_page(client):
    c, application = client
    inv_id = _invoice(application.state.repo, 9, "Wasser", correspondent="Stadtwerke")
    html = c.get("/invoices").text
    row = _row(html, inv_id)
    assert 'data-panel-url="/fragment/paperless/9"' in row
    assert 'data-page-url="/paperless/9"' in row
    assert 'data-paperless-id="9"' in row
    assert "aria-current" not in row
    assert 'href="/paperless/9"' in html  # Titel-Link funktioniert ohne JS
    assert ">Details<" not in html  # Details-Spalte entfällt
    assert 'class="col-secondary"' in html
    assert re.search(r'<aside id="panel"[^>]*\bhidden', html)
    assert "has-panel" not in html


def test_invoice_list_with_doc_renders_panel_and_marks_row(client, monkeypatch):
    _rechnungsbereich_an(monkeypatch)
    c, application = client
    inv_id = _invoice(application.state.repo, 9, "Wasser", correspondent="Stadtwerke")
    _invoice(application.state.repo, 10, "Gas")
    html = c.get("/invoices", params={"doc": 9, "q": "Wasser"}).text
    assert "container--wide has-panel" in html
    panel = _panel(html)
    assert 'data-fragment="/fragment/paperless/9"' in panel
    assert "Wasser" in panel and 'id="context-section"' in panel
    row = _row(html, inv_id)
    assert 'aria-current="true"' in row
    # Zeilen-Fragment markiert die Zeile ebenfalls, wenn doc mitgegeben wird.
    assert 'aria-current="true"' in c.get("/fragment/invoices", params={"doc": 9}).text
    # Unbekannte Dokument-ID: Liste ohne Leiste.
    unknown = c.get("/invoices", params={"doc": 404404}).text
    assert "has-panel" not in unknown and "hidden>" in unknown


def test_invoice_list_panel_shows_hint_when_paperless_is_down(client, monkeypatch):
    c, application = client
    _invoice(application.state.repo, 9, "Wasser")

    async def down(self, paperless_id):
        raise httpx.ConnectError("weg")

    monkeypatch.setattr(PaperlessSync, "load_document_view", down)
    resp = c.get("/invoices", params={"doc": 9})
    assert resp.status_code == 200
    assert "Wasser" in resp.text  # die Liste bleibt bedienbar
    assert "nicht erreichbar" in _panel(resp.text)


def test_invoice_list_without_connection_has_no_panel(client, monkeypatch):
    c, application = client
    inv_id = _invoice(application.state.repo, 9, "Wasser")
    monkeypatch.setattr(PaperlessSync, "view_enabled", property(lambda self: False))
    html = c.get("/invoices", params={"doc": 9}).text
    assert "<aside" not in html and "data-panel-url" not in html
    assert f'href="/invoices/{inv_id}"' in html


def _recipient_list_setup(monkeypatch):
    from app.models import RecipientRow
    from app.paperless import DocumentPage

    monkeypatch.setattr(PaperlessSync, "recipient_enabled", property(lambda self: True))

    async def fake_list(self, **_kw):
        rows = [
            RecipientRow(
                paperless_id=pid,
                title=f"Beleg {pid}",
                correspondent="Telekom",
                document_date=None,
                current_recipient=None,
            )
            for pid in (31, 32)
        ]
        return rows, DocumentPage(documents=[], count=2, page=1, page_size=50), None

    monkeypatch.setattr(PaperlessSync, "list_recipient_documents", fake_list)


def test_recipient_list_titles_link_and_panel_opens_with_doc(client, monkeypatch):
    c, _ = client
    _recipient_list_setup(monkeypatch)
    html = c.get("/empfaenger").text
    row = _row(html, 31)
    assert 'data-panel-url="/fragment/paperless/31"' in row
    assert 'data-page-url="/paperless/31"' in row
    assert '<a href="/paperless/31">Beleg 31</a>' in html
    assert "has-panel" not in html and " hidden>" in html

    opened = c.get("/empfaenger", params={"doc": 32}).text
    assert 'class="container has-panel"' in opened
    assert "Dokument 32" in _panel(opened)
    row32 = _row(opened, 32)
    assert 'aria-current="true"' in row32
    assert "aria-current" not in _row(opened, 31)


def test_dashboard_panel_shows_document_details_from_lector(client):
    c, application = client
    doc_id = application.state.repo.create_document(
        original_filename="scan-17.pdf", source_path="/scan-in/scan-17.pdf"
    )
    html = c.get("/").text
    row = _row(html, doc_id)
    assert f'data-panel-url="/fragment/documents/{doc_id}"' in row
    assert f'data-page-url="/documents/{doc_id}"' in row
    assert f'href="/documents/{doc_id}"' in html  # Link funktioniert ohne JS
    assert "hidden>" in html and "has-panel" not in html

    opened = c.get("/", params={"doc": doc_id}).text
    panel = _panel(opened)
    assert f'data-fragment="/fragment/documents/{doc_id}"' in panel
    assert "scan-17.pdf" in panel  # Stammdaten
    assert "<h2>Verlauf</h2>" in panel
    assert 'aria-current="true"' in _row(opened, doc_id)
    # Unbekannte ID: Liste ohne Leiste.
    assert "has-panel" not in c.get("/", params={"doc": 99999}).text
