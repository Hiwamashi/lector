"""Tests für die Empfänger-Zuordnung: Client-Helfer, LLM-Parsing und Repository-Cache."""

from __future__ import annotations

import httpx
import pytest

from app import recipient_llm as rl
from app.models import PaperlessInvoice, RecipientStatus
from app.paperless import DocumentPage, PaperlessClient, PaperlessDocument, SelectField
from app.recipient_llm import RecipientSuggester, RecipientSuggesterError
from app.repository import Repository

# ---- Client-Helfer ------------------------------------------------------


def _doc(custom_fields):
    return PaperlessDocument(
        id=1,
        title="t",
        content="",
        correspondent_id=None,
        document_type_id=None,
        tag_ids=[],
        custom_fields=custom_fields,
        original_file_name=None,
    )


def test_select_value_reads_option_id():
    doc = _doc([{"field": 1, "value": "abc123"}, {"field": 2, "value": "x"}])
    assert PaperlessClient.select_value(doc, 1) == "abc123"
    assert PaperlessClient.select_value(doc, 2) == "x"


def test_select_value_returns_none_when_unset():
    doc = _doc([{"field": 1, "value": None}])
    assert PaperlessClient.select_value(doc, 1) is None
    assert PaperlessClient.select_value(_doc([]), 1) is None


def test_document_page_total_pages():
    page = DocumentPage(documents=[], count=101, page=1, page_size=50)
    assert page.total_pages == 3
    assert DocumentPage(documents=[], count=0, page=1, page_size=50).total_pages == 1


def test_select_field_labels():
    field = SelectField(
        field_id=1, label_to_id={"A": "x", "B": "y"}, id_to_label={"x": "A", "y": "B"}
    )
    assert field.labels == ["A", "B"]


# ---- LLM-Parsing (ohne Netz) -------------------------------------------


def _parse(input_dict, options):
    response = {"content": [{"type": "tool_use", "name": "set_recipient", "input": input_dict}]}
    return RecipientSuggester._parse(response, options)


def test_llm_parse_valid_label():
    s = _parse({"recipient": "Sascha", "confidence": 0.9, "reasoning": "x"}, ["Sascha", "Familie"])
    assert s.label == "Sascha"
    assert s.confidence == 0.9
    assert s.reasoning == "x"


def test_llm_parse_unknown_maps_to_none():
    s = _parse({"recipient": "unbekannt", "confidence": 0.1}, ["Sascha"])
    assert s.label is None
    assert s.confidence == 0.1


def test_llm_parse_invalid_label_rejected():
    # Modell halluziniert einen Namen, der nicht in den Optionen steht → None.
    s = _parse({"recipient": "Max", "confidence": 0.8}, ["Sascha", "Familie"])
    assert s.label is None


def test_llm_parse_clamps_confidence():
    assert _parse({"recipient": "Sascha", "confidence": 5}, ["Sascha"]).confidence == 1.0
    assert _parse({"recipient": "Sascha", "confidence": -2}, ["Sascha"]).confidence == 0.0
    assert _parse({"recipient": "Sascha", "confidence": "x"}, ["Sascha"]).confidence == 0.0


def test_llm_parse_missing_tool_call_raises():
    with pytest.raises(RecipientSuggesterError):
        RecipientSuggester._parse({"content": [{"type": "text", "text": "hi"}]}, ["Sascha"])


def test_llm_build_prompt_lists_options_and_truncates():
    import re

    from app.recipient_llm import _MAX_CONTENT_CHARS

    prompt = RecipientSuggester._build_prompt("Titel", "Absender", "x" * 9000, ["A", "B"])
    assert "A, B" in prompt
    assert "Titel" in prompt and "Absender" in prompt
    # Der Dokumenttext (zusammenhängender x-Block) wird auf _MAX_CONTENT_CHARS gekürzt.
    longest_run = max(len(m) for m in re.findall(r"x+", prompt))
    assert longest_run == _MAX_CONTENT_CHARS


# ---- Repository-Cache ---------------------------------------------------


@pytest.fixture
def repo(tmp_path):
    return Repository(tmp_path / "rec.db")


def test_recipient_cache_roundtrip(repo):
    assert repo.get_recipient_cache(42) is None
    repo.set_recipient_cache(
        42,
        suggested_label="Sascha",
        confidence=0.8,
        reasoning="weil",
        status=RecipientStatus.SUGGESTED,
    )
    cache = repo.get_recipient_cache(42)
    assert cache.suggested_label == "Sascha"
    assert cache.confidence == 0.8
    assert cache.status == RecipientStatus.SUGGESTED


