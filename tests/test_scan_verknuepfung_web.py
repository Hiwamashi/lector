"""Web-Tests der Vorgangsansicht mit Paperless-Bezug (Change scan-paperless-verknuepfung,
Gruppe 5): Auslieferung des lokalen Originals, kombinierte Leiste in allen Zuständen der
Verknüpfung und der Rückweg ``back=doc:<id>`` der eingebetteten Aktionen."""

from __future__ import annotations

import dataclasses
import hashlib
import importlib
import re

import httpx
import pytest
from fastapi.testclient import TestClient
from test_web import (
    _fake_document_view,
    _invoice,
    _setup_test_environment,
    _sevdesk_on,
)

import app.config
import app.main
from app.models import DocStatus, DocType, PaperlessLink
from app.paperless_sync import PaperlessSync

PANEL = {"X-Lector-Panel": "1"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    _setup_test_environment(monkeypatch, tmp_path)
    app.config.get_settings.cache_clear()
    importlib.reload(app.main)
    _fake_document_view(monkeypatch)
    with TestClient(app.main.app) as c:
        yield c, app.main.app


def _doc(
    application,
    name="scan.pdf",
    *,
    status=DocStatus.DONE,
    link=None,
    paperless_id=None,
    error_message=None,
    **fields,
):
    repo = application.state.repo
    doc_id = repo.create_document(
        original_filename=name,
        source_path=f"/scan-in/{name}",
        file_hash=fields.pop("file_hash", None),
    )
    repo.set_status(doc_id, status, error_message=error_message)
    repo.update_document(doc_id, paperless_link=link, paperless_id=paperless_id, **fields)
    return doc_id


def _file(directory, name, content=b"%PDF-1.4 original"):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(content)
    return path


def _processed(application):
    return application.state.settings.processed_dir


def _error(application):
    return application.state.settings.error_dir


def _assert_one_bar_one_title(html: str) -> None:
    assert html.count('id="panel-title"') == 1
    assert html.count('class="panel-bar"') == 1


# ---- 5.1 Original ausliefern ----------------------------------------------------------


def test_original_pdf_is_served_with_preview_protection(client):
    c, application = client
    path = _file(_processed(application), "scan.pdf")
    doc_id = _doc(application, original_path=str(path))
    resp = c.get(f"/documents/{doc_id}/original")
    assert resp.status_code == 200
    assert resp.content == b"%PDF-1.4 original"
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.headers["x-frame-options"] == "SAMEORIGIN"
    assert "script-src 'none'" in resp.headers["content-security-policy"]
    assert resp.headers["x-content-type-options"] == "nosniff"


def test_original_image_is_served_inline_from_error_dir(client):
    c, application = client
    path = _file(_error(application), "foto.png", b"\x89PNG fake")
    doc_id = _doc(application, "foto.png", status=DocStatus.FAILED, original_path=str(path))
    resp = c.get(f"/documents/{doc_id}/original")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert "content-disposition" not in resp.headers


def test_original_xml_is_an_attachment_with_safe_filename(client):
    c, application = client
    path = _file(_processed(application), "Rechnung Müller.xml", b"<Invoice/>")
    doc_id = _doc(
        application,
        "Rechnung Müller.xml",
        status=DocStatus.SKIPPED_ERECHNUNG,
        doc_type=DocType.ERECHNUNG_XML,
        original_path=str(path),
    )
    resp = c.get(f"/documents/{doc_id}/original")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/xml")
    assert resp.headers["x-content-type-options"] == "nosniff"
    disposition = resp.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert "filename*=UTF-8''Rechnung%20M%C3%BCller.xml" in disposition
    assert 'filename="Rechnung_Mller.xml"' in disposition


def test_original_deleted_file_and_unknown_document_are_404(client):
    c, application = client
    path = _file(_processed(application), "weg.pdf")
    doc_id = _doc(application, "weg.pdf", original_path=str(path))
    path.unlink()
    assert c.get(f"/documents/{doc_id}/original").status_code == 404
    assert c.get("/documents/99999/original").status_code == 404


def test_original_outside_processed_and_error_dir_is_never_served(client):
    c, application = client
    settings = application.state.settings
    in_consume = _file(settings.consume_dir, "ergebnis.pdf")
    elsewhere = _file(settings.processed_dir.parent / "fremd", "geheim.pdf")
    # Auch ein Pfad, der nur per `..` aus processed herausführt, zählt als außerhalb.
    traversal = settings.processed_dir / ".." / "fremd" / "geheim.pdf"
    for candidate in (in_consume, elsewhere, traversal):
        doc_id = _doc(application, "x.pdf", original_path=str(candidate))
        assert c.get(f"/documents/{doc_id}/original").status_code == 404


def test_original_symlink_out_of_processed_dir_is_refused(client, tmp_path):
    c, application = client
    target = _file(tmp_path / "fremd", "ziel.pdf")
    link = _processed(application) / "link.pdf"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target)
    doc_id = _doc(application, "link.pdf", original_path=str(link))
    assert c.get(f"/documents/{doc_id}/original").status_code == 404


