from PIL import Image
from pypdf import PdfReader

from app.models import OcrPage, OcrResult, OcrToken
from app.pdfbuilder import build_sandwich_pdf


def _page_image():
    return Image.new("RGB", (400, 560), "white")


def test_build_creates_multipage_pdf_with_text(tmp_path):
    images = [_page_image(), _page_image()]
    ocr = OcrResult(
        pages=[
            OcrPage(
                page_index=0,
                width=400,
                height=560,
                tokens=[OcrToken("Rechnung", 0.1, 0.1, 0.4, 0.15, 0.99)],
            ),
            OcrPage(
                page_index=1,
                width=400,
                height=560,
                tokens=[OcrToken("Seite2", 0.1, 0.1, 0.4, 0.15)],
            ),
        ]
    )
    out = build_sandwich_pdf(images, ocr, tmp_path / "out.pdf")
    reader = PdfReader(str(out))
    assert len(reader.pages) == 2
    extracted = reader.pages[0].extract_text()
    assert "Rechnung" in extracted


def test_build_without_ocr_pages_still_renders(tmp_path):
    out = build_sandwich_pdf([_page_image()], OcrResult(), tmp_path / "noocr.pdf")
    reader = PdfReader(str(out))
    assert len(reader.pages) == 1


def test_build_empty_raises(tmp_path):
    import pytest

    with pytest.raises(ValueError):
        build_sandwich_pdf([], OcrResult(), tmp_path / "x.pdf")