def test_recipient_cache_upsert_and_bulk(repo):
    repo.set_recipient_cache(
        1, suggested_label="A", confidence=0.5, reasoning=None, status=RecipientStatus.SUGGESTED
    )
    repo.set_recipient_cache(
        2, suggested_label=None, confidence=0.1, reasoning=None, status=RecipientStatus.UNKNOWN
    )
    caches = repo.get_recipient_caches([1, 2, 3])
    assert set(caches) == {1, 2}
    assert caches[2].status == RecipientStatus.UNKNOWN


def test_mark_recipient_applied(repo):
    repo.set_recipient_cache(
        7, suggested_label="A", confidence=0.9, reasoning=None, status=RecipientStatus.SUGGESTED
    )
    repo.mark_recipient_applied(7)
    cache = repo.get_recipient_cache(7)
    assert cache.status == RecipientStatus.APPLIED


def test_notify_recipient_emits_token(tmp_path):
    seen: list[str] = []
    repo = Repository(tmp_path / "n.db", notifier=seen.append)
    repo.set_recipient_cache(
        5, suggested_label="A", confidence=0.5, reasoning=None, status=RecipientStatus.SUGGESTED
    )
    assert "rec:5" in seen


# Sicherstellen, dass das bestehende Invoice-Modell unberührt bleibt (Smoke).
def test_invoice_model_still_constructs():
    inv = PaperlessInvoice(id=1, paperless_id=2)
    assert inv.currency == "EUR"


# ---- Batch-Sammlung überspringt bereits gecachte Dokumente --------------


class _FakeClient:
    """Minimaler Paperless-Stub: liefert die übergebenen Dokumente paginiert aus."""

    def __init__(self, doc_ids, page_size):
        self._ids = doc_ids
        self._page_size = page_size

    async def search_documents(self, *, page, page_size, missing_field_id=None, **_):
        start = (page - 1) * page_size
        chunk = self._ids[start : start + page_size]
        docs = [_doc_with_id(i) for i in chunk]
        return DocumentPage(documents=docs, count=len(self._ids), page=page, page_size=page_size)


def _doc_with_id(doc_id):
    return PaperlessDocument(
        id=doc_id,
        title=f"#{doc_id}",
        content="",
        correspondent_id=None,
        document_type_id=None,
        tag_ids=[],
        custom_fields=[],
        original_file_name=None,
    )


async def test_collect_missing_ids_skips_cached_and_reaches_later_docs(tmp_path, monkeypatch):
    from app import paperless_sync as ps
    from app.config import Settings

    monkeypatch.setattr(ps, "RECIPIENT_PAGE_SIZE", 2)

    repo = Repository(tmp_path / "b.db")
    # Die ersten beiden fehlenden Dokumente haben bereits einen Vorschlag.
    for doc_id in (1, 2):
        repo.set_recipient_cache(
            doc_id,
            suggested_label="Sascha",
            confidence=0.9,
            reasoning=None,
            status=RecipientStatus.SUGGESTED,
        )

    sync = ps.PaperlessSync(Settings(PAPERLESS_URL="http://x", PAPERLESS_TOKEN="t"), repo)
    field = SelectField(field_id=1, label_to_id={"Sascha": "s"}, id_to_label={"s": "Sascha"})
    client = _FakeClient([1, 2, 3, 4, 5], page_size=2)

    ids, remaining = await sync._collect_missing_ids(client, field, limit=2)
    # Trotz Limit=2 dürfen die gecachten 1,2 nicht alles belegen — 3,4 müssen drankommen.
    assert ids == [3, 4]
    # 5 bleibt ungeplant liegen und muss als Rest gemeldet werden.
    assert remaining == 1


# ---- Batch überschreibt keinen währenddessen gesetzten Empfänger --------


class _WriteCapturingClient:
    """Stub, der den Live-Dokumentzustand liefert und Schreibzugriffe aufzeichnet."""

    def __init__(self, live_custom_fields):
        self._live = live_custom_fields
        self.writes: list[tuple[int, dict]] = []

    async def get_document(self, doc_id):
        return PaperlessDocument(
            id=doc_id, title="t", content="", correspondent_id=None, document_type_id=None,
            tag_ids=[], custom_fields=self._live, original_file_name=None,
        )

    @staticmethod
    def select_value(doc, field_id):
        return PaperlessClient.select_value(doc, field_id)

    async def set_custom_fields(self, doc_id, values):
        self.writes.append((doc_id, values))


