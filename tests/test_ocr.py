import json
import time
from types import SimpleNamespace

import pytest

from app.models import OcrPage, OcrToken, ocr_pages_from_payload, ocr_pages_to_payload
from app.ocr.base import RateLimiter, chunked
from app.ocr.documentai import document_to_pages


def test_chunked_splits_correctly():
    assert list(chunked(list(range(7)), 3)) == [[0, 1, 2], [3, 4, 5], [6]]
    assert list(chunked([], 3)) == []


def test_rate_limiter_disabled_does_not_sleep():
    rl = RateLimiter(0)
    start = time.monotonic()
    rl.acquire(100)
    assert time.monotonic() - start < 0.05


def test_rate_limiter_throttles():
    # 6000 Seiten/min -> 0.01 s/Seite; 3 Seiten -> >= 0.03 s bis zur nächsten Freigabe
    rl = RateLimiter(6000)
    rl.acquire(3)  # setzt next_allowed
    start = time.monotonic()
    rl.acquire(1)
    assert time.monotonic() - start >= 0.025


def _fake_document():
    """Dupliziert die von Document AI gelieferte Struktur (duck-typed)."""
    token = SimpleNamespace(
        layout=SimpleNamespace(
            text_anchor=SimpleNamespace(
                text_segments=[SimpleNamespace(start_index=0, end_index=5)]
            ),
            bounding_poly=SimpleNamespace(
                normalized_vertices=[
                    SimpleNamespace(x=0.1, y=0.2),
                    SimpleNamespace(x=0.4, y=0.2),
                    SimpleNamespace(x=0.4, y=0.3),
                    SimpleNamespace(x=0.1, y=0.3),
                ]
            ),
            confidence=0.95,
        )
    )
    page = SimpleNamespace(dimension=SimpleNamespace(width=600, height=800), tokens=[token])
    return SimpleNamespace(text="Hallo Welt", pages=[page])


def test_document_to_pages_maps_tokens_and_offset():
    pages = document_to_pages(_fake_document(), page_offset=2)
    assert len(pages) == 1
    page = pages[0]
    assert page.page_index == 2
    assert page.width == 600 and page.height == 800
    assert len(page.tokens) == 1
    tok = page.tokens[0]
    assert tok.text == "Hallo"
    assert (tok.x0, tok.y0, tok.x1, tok.y1) == (0.1, 0.2, 0.4, 0.3)
    assert abs(tok.confidence - 0.95) < 1e-6


# ---------------------------------------------------------------------------
# Serialisierung der Ergebnisstruktur (Zwischenspeicher, openspec design.md D3)
# ---------------------------------------------------------------------------


def _sample_pages():
    return [
        OcrPage(
            page_index=3,
            width=1240.0,
            height=1754.0,
            tokens=[
                OcrToken(text="Rechnung", x0=0.1, y0=0.05, x1=0.3, y1=0.09, confidence=0.98),
                OcrToken(text="1.234,56 €", x0=0.7, y0=0.5, x1=0.9, y1=0.54, confidence=0.71),
            ],
        ),
        OcrPage(page_index=4, width=1240.0, height=1754.0),
    ]


def test_payload_roundtrip_preserves_every_field():
    original = _sample_pages()

    restored = ocr_pages_from_payload(json.loads(json.dumps(ocr_pages_to_payload(original))))

    assert restored == original
    first = restored[0].tokens[1]
    assert first.text == "1.234,56 €"
    assert (first.x0, first.y0, first.x1, first.y1) == (0.7, 0.5, 0.9, 0.54)
    assert first.confidence == 0.71
    assert restored[1].tokens == []


@pytest.mark.parametrize(
    "broken",
    [
        [{"width": 1.0, "height": 2.0, "tokens": []}],  # page_index fehlt
        [{"page_index": 0, "height": 2.0, "tokens": []}],  # width fehlt
        [{"page_index": "null", "width": 1.0, "height": 2.0, "tokens": []}],  # falscher Typ
        [{"page_index": 0, "width": "breit", "height": 2.0, "tokens": []}],  # falscher Typ
        [{"page_index": 0, "width": 1.0, "height": 2.0, "tokens": {}}],  # tokens keine Liste
        [{"page_index": 0, "width": 1.0, "height": 2.0, "tokens": [{"x0": 0.1}]}],  # text fehlt
        [{"page_index": 0, "width": 1.0, "height": 2.0, "tokens": [{"text": 5, "x0": 0.1}]}],
        [
            {  # Koordinate fehlt
                "page_index": 0,
                "width": 1.0,
                "height": 2.0,
                "tokens": [{"text": "a", "x0": 0.1, "y0": 0.1, "x1": 0.2, "confidence": 1.0}],
            }
        ],
        "keine Liste",
        {},
        [None],
        None,
    ],
)
def test_payload_rejects_broken_data(broken):
    with pytest.raises(ValueError):
        ocr_pages_from_payload(broken)


