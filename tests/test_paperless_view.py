"""Tests für die Dokumentansicht auf Client- und Sync-Ebene (Change paperless-dokumentansicht):
Namenslisten, Notizen, Namens-Cache und ``load_document_view``."""

from __future__ import annotations

import httpx
import pytest

from app import paperless_sync as ps
from app.config import Settings
from app.paperless import PaperlessClient
from app.repository import Repository

BASE = "http://paperless.invalid"


def _client(handler) -> PaperlessClient:
    client = PaperlessClient(BASE, "token")
    client._client = httpx.AsyncClient(base_url=BASE, transport=httpx.MockTransport(handler))
    return client


def _page(items):
    return httpx.Response(200, json={"count": len(items), "next": None, "results": items})


# ---- 1.1 Client --------------------------------------------------------------------


async def test_name_maps_read_id_to_name():
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/document_types/":
            return _page([{"id": 3, "name": "Rechnung"}])
        if path == "/api/tags/":
            return _page([{"id": 1, "name": "bezahlt"}, {"id": 2, "name": "steuer"}])
        if path == "/api/custom_fields/":
            return _page([{"id": 7, "name": "Empfänger", "data_type": "select"}])
        return httpx.Response(404)

    async with _client(handler) as client:
        assert await client.document_type_map() == {3: "Rechnung"}
        assert await client.tag_map() == {1: "bezahlt", 2: "steuer"}
        assert await client.custom_field_map() == {7: "Empfänger"}


async def test_note_entries_with_and_without_author():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/documents/5/notes/"
        return httpx.Response(
            200,
            json=[
                {
                    "id": 1,
                    "note": "Geprüft",
                    "created": "2026-03-04T10:15:00+01:00",
                    "user": {
                        "id": 2,
                        "username": "sascha",
                        "first_name": "Sascha",
                        "last_name": "K",
                    },
                },
                {"id": 2, "note": "Ohne Verfasser", "created": "2026-03-05T08:00:00Z"},
                {"id": 3, "note": "Nur Login", "user": {"id": 9, "username": "robot"}},
            ],
        )

    async with _client(handler) as client:
        notes = await client.get_note_entries(5)
    assert [n.text for n in notes] == ["Geprüft", "Ohne Verfasser", "Nur Login"]
    assert [n.author for n in notes] == ["Sascha K", None, "robot"]
    assert notes[0].created == "2026-03-04T10:15:00+01:00"
    assert notes[2].created is None


async def test_document_maps_added_asn_and_page_count_and_tolerates_missing_asn():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/documents/1/":
            return httpx.Response(
                200,
                json={
                    "id": 1,
                    "title": "Voll",
                    "added": "2026-01-02T03:04:05Z",
                    "archive_serial_number": 42,
                    "page_count": 3,
                },
            )
        return httpx.Response(
            200, json={"id": 2, "title": "Leer", "archive_serial_number": None}
        )

    async with _client(handler) as client:
        full = await client.get_document(1)
        empty = await client.get_document(2)
    assert (full.added, full.archive_serial_number, full.page_count) == (
        "2026-01-02T03:04:05Z",
        42,
        3,
    )
    assert (empty.added, empty.archive_serial_number, empty.page_count) == (None, None, None)


# ---- 1.2 / 1.3 Sync ----------------------------------------------------------------


class _FakePaperless:
    """Zählt Abrufe je Pfad und beantwortet sie aus ``routes`` (Pfad -> JSON oder Status)."""

    def __init__(self, routes):
        self.routes = routes
        self.calls: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append(path)
        value = self.routes.get(path)
        if value is None:
            return httpx.Response(404)
        if isinstance(value, int):
            return httpx.Response(value)
        if isinstance(value, list) and path.startswith("/api/documents/"):
            return httpx.Response(200, json=value)
        if isinstance(value, list):
            return _page(value)
        return httpx.Response(200, json=value)

    def count(self, path: str) -> int:
        return self.calls.count(path)


def _sync(tmp_path, monkeypatch, fake: _FakePaperless) -> ps.PaperlessSync:
    sync = ps.PaperlessSync(
        Settings(PAPERLESS_URL=BASE, PAPERLESS_TOKEN="token"), Repository(tmp_path / "v.db")
    )
    monkeypatch.setattr(sync, "_paperless", lambda: _client(fake.handler))
    return sync


