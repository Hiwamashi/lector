"""Wiederverwendung bewahrter Blockergebnisse im Document-AI-Adapter (design.md D1/D4/D5)."""

import time
from types import SimpleNamespace

import pytest
from PIL import Image

from app.config import Settings
from app.models import OcrPage, OcrToken
from app.ocr.documentai import DocumentAiAdapter


class MemoryStore:
    """Ablageort im Speicher — die Testausführung der Schnittstelle aus `base.py`."""

    def __init__(self, preset=None):
        self.data = dict(preset or {})
        self.reads: list[int] = []
        self.writes: list[int] = []

    def get(self, chunk_index):
        self.reads.append(chunk_index)
        return self.data.get(chunk_index)

    def put(self, chunk_index, pages):
        self.writes.append(chunk_index)
        self.data[chunk_index] = pages


class ExplodingStore:
    def __init__(self, *, on_get=False, on_put=False):
        self._on_get, self._on_put = on_get, on_put

    def get(self, chunk_index):
        if self._on_get:
            raise RuntimeError("Zwischenspeicher kaputt")
        return None

    def put(self, chunk_index, pages):
        if self._on_put:
            raise RuntimeError("Ablegen kaputt")


def _settings(**overrides):
    base = dict(CHUNK_SIZE_PAGES="2", DOCAI_MAX_PAGES_PER_MINUTE="0")
    base.update(overrides)
    return Settings(_env_file=None, **base)


def _adapter(settings=None, *, fail_on=None):
    """Adapter mit ersetztem Netzwerkaufruf. `fail_on` = Index des Blocks, der wirft."""
    adapter = DocumentAiAdapter(settings or _settings())
    adapter.calls = []

    def fake_chunk(pages):
        index = len(adapter.calls)
        adapter.calls.append(len(pages))
        if fail_on is not None and index == fail_on:
            raise RuntimeError("Engine weg")
        return SimpleNamespace(
            text="Wort",
            pages=[
                SimpleNamespace(
                    dimension=SimpleNamespace(width=100.0, height=200.0),
                    tokens=[
                        SimpleNamespace(
                            layout=SimpleNamespace(
                                text_anchor=SimpleNamespace(
                                    text_segments=[SimpleNamespace(start_index=0, end_index=4)]
                                ),
                                bounding_poly=SimpleNamespace(
                                    normalized_vertices=[
                                        SimpleNamespace(x=0.1, y=0.1),
                                        SimpleNamespace(x=0.4, y=0.2),
                                    ]
                                ),
                                confidence=0.9,
                            )
                        )
                    ],
                )
                for _ in pages
            ],
        )

    adapter._process_chunk = fake_chunk
    return adapter


def _images(n):
    return [Image.new("RGB", (10, 10)) for _ in range(n)]


def _cached_pages(*indices):
    return [
        OcrPage(
            page_index=i,
            width=100.0,
            height=200.0,
            tokens=[OcrToken(text="AusSpeicher", x0=0.0, y0=0.0, x1=1.0, y1=1.0)],
        )
        for i in indices
    ]


def test_cached_chunk_skips_the_engine():
    adapter = _adapter()
    store = MemoryStore({0: _cached_pages(0, 1)})

    result = adapter.process(_images(4), store=store)

    assert adapter.calls == [2]  # nur der zweite Block ging an die Engine
    assert len(result.pages) == 4
    assert result.pages[0].tokens[0].text == "AusSpeicher"


def test_every_finished_chunk_is_stored_before_the_next_begins():
    """Der zweite Block wirft — das Ergebnis des ersten muss dennoch bewahrt sein."""
    adapter = _adapter(fail_on=1)
    store = MemoryStore()

    with pytest.raises(RuntimeError):
        adapter.process(_images(4), store=store)

    assert store.writes == [0]
    assert len(store.data[0]) == 2


def test_fully_cached_run_calls_the_engine_never():
    adapter = _adapter()
    store = MemoryStore({0: _cached_pages(0, 1), 1: _cached_pages(2, 3)})

    result = adapter.process(_images(4), store=store)

    assert adapter.calls == []
    assert [p.page_index for p in result.pages] == [0, 1, 2, 3]


def test_cached_chunks_are_not_throttled():
    """D5: Drosselung schützt die Quota — ohne Anfrage gibt es nichts zu drosseln."""
    settings = _settings(DOCAI_MAX_PAGES_PER_MINUTE="60")  # 1 Sekunde pro Seite
    adapter = _adapter(settings)
    store = MemoryStore({0: _cached_pages(0, 1), 1: _cached_pages(2, 3)})

    start = time.monotonic()
    adapter.process(_images(4), store=store)

    assert time.monotonic() - start < 0.5


def test_mixed_run_throttles_only_the_pages_actually_sent():
    settings = _settings(DOCAI_MAX_PAGES_PER_MINUTE="120")  # 0,5 s pro Seite
    adapter = _adapter(settings)
    store = MemoryStore({0: _cached_pages(0, 1)})

    start = time.monotonic()
    adapter.process(_images(4), store=store)
    dauer = time.monotonic() - start

    # Nur der zweite Block (2 Seiten) ging raus. Vier gedrosselte Seiten wären ~2 s.
    assert dauer < 1.5


def test_progress_distinguishes_cached_from_fresh_chunks():
    adapter = _adapter()
    store = MemoryStore({0: _cached_pages(0, 1)})
    seen: list[tuple[int, bool]] = []

    adapter.process(_images(4), progress=lambda n, from_cache=False: seen.append((n, from_cache)))
    seen.clear()
    adapter.process(
        _images(4), progress=lambda n, from_cache=False: seen.append((n, from_cache)), store=store
    )

    assert seen == [(2, True), (4, False)]


def test_page_indices_stay_ordered_across_a_mixed_run():
    adapter = _adapter()
    store = MemoryStore({1: _cached_pages(2, 3)})  # mittlerer Block vorbestückt

    result = adapter.process(_images(6), store=store)

    assert [p.page_index for p in result.pages] == [0, 1, 2, 3, 4, 5]
    assert adapter.calls == [2, 2]  # erster und dritter Block


def test_a_failing_store_does_not_break_the_run():
    """D4: Ein nicht bewahrter Block kostet einen Aufruf, ein Abbruch kostet alle."""
    for store in (ExplodingStore(on_get=True), ExplodingStore(on_put=True)):
        adapter = _adapter()

        result = adapter.process(_images(4), store=store)

        assert len(result.pages) == 4
        assert adapter.calls == [2, 2]


def test_without_a_store_the_adapter_behaves_as_before():
    adapter = _adapter()

    result = adapter.process(_images(3))

    assert adapter.calls == [2, 1]
    assert [p.page_index for p in result.pages] == [0, 1, 2]