def test_original_path_is_found_lazily_for_old_entries_and_stored(client):
    c, application = client
    content = b"%PDF-1.4 alt"
    # Namenszusatz `_1` wie bei `unique_target`; der Hash bestätigt den Treffer.
    path = _file(_processed(application), "alt_1.pdf", content)
    doc_id = _doc(application, "alt.pdf", file_hash=hashlib.sha256(content).hexdigest())
    assert application.state.repo.get_document(doc_id).original_path is None
    resp = c.get(f"/documents/{doc_id}/original")
    assert resp.status_code == 200 and resp.content == content
    assert application.state.repo.get_document(doc_id).original_path == str(path)


def test_original_lazy_search_needs_matching_hash_and_finds_error_dir(client):
    c, application = client
    _file(_processed(application), "name.pdf", b"anderer Inhalt")
    wrong = _doc(application, "name.pdf", file_hash=hashlib.sha256(b"x").hexdigest())
    assert c.get(f"/documents/{wrong}/original").status_code == 404
    content = b"%PDF fehler"
    _file(_error(application), "kaputt.pdf", content)
    failed = _doc(
        application,
        "kaputt.pdf",
        status=DocStatus.FAILED,
        file_hash=hashlib.sha256(content).hexdigest(),
    )
    assert c.get(f"/documents/{failed}/original").status_code == 200


def test_original_of_unfinished_document_is_not_served(client):
    c, application = client
    _file(_processed(application), "laeuft.pdf")
    doc_id = _doc(application, "laeuft.pdf", status=DocStatus.PROCESSING)
    assert c.get(f"/documents/{doc_id}/original").status_code == 404


# ---- 5.2 Kombinierte Leiste -----------------------------------------------------------


def _with_recipient(monkeypatch):
    """Gibt der Paperless-Ansicht das Empfängerformular (eingebettete Aktion)."""
    monkeypatch.setattr(PaperlessSync, "recipient_enabled", property(lambda self: True))
    original = PaperlessSync.load_document_view

    async def with_recipient(self, paperless_id):
        view = await original(self, paperless_id)
        if view is None:
            return None
        return dataclasses.replace(
            view,
            recipient_field_present=True,
            recipient_options=["Familie"],
            current_recipient=None,
        )

    monkeypatch.setattr(PaperlessSync, "load_document_view", with_recipient)


def test_linked_document_embeds_paperless_view_with_one_title_and_closed_log(client, monkeypatch):
    c, application = client
    _with_recipient(monkeypatch)
    doc_id = _doc(application, "scan-1.pdf", link=PaperlessLink.LINKED, paperless_id=5)
    html = c.get(f"/fragment/documents/{doc_id}").text
    _assert_one_bar_one_title(html)
    assert '<h1 id="panel-title" tabindex="-1">scan-1.pdf</h1>' in html
    assert 'class="badge badge--link-linked"' in html
    assert 'href="/paperless/5">in Paperless #5</a>' in html
    assert "über Dateinamen" not in html
    assert '<h2 class="doc-title">Dokument 5</h2>' in html
    assert 'data="/paperless/5/preview"' in html
    assert "Angaben aus Paperless" in html
    assert '<details class="doc-log">' in html  # fertig: eingeklappt
    assert "/documents/" + str(doc_id) + "/original" not in html
    # Eingebettete Aktionen tragen den Rückweg zur kombinierten Leiste.
    assert f'<input type="hidden" name="back" value="doc:{doc_id}" />' in html


def test_linked_by_name_is_marked(client):
    c, application = client
    doc_id = _doc(application, link=PaperlessLink.LINKED_BY_NAME, paperless_id=5)
    html = c.get(f"/fragment/documents/{doc_id}").text
    assert "in Paperless #5" in html and "über Dateinamen" in html
    assert "badge--link-linked_by_name" in html