def _routes(**overrides):
    routes = {
        "/api/correspondents/": [{"id": 4, "name": "Telekom"}],
        "/api/document_types/": [{"id": 3, "name": "Rechnung"}],
        "/api/tags/": [{"id": 1, "name": "bezahlt"}, {"id": 2, "name": "steuer"}],
        "/api/custom_fields/": [
            {
                "id": 7,
                "name": "Empfänger",
                "data_type": "select",
                "extra_data": {"select_options": [{"id": "opt1", "label": "Familie"}]},
            },
            {"id": 8, "name": "SevDesk-Beleg", "data_type": "string"},
        ],
        "/api/documents/1234/": {
            "id": 1234,
            "title": "Rechnung Mai",
            "correspondent": 4,
            "document_type": 3,
            "tags": [1, 2],
            "created": "2026-05-01",
            "added": "2026-05-03T10:00:00Z",
            "archive_serial_number": 17,
            "custom_fields": [
                {"field": 7, "value": "opt1"},
                {"field": 8, "value": "BEL-9"},
            ],
        },
        "/api/documents/1234/notes/": [
            {"id": 1, "note": "ok", "created": "2026-05-04T08:00:00Z", "user": {"username": "s"}}
        ],
    }
    routes.update(overrides)
    return routes


async def test_name_cache_second_access_without_http_and_reload_after_expiry(
    tmp_path, monkeypatch
):
    fake = _FakePaperless(_routes())
    sync = _sync(tmp_path, monkeypatch, fake)
    async with sync._paperless() as client:
        first = await sync._names(client, "tag")
        second = await sync._names(client, "tag", [1, 2])
    assert first == second == {1: "bezahlt", 2: "steuer"}
    assert fake.count("/api/tags/") == 1

    # Abgelaufen: genau ein Neuladen.
    now = ps.time.monotonic()
    monkeypatch.setattr(ps.time, "monotonic", lambda: now + ps.NAME_CACHE_TTL + 1)
    async with sync._paperless() as client:
        await sync._names(client, "tag")
        await sync._names(client, "tag")
    assert fake.count("/api/tags/") == 2


async def test_name_cache_reloads_once_for_unknown_id(tmp_path, monkeypatch):
    fake = _FakePaperless(_routes())
    sync = _sync(tmp_path, monkeypatch, fake)
    async with sync._paperless() as client:
        await sync._names(client, "tag")
        # Neuer Tag seit dem letzten Abruf: einmal neu laden, dann steht er in der Liste.
        fake.routes["/api/tags/"] = [{"id": 1, "name": "bezahlt"}, {"id": 99, "name": "neu"}]
        names = await sync._names(client, "tag", [99])
    assert names[99] == "neu"
    assert fake.count("/api/tags/") == 2


async def test_corr_map_cached_uses_name_cache(tmp_path, monkeypatch):
    fake = _FakePaperless(_routes())
    sync = _sync(tmp_path, monkeypatch, fake)
    async with sync._paperless() as client:
        assert await sync._corr_map_cached(client) == {4: "Telekom"}
        assert await sync._corr_map_cached(client) == {4: "Telekom"}
    assert fake.count("/api/correspondents/") == 1


async def test_view_enabled_needs_url_and_token(tmp_path):
    repo = Repository(tmp_path / "e.db")
    assert not ps.PaperlessSync(Settings(PAPERLESS_URL=BASE), repo).view_enabled
    assert not ps.PaperlessSync(Settings(PAPERLESS_TOKEN="t"), repo).view_enabled
    assert ps.PaperlessSync(Settings(PAPERLESS_URL=BASE, PAPERLESS_TOKEN="t"), repo).view_enabled


async def test_load_document_view_with_all_details(tmp_path, monkeypatch):
    fake = _FakePaperless(_routes())
    sync = _sync(tmp_path, monkeypatch, fake)
    view = await sync.load_document_view(1234)
    assert view is not None
    assert view.title == "Rechnung Mai"
    assert view.correspondent == "Telekom"
    assert view.document_type == "Rechnung"
    assert view.tags == ["bezahlt", "steuer"]
    assert view.archive_serial_number == 17
    assert view.created.year == 2026 and view.added.month == 5
    assert [(f.name, f.value) for f in view.custom_fields] == [
        ("Empfänger", "Familie"),
        ("SevDesk-Beleg", "BEL-9"),
    ]
    assert view.current_recipient == "Familie"
    assert view.recipient_options == ["Familie"]
    assert view.notes[0].text == "ok" and view.notes[0].author == "s"
    assert view.invoice is None


async def test_load_document_view_without_correspondent_and_asn(tmp_path, monkeypatch):
    fake = _FakePaperless(
        _routes(
            **{
                "/api/documents/1234/": {
                    "id": 1234,
                    "title": "",
                    "correspondent": None,
                    "document_type": None,
                    "tags": [],
                    "custom_fields": [],
                }
            }
        )
    )
    sync = _sync(tmp_path, monkeypatch, fake)
    view = await sync.load_document_view(1234)
    assert view.correspondent is None and view.document_type is None
    assert view.archive_serial_number is None
    assert view.title == "#1234"
    assert view.tags == [] and view.custom_fields == []


