"""Seitenextraktion: Eingangsdatei → Liste von PIL-Bildern (eine pro Seite).

PDFs werden mit pypdfium2 gerendert (keine System-Abhängigkeiten), mehrseitige TIFFs
über Pillow Frame für Frame gelesen, Einzelbilder direkt geladen.
"""

from __future__ import annotations

from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageSequence

from .models import DocType

# Renderauflösung für PDF-Seiten. 200 DPI ist ein guter Kompromiss aus OCR-Qualität
# und Dateigröße (72 DPI = Skalierungsfaktor 1.0).
PDF_RENDER_DPI = 200


def render_pdf(path: Path, dpi: int = PDF_RENDER_DPI) -> list[Image.Image]:
    scale = dpi / 72.0
    images: list[Image.Image] = []
    pdf = pdfium.PdfDocument(str(path))
    try:
        for page in pdf:
            bitmap = page.render(scale=scale)
            images.append(bitmap.to_pil().convert("RGB"))
            page.close()
    finally:
        pdf.close()
    return images


def load_tiff(path: Path) -> list[Image.Image]:
    images: list[Image.Image] = []
    with Image.open(path) as img:
        for frame in ImageSequence.Iterator(img):
            images.append(frame.convert("RGB"))
    return images


def load_image(path: Path) -> list[Image.Image]:
    with Image.open(path) as img:
        return [img.convert("RGB")]


def extract_pages(path: Path, doc_type: DocType) -> list[Image.Image]:
    if doc_type == DocType.PDF:
        return render_pdf(path)
    if doc_type == DocType.TIFF:
        return load_tiff(path)
    if doc_type == DocType.IMAGE:
        return load_image(path)
    raise ValueError(f"Seitenextraktion für doc_type={doc_type} nicht unterstützt")