def test_page_and_dashboard_panel_use_the_same_block(client):
    c, application = client
    doc_id = _doc(application, "scan-2.pdf", link=PaperlessLink.LINKED, paperless_id=5)
    page = c.get(f"/documents/{doc_id}").text
    assert f'<div id="detail" data-fragment="/fragment/documents/{doc_id}">' in page
    _assert_one_bar_one_title(page)
    assert '<h2 class="doc-title">Dokument 5</h2>' in page
    listing = c.get("/", params={"doc": doc_id}).text
    panel = re.search(r'<aside id="panel".*?</aside>', listing, re.S)
    assert panel is not None
    _assert_one_bar_one_title(panel.group(0))
    assert 'data="/paperless/5/preview"' in panel.group(0)


def test_unlinked_document_shows_local_original(client):
    c, application = client
    path = _file(_processed(application), "scan-3.pdf")
    doc_id = _doc(application, "scan-3.pdf", link=PaperlessLink.NOT_FOUND, original_path=str(path))
    html = c.get(f"/fragment/documents/{doc_id}").text
    _assert_one_bar_one_title(html)
    assert f'data="/documents/{doc_id}/original"' in html
    assert "badge--link-not_found" in html
    assert "/paperless/" not in html
    assert "paperless-embedded" not in html


def test_unlinked_xml_offers_download_instead_of_preview(client):
    c, application = client
    path = _file(_processed(application), "r.xml", b"<Invoice/>")
    doc_id = _doc(
        application,
        "r.xml",
        status=DocStatus.SKIPPED_ERECHNUNG,
        doc_type=DocType.ERECHNUNG_XML,
        original_path=str(path),
    )
    html = c.get(f"/fragment/documents/{doc_id}").text
    assert "XML-E-Rechnung herunterladen" in html
    assert f'href="/documents/{doc_id}/original"' in html
    assert "<object" not in html


def test_original_gone_shows_hint_not_error(client):
    c, application = client
    doc_id = _doc(application, "alt.pdf", link=PaperlessLink.NOT_FOUND)
    resp = c.get(f"/fragment/documents/{doc_id}")
    assert resp.status_code == 200
    assert "Original nicht mehr vorhanden" in resp.text
    assert "<object" not in resp.text


def test_failed_document_has_open_log_error_and_original_from_error_dir(client):
    c, application = client
    path = _file(_error(application), "kaputt.pdf")
    doc_id = _doc(
        application,
        "kaputt.pdf",
        status=DocStatus.FAILED,
        error_message="OCR abgelehnt",
        attempt_count=3,
        original_path=str(path),
    )
    html = c.get(f"/fragment/documents/{doc_id}").text
    _assert_one_bar_one_title(html)
    assert '<details class="doc-log" open>' in html
    assert "OCR abgelehnt" in html
    assert f'data="/documents/{doc_id}/original"' in html
    assert "badge--link-" not in html  # kein Ergebnis, kein Paperless-Bezug


@pytest.mark.parametrize("status", [DocStatus.PROCESSING, DocStatus.PENDING, DocStatus.BLOCKED])
def test_open_states_keep_log_open_and_show_no_original_hint(client, status):
    c, application = client
    doc_id = _doc(application, "laeuft.pdf", status=status)
    html = c.get(f"/fragment/documents/{doc_id}").text
    assert '<details class="doc-log" open>' in html
    assert "Original nicht mehr vorhanden" not in html


def test_deleted_in_paperless_is_detected_once_and_stored(client, monkeypatch):
    c, application = client
    calls = []
    original = PaperlessSync.load_document_view

    async def counting(self, paperless_id):
        calls.append(paperless_id)
        return await original(self, paperless_id)

    monkeypatch.setattr(PaperlessSync, "load_document_view", counting)
    path = _file(_processed(application), "weg.pdf")
    doc_id = _doc(
        application,
        "weg.pdf",
        link=PaperlessLink.LINKED,
        paperless_id=404404,  # Stub: Paperless kennt die ID nicht
        original_path=str(path),
    )
    html = c.get(f"/fragment/documents/{doc_id}").text
    _assert_one_bar_one_title(html)
    assert "nicht mehr vorhanden (#404404)" in html
    assert "badge--link-missing" in html
    assert f'data="/documents/{doc_id}/original"' in html  # Original, falls vorhanden
    stored = application.state.repo.get_document(doc_id)
    assert stored.paperless_link == PaperlessLink.MISSING and stored.paperless_id == 404404
    # Der gespeicherte Zustand genügt: kein zweiter Paperless-Abruf.
    c.get(f"/fragment/documents/{doc_id}")
    assert calls == [404404]