async def test_load_document_view_unknown_tag_falls_back_to_id(tmp_path, monkeypatch):
    routes = _routes()
    routes["/api/documents/1234/"] = {**routes["/api/documents/1234/"], "tags": [55]}
    fake = _FakePaperless(routes)
    sync = _sync(tmp_path, monkeypatch, fake)
    view = await sync.load_document_view(1234)
    assert view.tags == ["#55"]
    # Die unbekannte ID löste genau ein Neuladen der Tag-Liste aus.
    assert fake.count("/api/tags/") == 1


@pytest.mark.parametrize("status", [404, 403])
async def test_load_document_view_unknown_id_returns_none(tmp_path, monkeypatch, status):
    fake = _FakePaperless({"/api/documents/9/": status, "/api/documents/9/notes/": status})
    sync = _sync(tmp_path, monkeypatch, fake)
    assert await sync.load_document_view(9) is None


async def test_load_document_view_paperless_error_propagates(tmp_path, monkeypatch):
    fake = _FakePaperless({"/api/documents/9/": 500, "/api/documents/9/notes/": 500})
    sync = _sync(tmp_path, monkeypatch, fake)
    with pytest.raises(httpx.HTTPStatusError):
        await sync.load_document_view(9)


async def test_fetch_document_preview(tmp_path, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/documents/5/preview/":
            return httpx.Response(200, content=b"%PDF", headers={"Content-Type": "application/pdf"})
        if request.url.path == "/api/documents/6/preview/":
            return httpx.Response(500)
        return httpx.Response(404)

    sync = ps.PaperlessSync(
        Settings(PAPERLESS_URL=BASE, PAPERLESS_TOKEN="token"), Repository(tmp_path / "p.db")
    )
    monkeypatch.setattr(sync, "_paperless", lambda: _client(handler))
    assert await sync.fetch_document_preview(5) == (b"%PDF", "application/pdf")
    assert await sync.fetch_document_preview(7) is None
    with pytest.raises(httpx.HTTPStatusError):
        await sync.fetch_document_preview(6)


async def test_fetch_document_preview_disabled_returns_none(tmp_path):
    sync = ps.PaperlessSync(Settings(), Repository(tmp_path / "d.db"))
    assert await sync.fetch_document_preview(1) is None


async def test_load_document_view_finds_known_invoice_by_paperless_id(tmp_path, monkeypatch):
    fake = _FakePaperless(_routes())
    sync = _sync(tmp_path, monkeypatch, fake)
    inv_id = sync.repo.upsert_invoice(paperless_id=1234, title="Rechnung Mai", correspondent=None)
    view = await sync.load_document_view(1234)
    assert view.invoice is not None and view.invoice.id == inv_id


@pytest.mark.parametrize(
    ("select_options", "stored", "expected"),
    [
        ([{"id": "a1", "label": "Rot"}, {"id": "b2", "label": "Blau"}], "b2", "Blau"),  # 2.x
        (["Rot", "Blau"], 1, "Blau"),  # ältere Versionen: Wert = Index
        ([{"id": "a1", "label": "Rot"}], "unbekannt", "unbekannt"),
        (["Rot"], 7, "7"),
    ],
)
async def test_select_field_values_show_label(
    tmp_path, monkeypatch, select_options, stored, expected
):
    routes = _routes()
    routes["/api/custom_fields/"] = [
        {"id": 9, "name": "Farbe", "data_type": "select",
         "extra_data": {"select_options": select_options}},
    ]
    routes["/api/documents/1234/"] = {
        **routes["/api/documents/1234/"],
        "custom_fields": [{"field": 9, "value": stored}],
    }
    fake = _FakePaperless(routes)
    sync = _sync(tmp_path, monkeypatch, fake)
    view = await sync.load_document_view(1234)
    assert [(f.name, f.value) for f in view.custom_fields] == [("Farbe", expected)]
    # Namen und Optionen kommen aus einer einzigen Abfrage der Felder.
    assert fake.count("/api/custom_fields/") == 1 + 1  # +1: Empfänger-Feld-Auflösung


async def test_name_cache_remembers_missing_ids_for_a_minute(tmp_path, monkeypatch):
    fake = _FakePaperless(_routes())
    sync = _sync(tmp_path, monkeypatch, fake)
    now = ps.time.monotonic()
    async with sync._paperless() as client:
        await sync._names(client, "tag", [1, 555])  # 555 gibt es nicht
        await sync._names(client, "tag", [1, 555])
        await sync._names(client, "tag", [555])
        assert fake.count("/api/tags/") == 1
        # Nach Ablauf der Merkzeit wird einmal neu geladen.
        monkeypatch.setattr(ps.time, "monotonic", lambda: now + ps.NAME_MISS_TTL + 1)
        await sync._names(client, "tag", [555])
        await sync._names(client, "tag", [555])
    assert fake.count("/api/tags/") == 2
