"""Tests für die Verknüpfung Vorgang -> Paperless-Dokument (Change scan-paperless-verknuepfung):
Client-Suche (`find_documents`) und Verknüpfungsjob (`PaperlessLinker`)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.config import Settings, validate_settings
from app.models import DocStatus, DocType, EventType, PaperlessLink
from app.paperless import DocumentHit, PaperlessClient, PaperlessError, TooManyHitsError
from app.paperless_link import (
    BATCH_SIZE,
    FILTER_ADDED_FROM,
    FILTER_ADDED_TO,
    FILTER_CHECKSUM,
    FILTER_ORIGINAL_NAME,
    PaperlessLinker,
)
from app.repository import Repository

BASE = "http://paperless.invalid"
HASH = "a" * 64
NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


# ---- Client: find_documents ----------------------------------------------------------


def _client(handler) -> PaperlessClient:
    client = PaperlessClient(BASE, "token")
    client._client = httpx.AsyncClient(base_url=BASE, transport=httpx.MockTransport(handler))
    return client


async def test_find_documents_sends_filters_and_fields_and_returns_hits():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(
            200,
            json={
                "count": 1,
                "next": None,
                "results": [
                    {"id": 7, "original_file_name": "a.pdf", "added": "2026-11-02T10:00:00Z"}
                ],
            },
        )

    client = _client(handler)
    hits = await client.find_documents(checksum__iexact=HASH)
    await client.aclose()

    assert seen["path"] == "/api/documents/"
    assert seen["params"]["checksum__iexact"] == HASH
    assert seen["params"]["fields"] == "id,original_file_name,added"
    assert hits == [DocumentHit(id=7, original_file_name="a.pdf", added="2026-11-02T10:00:00Z")]


async def test_find_documents_rejects_result_larger_than_five_as_unsupported_filter():
    """Paperless ignoriert unbekannte Filter und liefert den ganzen Bestand."""

    def handler(request: httpx.Request) -> httpx.Response:
        items = [{"id": i} for i in range(6)]
        return httpx.Response(200, json={"count": 1500, "next": "x", "results": items})

    client = _client(handler)
    with pytest.raises(TooManyHitsError, match="Filter nicht unterstützt"):
        await client.find_documents(checksum__iexact=HASH)
    await client.aclose()


# ---- Job ------------------------------------------------------------------------------


class FakeClient:
    """Ersatz für `PaperlessClient`: antwortet nach Filterart; merkt sich die Aufrufe."""

    def __init__(self, *, by_checksum=None, by_name=None, error=None, name_error=None):
        self.name_error = name_error
        self.by_checksum = by_checksum or {}
        self.by_name = by_name or {}
        self.error = error
        self.calls: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def find_documents(self, **filters):
        self.calls.append(filters)
        if FILTER_ORIGINAL_NAME in filters and self.name_error is not None:
            raise self.name_error
        if self.error is not None:
            raise self.error
        if FILTER_CHECKSUM in filters:
            return list(self.by_checksum.get(filters[FILTER_CHECKSUM], []))
        return list(self.by_name.get(filters[FILTER_ORIGINAL_NAME], []))


def _setup(tmp_path, client, now=NOW):
    settings = Settings(_env_file=None, PAPERLESS_URL=BASE, PAPERLESS_TOKEN="t")
    repo = Repository(tmp_path / "lector.db")
    linker = PaperlessLinker(settings, repo, client_factory=lambda: client, now=lambda: now)
    return repo, linker


def _doc(
    repo,
    name="a.pdf",
    *,
    status=DocStatus.DONE,
    link=None,
    output_hash=HASH,
    file_hash=None,
    doc_type=DocType.PDF,
    consumed_ago=timedelta(hours=1),
    output_path="auto",
):
    doc_id = repo.create_document(
        original_filename=name, source_path=f"/scan-in/{name}", file_hash=file_hash
    )
    repo.update_document(
        doc_id,
        status=status,
        doc_type=doc_type,
        output_hash=output_hash,
        output_path=f"/consume/{name}" if output_path == "auto" else output_path,
        consumed_at=(NOW - consumed_ago).strftime("%Y-%m-%d %H:%M:%S"),
    )
    if link is not None:
        repo.update_document(doc_id, paperless_link=link)
    return doc_id


async def test_pending_document_is_linked_by_checksum_with_event(tmp_path):
    client = FakeClient(by_checksum={HASH: [DocumentHit(id=1234)]})
    repo, linker = _setup(tmp_path, client)
    doc_id = _doc(repo, link=PaperlessLink.PENDING)

    result = await linker.run_once()

    doc = repo.get_document(doc_id)
    assert (doc.paperless_link, doc.paperless_id) == (PaperlessLink.LINKED, 1234)
    assert result.linked == 1
    assert EventType.PAPERLESS_LINKED.value in [e["event_type"] for e in repo.list_events(doc_id)]


async def test_duplicate_points_to_existing_document(tmp_path):
    """Lehnt Paperless die Datei als Dublette ab, findet die Suche das vorhandene Dokument."""
    client = FakeClient(by_checksum={HASH: [DocumentHit(id=99)]})
    repo, linker = _setup(tmp_path, client)
    doc_id = _doc(repo, link=PaperlessLink.PENDING, consumed_ago=timedelta(hours=30))

    await linker.run_once()

    doc = repo.get_document(doc_id)
    assert (doc.paperless_link, doc.paperless_id) == (PaperlessLink.LINKED, 99)


async def test_no_hit_before_24h_stays_pending(tmp_path):
    repo, linker = _setup(tmp_path, FakeClient())
    doc_id = _doc(repo, link=PaperlessLink.PENDING, consumed_ago=timedelta(hours=23))

    await linker.run_once()

    doc = repo.get_document(doc_id)
    assert doc.paperless_link == PaperlessLink.PENDING
    assert doc.paperless_checked_at is not None


async def test_no_hit_after_24h_marks_not_found_and_keeps_status(tmp_path):
    repo, linker = _setup(tmp_path, FakeClient())
    doc_id = _doc(repo, link=PaperlessLink.PENDING, consumed_ago=timedelta(hours=25))

    result = await linker.run_once()

    doc = repo.get_document(doc_id)
    assert doc.paperless_link == PaperlessLink.NOT_FOUND
    assert doc.status == DocStatus.DONE
    assert result.not_found == 1


async def test_network_error_aborts_without_state_change(tmp_path):
    client = FakeClient(error=httpx.ConnectError("down"))
    repo, linker = _setup(tmp_path, client)
    doc_id = _doc(repo, link=PaperlessLink.PENDING, consumed_ago=timedelta(hours=30))

    result = await linker.run_once()

    doc = repo.get_document(doc_id)
    assert doc.paperless_link == PaperlessLink.PENDING
    assert doc.paperless_checked_at is None
    assert result.aborted is True
    assert len(client.calls) == 1  # Lauf abgebrochen, kein weiterer Versuch


async def test_unsupported_filter_aborts_without_linking(tmp_path):
    client = FakeClient(error=PaperlessError("Filter nicht unterstützt: 1500 Treffer"))
    repo, linker = _setup(tmp_path, client)
    doc_id = _doc(repo, link=PaperlessLink.PENDING, consumed_ago=timedelta(hours=30))

    result = await linker.run_once()

    assert result.aborted is True
    assert repo.get_document(doc_id).paperless_link == PaperlessLink.PENDING


async def test_several_checksum_hits_neither_link_nor_not_found(tmp_path):
    client = FakeClient(by_checksum={HASH: [DocumentHit(id=1), DocumentHit(id=2)]})
    repo, linker = _setup(tmp_path, client)
    doc_id = _doc(repo, link=PaperlessLink.PENDING, consumed_ago=timedelta(hours=30))

    await linker.run_once()

    doc = repo.get_document(doc_id)
    assert doc.paperless_link == PaperlessLink.PENDING
    assert doc.paperless_id is None


async def test_failed_and_discarded_documents_are_never_searched(tmp_path):
    client = FakeClient(by_checksum={HASH: [DocumentHit(id=1)]})
    repo, linker = _setup(tmp_path, client)
    _doc(repo, "f.pdf", status=DocStatus.FAILED)
    _doc(repo, "p.pdf", status=DocStatus.PENDING)
    _doc(repo, "b.pdf", status=DocStatus.BLOCKED, link=PaperlessLink.PENDING)

    await linker.run_once()

    assert client.calls == []


async def test_catchup_erechnung_uses_file_hash_as_checksum(tmp_path):
    """Altbestand: E-Rechnung ohne Ausgabe-Prüfsumme und ohne Verknüpfung."""
    client = FakeClient(by_checksum={HASH: [DocumentHit(id=5)]})
    repo, linker = _setup(tmp_path, client)
    doc_id = _doc(
        repo,
        "r.xml",
        status=DocStatus.SKIPPED_ERECHNUNG,
        doc_type=DocType.ERECHNUNG_XML,
        output_hash=None,
        file_hash=HASH,
        consumed_ago=timedelta(days=60),
    )

    await linker.run_once()

    doc = repo.get_document(doc_id)
    assert (doc.paperless_link, doc.paperless_id) == (PaperlessLink.LINKED, 5)
    assert client.calls == [{FILTER_CHECKSUM: HASH}]


async def test_catchup_derives_consumed_at_from_event_for_old_documents(tmp_path):
    repo, linker = _setup(tmp_path, FakeClient())
    doc_id = repo.create_document(original_filename="alt.pdf", source_path="/x/alt.pdf")
    repo.update_document(
        doc_id, status=DocStatus.DONE, doc_type=DocType.PDF, output_path="/consume/alt.pdf"
    )
    repo.add_event(doc_id, EventType.MOVED_TO_CONSUME, "nach alt.pdf")

    await linker.run_once()

    assert repo.get_document(doc_id).consumed_at is not None


def _alt_ocr(repo, name="rechnung.pdf"):
    return _doc(repo, name, output_hash=None, consumed_ago=timedelta(days=40))


async def test_catchup_ocr_unique_name_links_by_name_with_window(tmp_path):
    consumed = NOW - timedelta(days=40)
    hit = DocumentHit(
        id=77,
        original_file_name="Rechnung.PDF",
        added=(consumed + timedelta(minutes=3)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    client = FakeClient(by_name={"rechnung.pdf": [hit]})
    repo, linker = _setup(tmp_path, client)
    doc_id = _alt_ocr(repo)

    await linker.run_once()

    doc = repo.get_document(doc_id)
    assert (doc.paperless_link, doc.paperless_id) == (PaperlessLink.LINKED_BY_NAME, 77)
    call = client.calls[0]
    assert call[FILTER_ORIGINAL_NAME] == "rechnung.pdf"
    assert call[FILTER_ADDED_FROM] == consumed.strftime("%Y-%m-%dT%H:%M:%SZ")
    assert call[FILTER_ADDED_TO] == (consumed + timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")


async def test_catchup_ocr_ambiguous_name_is_not_found(tmp_path):
    consumed = NOW - timedelta(days=40)
    added = (consumed + timedelta(minutes=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    client = FakeClient(
        by_name={
            "rechnung.pdf": [
                DocumentHit(id=1, original_file_name="rechnung.pdf", added=added),
                DocumentHit(id=2, original_file_name="rechnung.pdf", added=added),
            ]
        }
    )
    repo, linker = _setup(tmp_path, client)
    doc_id = _alt_ocr(repo)

    await linker.run_once()

    doc = repo.get_document(doc_id)
    assert doc.paperless_link == PaperlessLink.NOT_FOUND
    assert doc.paperless_id is None


async def test_catchup_ocr_ignores_hits_with_wrong_name_or_outside_window(tmp_path):
    """Schutz gegen lautlos ignorierte Filter: Treffer werden am Ergebnis gegengeprüft."""
    consumed = NOW - timedelta(days=40)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    in_window = (consumed + timedelta(hours=1)).strftime(fmt)
    outside = (consumed + timedelta(days=3)).strftime(fmt)
    client = FakeClient(
        by_name={
            "rechnung.pdf": [
                DocumentHit(id=1, original_file_name="anderes.pdf", added=in_window),
                DocumentHit(id=2, original_file_name="rechnung.pdf", added=outside),
            ]
        }
    )
    repo, linker = _setup(tmp_path, client)
    doc_id = _alt_ocr(repo)

    await linker.run_once()

    assert repo.get_document(doc_id).paperless_link == PaperlessLink.NOT_FOUND


async def test_not_found_is_rechecked_once_after_start_and_can_become_linked(tmp_path):
    client = FakeClient(by_checksum={HASH: [DocumentHit(id=8)]})
    repo, linker = _setup(tmp_path, client)
    doc_id = _doc(repo, link=PaperlessLink.NOT_FOUND, consumed_ago=timedelta(days=3))

    await linker.run_once()

    doc = repo.get_document(doc_id)
    assert (doc.paperless_link, doc.paperless_id) == (PaperlessLink.LINKED, 8)


async def test_not_found_is_not_searched_in_every_run(tmp_path):
    client = FakeClient()
    repo, linker = _setup(tmp_path, client)
    _doc(repo, link=PaperlessLink.NOT_FOUND, consumed_ago=timedelta(days=3))

    await linker.run_once()  # Nachholen nach dem Start: einmal gesucht
    await linker.run_once()  # danach nicht mehr

    assert len(client.calls) == 1


async def test_null_link_with_checksum_recent_becomes_pending(tmp_path):
    """Anbindung nachträglich eingeschaltet: NULL bei jungem Vorgang wird zu `pending`."""
    repo, linker = _setup(tmp_path, FakeClient())
    doc_id = _doc(repo, consumed_ago=timedelta(hours=2))

    await linker.run_once()

    assert repo.get_document(doc_id).paperless_link == PaperlessLink.PENDING


async def test_batch_limit_and_backlog_flag(tmp_path):
    client = FakeClient()
    repo, linker = _setup(tmp_path, client)
    for i in range(BATCH_SIZE + 5):
        _doc(repo, f"n{i}.pdf", consumed_ago=timedelta(hours=1))

    result = await linker.run_once()

    assert len(client.calls) == BATCH_SIZE
    assert result.more_work is True


def test_interval_validation():
    settings = Settings(_env_file=None, PAPERLESS_LINK_INTERVAL_SECONDS="0")
    assert any("PAPERLESS_LINK_INTERVAL_SECONDS" in p for p in validate_settings(settings))
    assert not any(
        "PAPERLESS_LINK_INTERVAL_SECONDS" in p for p in validate_settings(Settings(_env_file=None))
    )


async def test_too_many_name_hits_means_ambiguous_and_run_continues(tmp_path):
    """Ein häufiger Name (`scan.pdf`) blockiert den Altbestand nicht."""
    client = FakeClient(
        by_checksum={"b" * 64: [DocumentHit(id=3)]},
        name_error=TooManyHitsError("zu viele"),
    )
    repo, linker = _setup(tmp_path, client)
    viele = _alt_ocr(repo, "scan.pdf")
    weiter = _doc(repo, "n.pdf", output_hash="b" * 64, link=PaperlessLink.PENDING)

    result = await linker.run_once()

    assert result.aborted is False
    assert repo.get_document(viele).paperless_link == PaperlessLink.NOT_FOUND
    assert repo.get_document(weiter).paperless_link == PaperlessLink.LINKED


async def test_too_many_checksum_hits_still_abort(tmp_path):
    client = FakeClient(error=TooManyHitsError("Filter nicht unterstützt"))
    repo, linker = _setup(tmp_path, client)
    _doc(repo, link=PaperlessLink.PENDING)

    assert (await linker.run_once()).aborted is True


async def test_not_found_with_checksum_is_rechecked_daily_within_14_days(tmp_path):
    client = FakeClient(by_checksum={HASH: [DocumentHit(id=21)]})
    repo, linker = _setup(tmp_path, client)
    doc_id = _doc(repo, link=PaperlessLink.NOT_FOUND, consumed_ago=timedelta(days=3))
    # Zuletzt vor 2 Tagen gesucht, nach dem Start des Linkers -> nur die Tagesregel greift.
    repo._conn.execute(
        "UPDATE documents SET paperless_checked_at = ? WHERE id = ?",
        ((NOW - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S"), doc_id),
    )
    repo._conn.commit()
    linker._started_at = NOW - timedelta(days=5)

    await linker.run_once()

    assert repo.get_document(doc_id).paperless_link == PaperlessLink.LINKED


async def test_daily_recheck_skips_recent_checks_old_documents_and_name_based(tmp_path):
    client = FakeClient()
    repo, linker = _setup(tmp_path, client)
    linker._started_at = NOW - timedelta(days=30)
    fmt = "%Y-%m-%d %H:%M:%S"

    def checked(doc_id, ago):
        repo._conn.execute(
            "UPDATE documents SET paperless_checked_at = ? WHERE id = ?",
            ((NOW - ago).strftime(fmt), doc_id),
        )
        repo._conn.commit()

    frisch = _doc(repo, "a.pdf", link=PaperlessLink.NOT_FOUND, consumed_ago=timedelta(days=3))
    checked(frisch, timedelta(hours=2))  # vor 2 h gesucht
    alt = _doc(repo, "b.pdf", link=PaperlessLink.NOT_FOUND, consumed_ago=timedelta(days=20))
    checked(alt, timedelta(days=2))  # Ablage älter als 14 Tage
    nach_namen = _doc(
        repo, "c.pdf", link=PaperlessLink.NOT_FOUND, output_hash=None,
        consumed_ago=timedelta(days=3),
    )
    checked(nach_namen, timedelta(days=2))  # Namens-not_found: keine Tageswiederholung

    await linker.run_once()

    assert client.calls == []


async def test_name_hit_already_linked_to_other_document_is_discarded(tmp_path):
    consumed = NOW - timedelta(days=40)
    added = (consumed + timedelta(minutes=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    hit = DocumentHit(id=50, original_file_name="rechnung.pdf", added=added)
    client = FakeClient(by_name={"rechnung.pdf": [hit]})
    repo, linker = _setup(tmp_path, client)
    anderer = _doc(repo, "x.pdf", link=PaperlessLink.LINKED)
    repo.set_paperless_link(anderer, PaperlessLink.LINKED, paperless_id=50)
    doc_id = _alt_ocr(repo)

    await linker.run_once()

    doc = repo.get_document(doc_id)
    assert doc.paperless_link == PaperlessLink.NOT_FOUND
    assert doc.paperless_id is None


def test_catchup_order_puts_least_recently_checked_first(tmp_path):
    repo = Repository(tmp_path / "o.db")
    erster = _doc(repo, "a.pdf", output_hash=None)
    zweiter = _doc(repo, "b.pdf", output_hash=None)
    repo.touch_paperless_checked(erster)  # bereits geprüft -> rückt nach hinten

    ids = [
        d.id
        for d in repo.list_paperless_catchup(recheck_before=NOW + timedelta(days=1))
    ]

    assert ids == [zweiter, erster]