class _StubSuggester:
    def __init__(self, label, confidence):
        from app.models import RecipientSuggestion

        self._s = RecipientSuggestion(label=label, confidence=confidence, reasoning="r")

    async def suggest(self, **_):
        return self._s


def _sync_for_suggest(repo):
    from app import paperless_sync as ps
    from app.config import Settings

    return ps.PaperlessSync(Settings(PAPERLESS_URL="http://x", PAPERLESS_TOKEN="t"), repo)


async def test_batch_does_not_overwrite_live_recipient(tmp_path):
    # Während des LLM-Calls wurde der Empfänger direkt in Paperless gesetzt (Feld 1 = "s").
    repo = Repository(tmp_path / "g.db")
    sync = _sync_for_suggest(repo)
    field = SelectField(field_id=1, label_to_id={"Sascha": "s"}, id_to_label={"s": "Sascha"})
    client = _WriteCapturingClient([{"field": 1, "value": "s"}])

    result = await sync._suggest_for_doc(
        client, _StubSuggester("Sascha", 0.9), field, _doc_with_id(7), None,
        guard_concurrent=True,
    )
    assert result.label == "Sascha"
    assert client.writes == []  # kein Überschreiben des Live-Werts
    assert repo.get_recipient_cache(7) is None  # auch kein Cache-Write


async def test_batch_auto_applies_when_field_empty(tmp_path):
    # Gegenprobe: leeres Feld → Vorschlag wird angewandt (Schreibzugriff + APPLIED).
    repo = Repository(tmp_path / "h.db")
    sync = _sync_for_suggest(repo)
    field = SelectField(field_id=1, label_to_id={"Sascha": "s"}, id_to_label={"s": "Sascha"})
    client = _WriteCapturingClient([])

    await sync._suggest_for_doc(
        client, _StubSuggester("Sascha", 0.9), field, _doc_with_id(7), None,
        guard_concurrent=True,
    )
    assert client.writes == [(7, {1: "s"})]
    assert repo.get_recipient_cache(7).status == RecipientStatus.APPLIED


class _CtxClient:
    """Reicht einen bereits fertigen Client als async Context Manager durch."""

    def __init__(self, inner):
        self._inner = inner

    async def __aenter__(self):
        return self._inner

    async def __aexit__(self, *exc):
        return False


async def test_batch_limit_zero_does_not_fall_back_to_maximum(tmp_path):
    # limit=0 ist explizit "keine Dokumente", nicht "kein Limit" — 0 ist falsy und darf
    # nicht via `limit or maximum` auf die Settings-Obergrenze (hier Default 1000)
    # zurückfallen. _collect_missing_ids wird durch einen Spy ersetzt, damit der Test
    # den tatsächlich durchgereichten Effektiv-Wert prüft statt sich auf Seiteneffekte
    # der Dokumentverarbeitung zu verlassen.
    from app import paperless_sync as ps
    from app.config import Settings

    repo = Repository(tmp_path / "i.db")
    settings = Settings(
        PAPERLESS_URL="http://x",
        PAPERLESS_TOKEN="t",
        FEATURE_RECIPIENT_LLM=True,
        ANTHROPIC_API_KEY="k",
    )
    sync = ps.PaperlessSync(settings, repo)
    field = SelectField(field_id=1, label_to_id={"Sascha": "s"}, id_to_label={"s": "Sascha"})
    # Feldauflösung vorab cachen, damit kein echter Client-Aufruf nötig ist.
    sync._recipient_field = field
    sync._recipient_field_resolved = True
    sync._paperless = lambda: _CtxClient(object())

    seen_limits: list[int] = []

    async def fake_collect(client, field, limit):
        seen_limits.append(limit)
        return [], 0

    sync._collect_missing_ids = fake_collect

    processed = await sync.suggest_recipients_batch(limit=0)
    assert processed == 0
    assert seen_limits == [0]


# ---- Retry / Backoff im LLM-Client --------------------------------------


def _ok_payload():
    return {
        "content": [
            {
                "type": "tool_use",
                "name": "set_recipient",
                "input": {"recipient": "Sascha", "confidence": 0.9, "reasoning": "r"},
            }
        ]
    }


