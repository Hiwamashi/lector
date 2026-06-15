"""Tests für die Empfänger-Zuordnung: Client-Helfer, LLM-Parsing und Repository-Cache."""

from __future__ import annotations

import pytest

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

    # Kleine Seitengröße + Deckel, damit der frühere Bug (immer dieselbe erste Seite)
    # ohne den Skip greifen würde.
    monkeypatch.setattr(ps, "RECIPIENT_PAGE_SIZE", 2)
    monkeypatch.setattr(ps, "RECIPIENT_BATCH_MAX", 2)

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

    ids = await sync._collect_missing_ids(client, field)
    # Trotz Deckel=2 dürfen die gecachten 1,2 nicht alles belegen — 3,4 müssen drankommen.
    assert ids == [3, 4]


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
