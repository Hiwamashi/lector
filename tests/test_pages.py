"""Seitenzählung ohne Rasterung (siehe openspec design.md D1)."""

import pypdfium2 as pdfium
import pytest
from PIL import Image
from reportlab.pdfgen import canvas

from app.models import DocType
from app.pages import count_pages, extract_pages


def _make_pdf(path, pages=2):
    c = canvas.Canvas(str(path))
    for i in range(pages):
        c.drawString(100, 700, f"Seite {i + 1}")
        c.showPage()
    c.save()


def _make_tiff(path, frames=3):
    imgs = [Image.new("RGB", (60, 80), (i * 40, 120, 200)) for i in range(frames)]
    imgs[0].save(str(path), save_all=True, append_images=imgs[1:])


def _make_png(path):
    Image.new("RGB", (40, 50), (10, 20, 30)).save(str(path))


@pytest.mark.parametrize("pages", [1, 2, 7])
def test_count_pages_pdf(tmp_path, pages):
    src = tmp_path / "scan.pdf"
    _make_pdf(src, pages=pages)

    assert count_pages(src, DocType.PDF) == pages


@pytest.mark.parametrize("frames", [1, 3])
def test_count_pages_tiff(tmp_path, frames):
    src = tmp_path / "scan.tiff"
    _make_tiff(src, frames=frames)

    assert count_pages(src, DocType.TIFF) == frames


def test_count_pages_single_image(tmp_path):
    src = tmp_path / "foto.png"
    _make_png(src)

    assert count_pages(src, DocType.IMAGE) == 1


def test_count_pages_rejects_unsupported_type(tmp_path):
    src = tmp_path / "rechnung.xml"
    src.write_text("<Invoice/>", encoding="utf-8")

    with pytest.raises(ValueError):
        count_pages(src, DocType.ERECHNUNG_XML)


def test_count_matches_extraction_for_pdf(tmp_path):
    """D1: eine Abweichung würde nach einer Zahl blockieren, die später nicht gilt."""
    src = tmp_path / "scan.pdf"
    _make_pdf(src, pages=5)

    assert count_pages(src, DocType.PDF) == len(extract_pages(src, DocType.PDF))


def test_count_matches_extraction_for_tiff(tmp_path):
    src = tmp_path / "scan.tiff"
    _make_tiff(src, frames=4)

    assert count_pages(src, DocType.TIFF) == len(extract_pages(src, DocType.TIFF))


def test_count_matches_extraction_for_image(tmp_path):
    src = tmp_path / "foto.png"
    _make_png(src)

    assert count_pages(src, DocType.IMAGE) == len(extract_pages(src, DocType.IMAGE))


def test_counting_does_not_rasterize(tmp_path, monkeypatch):
    """Die Zählung darf keine Seite rendern — sonst verschiebt die Grenze den Schaden
    nur von Geld auf Arbeitsspeicher."""
    src = tmp_path / "scan.pdf"
    _make_pdf(src, pages=3)

    def explode(*args, **kwargs):
        raise AssertionError("render() darf beim Zählen nicht aufgerufen werden")

    monkeypatch.setattr(pdfium.PdfPage, "render", explode)

    assert count_pages(src, DocType.PDF) == 3

    # Gegenprobe: derselbe Patch bringt die Extraktion zu Fall — er greift also.
    with pytest.raises(AssertionError):
        extract_pages(src, DocType.PDF)