def _suggester_with(responses, monkeypatch):
    """Baut einen Suggester, dessen Transport die übergebenen Antworten der Reihe nach liefert.

    Ein Eintrag ist entweder ein httpx.Response oder eine Exception, die geworfen wird.
    Wartezeiten werden aufgezeichnet statt real abzuwarten.
    """
    slept: list[float] = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(rl.asyncio, "sleep", fake_sleep)

    calls = {"n": 0}

    def handler(request):
        item = responses[calls["n"]]
        calls["n"] += 1
        if isinstance(item, Exception):
            raise item
        return item

    suggester = rl.RecipientSuggester(
        "key", "model", transport=httpx.MockTransport(handler)
    )
    return suggester, slept, calls


async def test_retry_recovers_after_429(monkeypatch):
    suggester, slept, calls = _suggester_with(
        [httpx.Response(429), httpx.Response(200, json=_ok_payload())], monkeypatch
    )
    async with suggester:
        result = await suggester.suggest(
            title="t", correspondent=None, content="c", options=["Sascha"]
        )
    assert result.label == "Sascha"
    assert calls["n"] == 2
    assert slept == [1.0]


async def test_retry_honours_retry_after_header(monkeypatch):
    suggester, slept, _ = _suggester_with(
        [
            httpx.Response(429, headers={"retry-after": "7"}),
            httpx.Response(200, json=_ok_payload()),
        ],
        monkeypatch,
    )
    async with suggester:
        await suggester.suggest(
            title="t", correspondent=None, content="c", options=["Sascha"]
        )
    assert slept == [7.0]


async def test_retry_skips_client_errors(monkeypatch):
    # 400 wird durch Warten nicht besser — genau ein Versuch, keine Wartezeit.
    suggester, slept, calls = _suggester_with([httpx.Response(400)], monkeypatch)
    async with suggester:
        with pytest.raises(RecipientSuggesterError):
            await suggester.suggest(
                title="t", correspondent=None, content="c", options=["Sascha"]
            )
    assert calls["n"] == 1
    assert slept == []


async def test_retry_gives_up_after_three_attempts(monkeypatch):
    suggester, slept, calls = _suggester_with(
        [httpx.Response(529), httpx.Response(529), httpx.Response(529)], monkeypatch
    )
    async with suggester:
        with pytest.raises(RecipientSuggesterError):
            await suggester.suggest(
                title="t", correspondent=None, content="c", options=["Sascha"]
            )
    assert calls["n"] == 3
    assert slept == [1.0, 2.0]


async def test_retry_covers_timeouts(monkeypatch):
    suggester, slept, calls = _suggester_with(
        [httpx.TimeoutException("zu langsam"), httpx.Response(200, json=_ok_payload())],
        monkeypatch,
    )
    async with suggester:
        result = await suggester.suggest(
            title="t", correspondent=None, content="c", options=["Sascha"]
        )
    assert result.label == "Sascha"
    assert calls["n"] == 2


async def test_collect_reports_no_rest_when_limit_suffices(tmp_path, monkeypatch):
    from app import paperless_sync as ps
    from app.config import Settings

    monkeypatch.setattr(ps, "RECIPIENT_PAGE_SIZE", 2)
    repo = Repository(tmp_path / "c.db")
    sync = ps.PaperlessSync(Settings(PAPERLESS_URL="http://x", PAPERLESS_TOKEN="t"), repo)
    field = SelectField(field_id=1, label_to_id={"Sascha": "s"}, id_to_label={"s": "Sascha"})
    client = _FakeClient([1, 2, 3], page_size=2)

    ids, remaining = await sync._collect_missing_ids(client, field, limit=10)
    assert ids == [1, 2, 3]
    assert remaining == 0


# ---- Laufzustand, Abbruch, Fehlerserie ----------------------------------


class _FailingSuggester:
    """Stub, der die ersten ``fail_first`` Aufrufe scheitern lässt."""

    def __init__(self, fail_first: int):
        self._left = fail_first

    async def suggest(self, **_):
        from app.models import RecipientSuggestion
        from app.recipient_llm import RecipientSuggesterError

        if self._left > 0:
            self._left -= 1
            raise RecipientSuggesterError("throttled")
        return RecipientSuggestion(label="Sascha", confidence=0.9, reasoning="r")


