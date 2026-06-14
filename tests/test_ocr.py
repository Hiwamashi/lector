import time
from types import SimpleNamespace

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