def test_paperless_unreachable_only_degrades_the_embedded_block(client, monkeypatch):
    c, application = client
    path = _file(_processed(application), "scan.pdf")
    doc_id = _doc(
        application, link=PaperlessLink.LINKED, paperless_id=5, original_path=str(path)
    )

    async def down(self, paperless_id):
        raise httpx.ConnectError("weg")

    monkeypatch.setattr(PaperlessSync, "load_document_view", down)
    for url in (f"/fragment/documents/{doc_id}", f"/documents/{doc_id}"):
        resp = c.get(url)
        assert resp.status_code == 200
        assert "Paperless nicht erreichbar" in resp.text
        _assert_one_bar_one_title(resp.text)
        assert f'data="/documents/{doc_id}/original"' in resp.text
    # Kein Zustandswechsel durch einen Netzfehler.
    assert application.state.repo.get_document(doc_id).paperless_link == PaperlessLink.LINKED


def test_without_paperless_connection_shows_no_paperless_details(client, monkeypatch):
    c, application = client
    monkeypatch.setattr(PaperlessSync, "view_enabled", property(lambda self: False))
    path = _file(_processed(application), "scan.pdf")
    doc_id = _doc(
        application, link=PaperlessLink.LINKED, paperless_id=5, original_path=str(path)
    )
    html = c.get(f"/fragment/documents/{doc_id}").text
    _assert_one_bar_one_title(html)
    assert "badge--link-" not in html and "in Paperless" not in html
    assert f'data="/documents/{doc_id}/original"' in html


def test_unknown_document_is_404_for_page_and_fragment(client):
    c, _ = client
    assert c.get("/documents/99999").status_code == 404
    assert c.get("/fragment/documents/99999").status_code == 404


# ---- 5.2 Rückweg der eingebetteten Aktionen -------------------------------------------


@pytest.mark.parametrize(
    ("path", "data", "plain_suffix", "panel_suffix"),
    [
        ("/invoices/{id}/dismiss", {}, "", ""),
        ("/invoices/{id}/paid", {"paid": "true"}, "", ""),
        ("/invoices/{id}/giro", {}, "", ""),
        ("/invoices/{id}/export", {"confirm": "1"}, "", ""),
        ("/invoices/{id}/export", {}, "?ask=1", "?ask=1"),
        ("/empfaenger/{pid}", {"recipient": "Familie"}, "", ""),
        ("/empfaenger/{pid}/suggest", {}, "", ""),
    ],
)
def test_back_doc_returns_to_combined_view(
    client, monkeypatch, path, data, plain_suffix, panel_suffix
):
    c, application = client
    sync = application.state.sync
    inv_id = _invoice(application.state.repo, 7, "Hosting", label="Familie", amount=20.0)
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
    form = {**data, "back": "doc:12"}

    plain = c.post(path, data=form, follow_redirects=False)
    assert plain.status_code == 303
    assert plain.headers["location"] == f"/documents/12{plain_suffix}"
    panel = c.post(path, data=form, headers=PANEL, follow_redirects=False)
    assert panel.status_code == 303
    assert panel.headers["location"] == f"/fragment/documents/12{panel_suffix}"


@pytest.mark.parametrize(
    "back",
    ["doc:abc", "doc:", "doc:1/../x", "doc:-1", "//evil.example", "https://evil.example/doc:1",
     "/documents/1", "doc:١٢", "document:1", ""],
)
def test_invalid_back_value_is_ignored(client, monkeypatch, back):
    c, application = client
    sync = application.state.sync
    inv_id = _invoice(application.state.repo, 7, "Hosting")

    async def noop(*_a, **_kw):
        return None

    monkeypatch.setattr(sync, "dismiss_invoice", lambda *_a, **_kw: None)
    monkeypatch.setattr(sync, "set_recipient", noop)
    for headers, expected_invoice, expected_recipient in (
        ({}, f"/invoices/{inv_id}", "/empfaenger?page=1"),
        (PANEL, "/fragment/paperless/7", "/fragment/paperless/7"),
    ):
        dismiss = c.post(
            f"/invoices/{inv_id}/dismiss", data={"back": back}, headers=headers,
            follow_redirects=False,
        )
        recipient = c.post(
            "/empfaenger/7", data={"recipient": "", "back": back}, headers=headers,
            follow_redirects=False,
        )
        assert dismiss.headers["location"] == expected_invoice
        assert recipient.headers["location"] == expected_recipient


# ---- Review-Nachträge ------------------------------------------------------------------