def _batch_sync(tmp_path, monkeypatch, doc_ids, suggester):
    """Baut einen PaperlessSync, dessen Batch-Lauf gegen Stubs statt gegen das Netz läuft."""
    from contextlib import asynccontextmanager

    from app import paperless_sync as ps
    from app.config import Settings

    repo = Repository(tmp_path / "p.db")
    sync = ps.PaperlessSync(
        Settings(
            PAPERLESS_URL="http://x",
            PAPERLESS_TOKEN="t",
            FEATURE_RECIPIENT_LLM=True,
            ANTHROPIC_API_KEY="k",
        ),
        repo,
    )
    field = SelectField(field_id=1, label_to_id={"Sascha": "s"}, id_to_label={"s": "Sascha"})
    client = _WriteCapturingClient([])

    @asynccontextmanager
    async def fake_paperless():
        yield client

    @asynccontextmanager
    async def fake_suggester():
        yield suggester

    monkeypatch.setattr(sync, "_paperless", fake_paperless)
    monkeypatch.setattr(sync, "_suggester", fake_suggester)
    async def fake_field(_client):
        return field

    async def fake_collect(_client, _field, _limit):
        return list(doc_ids), 0

    monkeypatch.setattr(sync, "_recipient_field_cached", fake_field)
    monkeypatch.setattr(sync, "_collect_missing_ids", fake_collect)
    return sync, repo


async def test_progress_counts_done_and_failed(tmp_path, monkeypatch):
    sync, _ = _batch_sync(tmp_path, monkeypatch, [1, 2, 3], _FailingSuggester(fail_first=1))
    await sync.suggest_recipients_batch(limit=10)
    p = sync.batch_progress
    assert p.running is False
    assert p.total == 3
    assert p.done == 2
    assert p.failed == 1
    assert p.aborted_reason is None


async def test_stop_ends_run_early(tmp_path, monkeypatch):
    sync, _ = _batch_sync(tmp_path, monkeypatch, [1, 2, 3, 4], _StubSuggester("Sascha", 0.9))

    original = sync._suggest_for_doc

    async def stop_after_first(*args, **kwargs):
        result = await original(*args, **kwargs)
        sync.stop_batch()
        return result

    monkeypatch.setattr(sync, "_suggest_for_doc", stop_after_first)

    await sync.suggest_recipients_batch(limit=10)
    p = sync.batch_progress
    assert p.stopped is True
    assert p.done == 1
    assert p.running is False


async def test_error_streak_aborts_run(tmp_path, monkeypatch):
    from app import paperless_sync as ps

    monkeypatch.setattr(ps, "BATCH_ERROR_STREAK", 3)
    sync, _ = _batch_sync(tmp_path, monkeypatch, list(range(1, 21)), _FailingSuggester(99))

    await sync.suggest_recipients_batch(limit=50)
    p = sync.batch_progress
    assert p.failed == 3
    assert p.aborted_reason is not None
    assert p.done == 0


async def test_success_resets_error_streak(tmp_path, monkeypatch):
    from app import paperless_sync as ps

    monkeypatch.setattr(ps, "BATCH_ERROR_STREAK", 3)
    # 2 Fehler, dann Erfolge — die Serie darf den Lauf nicht abbrechen.
    sync, _ = _batch_sync(tmp_path, monkeypatch, [1, 2, 3, 4, 5], _FailingSuggester(fail_first=2))

    await sync.suggest_recipients_batch(limit=50)
    p = sync.batch_progress
    assert p.aborted_reason is None
    assert p.failed == 2
    assert p.done == 3


async def test_progress_publishes_are_throttled(tmp_path, monkeypatch):
    # 30 Dokumente duerfen keine 30 SSE-Ereignisse ausloesen: die Drossel laesst
    # nur Start, Ende und hoechstens alle 2 s eines durch.
    sync, repo = _batch_sync(tmp_path, monkeypatch, list(range(1, 31)),
                             _StubSuggester("Sascha", 0.9))
    emitted: list[str] = []
    monkeypatch.setattr(repo, "notify_batch", lambda: emitted.append("batch:recipient"))

    await sync.suggest_recipients_batch(limit=50)
    # Start + Ende sind erzwungen; dazwischen darf im schnellen Testlauf nichts kommen.
    assert len(emitted) <= 4
    assert sync.batch_progress.done == 30
