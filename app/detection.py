"""Deterministische Format- und E-Rechnungs-Erkennung (siehe PRD §4.4).

E-Rechnungen werden ohne KI/OCR rein anhand von Struktur und Metadaten erkannt:
- XRechnung: XML mit Root `Invoice` (UBL) bzw. `CrossIndustryInvoice` (UN/CEFACT CII).
- ZUGFeRD/Factur-X: PDF mit eingebetteter Rechnungs-XML bzw. entsprechenden XMP-Metadaten.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import pikepdf

from .models import DocType

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
TIFF_SUFFIXES = {".tif", ".tiff"}
PDF_SUFFIXES = {".pdf"}
XML_SUFFIXES = {".xml"}

# Lokalnamen der akzeptierten E-Rechnungs-Root-Elemente (Namespace-agnostisch geprüft).
_EINVOICE_ROOTS = {"invoice", "crossindustryinvoice"}

# Bekannte Dateinamen eingebetteter Rechnungs-XML in ZUGFeRD/Factur-X-PDFs.
_EMBEDDED_INVOICE_NAMES = {
    "factur-x.xml",
    "zugferd-invoice.xml",
    "xrechnung.xml",
    "cii.xml",
}


@dataclass
class Detection:
    doc_type: DocType
    is_erechnung: bool


def _local_name(tag: str) -> str:
    """Entfernt einen evtl. vorhandenen Namespace-Präfix aus einem XML-Tag."""
    return tag.rsplit("}", 1)[-1].lower()


def is_erechnung_xml(path: Path) -> bool:
    try:
        # Nur das Root-Element lesen reicht zur Klassifizierung.
        for _event, elem in ET.iterparse(path, events=("start",)):
            return _local_name(elem.tag) in _EINVOICE_ROOTS
    except (ET.ParseError, OSError):
        return False
    return False


def pdf_has_embedded_invoice(path: Path) -> bool:
    try:
        with pikepdf.open(path) as pdf:
            try:
                attachments = pdf.attachments
            except Exception:
                attachments = {}
            for name in attachments:
                if name.lower() in _EMBEDDED_INVOICE_NAMES:
                    return True
            # XMP-Metadaten auf Factur-X/ZUGFeRD-Kennung prüfen
            try:
                meta = str(pdf.Root.Metadata.read_bytes()).lower()
            except Exception:
                meta = ""
            if "factur-x" in meta or "zugferd" in meta or "fx:documenttype" in meta:
                return True
    except Exception:
        return False
    return False


def detect(path: Path) -> Detection:
    suffix = path.suffix.lower()

    if suffix in XML_SUFFIXES:
        if is_erechnung_xml(path):
            return Detection(DocType.ERECHNUNG_XML, is_erechnung=True)
        # XML ohne Rechnungs-Root: für die OCR-Pipeline ungeeignet, aber als XML markieren.
        return Detection(DocType.ERECHNUNG_XML, is_erechnung=False)

    if suffix in PDF_SUFFIXES:
        if pdf_has_embedded_invoice(path):
            return Detection(DocType.ERECHNUNG_PDF, is_erechnung=True)
        return Detection(DocType.PDF, is_erechnung=False)

    if suffix in TIFF_SUFFIXES:
        return Detection(DocType.TIFF, is_erechnung=False)

    if suffix in IMAGE_SUFFIXES:
        return Detection(DocType.IMAGE, is_erechnung=False)

    # Unbekannte Endung: als Bild behandeln; die Pipeline meldet ggf. einen Fehler.
    return Detection(DocType.IMAGE, is_erechnung=False)


SUPPORTED_SUFFIXES = IMAGE_SUFFIXES | TIFF_SUFFIXES | PDF_SUFFIXES | XML_SUFFIXES


def is_supported(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_SUFFIXES
