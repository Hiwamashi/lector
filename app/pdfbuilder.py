"""Sandwich-PDF-Bau: vorverarbeitetes Bild als sichtbare Ebene + unsichtbarer,
durchsuchbarer Textlayer aus den OCR-Token (siehe PRD §3.1).

Die OCR-Token liegen in normalisierten Seitenkoordinaten (0..1, Ursprung oben-links). Die
PDF-Seitengröße wird auf die Bildpixel (1 px = 1 pt) gesetzt; Bild und Text werden auf diese
Fläche abgebildet. Der Text wird mit Render-Modus 3 (unsichtbar) gezeichnet und horizontal so
skaliert, dass er die Token-Box ausfüllt — das verbessert die Text-Markierung im Viewer.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from .models import OcrPage, OcrResult

_FONT = "Helvetica"


def _draw_page(c: canvas.Canvas, image: Image.Image, ocr_page: OcrPage | None) -> None:
    width, height = image.size
    c.setPageSize((width, height))
    c.drawImage(ImageReader(image), 0, 0, width=width, height=height)

    if ocr_page is None:
        c.showPage()
        return

    text = c.beginText()
    text.setTextRenderMode(3)  # unsichtbar
    for token in ocr_page.tokens:
        content = token.text.strip()
        if not content:
            continue
        box_w = max((token.x1 - token.x0) * width, 1.0)
        box_h = max((token.y1 - token.y0) * height, 1.0)
        font_size = max(box_h * 0.8, 1.0)
        base_w = stringWidth(content, _FONT, font_size) or box_w
        horiz_scale = max(min(box_w / base_w * 100.0, 1000.0), 1.0)
        # PDF-Ursprung unten-links: y von oben nach unten spiegeln, Baseline an Box-Unterkante.
        x = token.x0 * width
        y = height - token.y1 * height
        text.setFont(_FONT, font_size)
        text.setHorizScale(horiz_scale)
        text.setTextOrigin(x, y)
        text.textOut(content)
    c.drawText(text)
    c.showPage()


def build_sandwich_pdf(
    images: list[Image.Image], ocr: OcrResult, output_path: Path
) -> Path:
    if not images:
        raise ValueError("Keine Seiten zum Erzeugen des PDFs")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pages_by_index = {p.page_index: p for p in ocr.pages}
    c = canvas.Canvas(str(output_path))
    for idx, image in enumerate(images):
        _draw_page(c, image.convert("RGB"), pages_by_index.get(idx))
    c.save()
    return output_path