def test_cancel_in_export_question_returns_to_the_document(client, monkeypatch):
    from test_web import _rechnungsbereich_an

    _rechnungsbereich_an(monkeypatch)
    c, application = client
    _sevdesk_on(application, monkeypatch)
    _invoice(application.state.repo, 1, "Privat", correspondent="Kita", label="Familie")
    doc_id = _doc(application, link=PaperlessLink.LINKED, paperless_id=1)
    html = c.get(f"/fragment/documents/{doc_id}", params={"ask": "1"}).text
    assert "Vor dem Export klären" in html
    assert (
        f'href="/documents/{doc_id}" data-panel-url="/fragment/documents/{doc_id}">Abbrechen'
        in html
    )
    assert 'data-panel-url="/fragment/paperless/' not in html
    # Die reine Paperless-Ansicht behält ihr bisheriges Ziel.
    plain = c.get("/fragment/paperless/1", params={"ask": "1"}).text
    assert 'data-panel-url="/fragment/paperless/1">Abbrechen' in plain


def test_failed_lazy_search_is_not_repeated_until_ttl_expires(client, monkeypatch):
    c, application = client
    content = b"%PDF-1.4 spaet"
    doc_id = _doc(application, "spaet.pdf", file_hash=hashlib.sha256(content).hexdigest())
    now = [1000.0]
    monkeypatch.setattr(app.main, "_miss_clock", lambda: now[0])
    searches = []
    real = app.main._find_in_processed
    monkeypatch.setattr(
        app.main, "_find_in_processed", lambda *a: searches.append(a) or real(*a)
    )
    assert c.get(f"/documents/{doc_id}/original").status_code == 404
    first = len(searches)
    assert first >= 1
    _file(_processed(application), "spaet.pdf", content)  # taucht danach auf
    assert c.get(f"/documents/{doc_id}/original").status_code == 404  # Negativcache
    assert len(searches) == first
    now[0] += app.main._ORIGINAL_MISS_TTL_SECONDS + 1
    assert c.get(f"/documents/{doc_id}/original").status_code == 200
    assert len(searches) > first


@pytest.mark.parametrize(
    "error",
    [
        httpx.ConnectError("weg"),
        httpx.HTTPStatusError(
            "500", request=httpx.Request("GET", "http://p/x"), response=httpx.Response(500)
        ),
    ],
)
def test_paperless_errors_never_set_missing(client, monkeypatch, error):
    c, application = client
    doc_id = _doc(application, link=PaperlessLink.LINKED, paperless_id=5)

    async def boom(self, paperless_id):
        raise error

    monkeypatch.setattr(PaperlessSync, "load_document_view", boom)
    resp = c.get(f"/fragment/documents/{doc_id}")
    assert resp.status_code == 200 and "Paperless nicht erreichbar" in resp.text
    stored = application.state.repo.get_document(doc_id)
    assert stored.paperless_link == PaperlessLink.LINKED and stored.paperless_id == 5


def test_download_filename_with_quote_cr_lf_cannot_inject_headers(client):
    c, application = client
    path = _file(_processed(application), "x.xml", b"<Invoice/>")
    doc_id = _doc(
        application,
        'ev"il\r\nSet-Cookie: x=1.xml',
        status=DocStatus.SKIPPED_ERECHNUNG,
        original_path=str(path),
    )
    resp = c.get(f"/documents/{doc_id}/original")
    assert resp.status_code == 200
    disposition = resp.headers["content-disposition"]
    assert "\r" not in disposition and "\n" not in disposition
    assert "set-cookie" not in resp.headers
    ascii_part, _, utf_part = disposition.partition("; filename*=")
    assert ascii_part.count('"') == 2  # nur die Begrenzer des Rückfallnamens
    assert "%22" in utf_part and "%0D%0A" in utf_part


def test_back_doc_on_match_decision(client, monkeypatch):
    from app.models import InvoiceVoucherMatch, MatchKind, SevdeskVoucher

    c, application = client
    repo = application.state.repo
    inv_id = _invoice(repo, 7, "Hosting", label="Familie", amount=20.0)
    _sevdesk_on(application, monkeypatch)
    repo.replace_vouchers(
        [SevdeskVoucher(voucher_id="987", voucher_date="2026-10-04", supplier_name="AWS",
                        sum_gross=20.0, currency="EUR")]
    )
    repo.replace_auto_matches(
        [
            InvoiceVoucherMatch(
                invoice_id=inv_id, voucher_id="987", kind=MatchKind.SIMILAR, score=0.8
            )
        ]
    )
    monkeypatch.setattr(application.state.sync, "recompute_matches", lambda: 0)
    path = f"/invoices/{inv_id}/matches/987"
    form = {"decision": "confirm", "back": f"doc:{12}"}
    plain = c.post(path, data=form, follow_redirects=False)
    assert plain.headers["location"] == "/documents/12"
    # Doppelklick (Entscheidung steht schon) nimmt denselben Rückweg.
    again = c.post(path, data=form, headers=PANEL, follow_redirects=False)
    assert again.headers["location"] == "/fragment/documents/12"
