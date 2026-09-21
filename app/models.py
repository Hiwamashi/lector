"""Domänenmodelle: Status- und Typ-Enums sowie Datencontainer (siehe PRD §4.3)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class DocStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    # Wartezustand, kein Endzustand: Der Vorgang ist angehalten, weil die Verarbeitung
    # eine Entscheidung des Anwenders braucht. Er verlässt ihn nur durch Freigabe oder
    # Verwerfen — nie von selbst, und ohne eingeplanten Wiederholversuch.
    BLOCKED = "blocked"
    DONE = "done"
    SKIPPED_ERECHNUNG = "skipped_erechnung"
    FAILED = "failed"


class DocType(StrEnum):
    PDF = "pdf"
    TIFF = "tiff"
    IMAGE = "image"
    ERECHNUNG_XML = "erechnung_xml"
    ERECHNUNG_PDF = "erechnung_pdf"


class EventType(StrEnum):
    DETECTED = "detected"
    PREPROCESSING = "preprocessing"
    OCR_CHUNK = "ocr_chunk"
    BUILT_PDF = "built_pdf"
    MOVED_TO_CONSUME = "moved_to_consume"
    RETRY_SCHEDULED = "retry_scheduled"
    SKIPPED_ERECHNUNG = "skipped_erechnung"
    BLOCKED = "blocked"
    RELEASED = "released"
    DISCARDED = "discarded"
    FAILED = "failed"
    DONE = "done"


@dataclass
class Document:
    id: int
    original_filename: str
    source_path: str
    status: DocStatus
    file_hash: str | None = None
    doc_type: DocType | None = None
    ocr_engine: str | None = None
    total_pages: int | None = None
    processed_pages: int = 0
    attempt_count: int = 0
    next_retry_at: datetime | None = None
    error_message: str | None = None
    output_path: str | None = None
    # Ausdrücklich erteilte Freigabe trotz überschrittener Seitenobergrenze. Liegt am
    # Vorgang statt im Verlauf, weil sie die Verarbeitung steuert und nicht bloß
    # protokolliert, was geschehen ist.
    page_limit_approved: bool = False
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


@dataclass
class DocumentEvent:
    id: int
    document_id: int
    timestamp: datetime
    event_type: EventType
    message: str | None = None


class GiroStatus(StrEnum):
    """Status der GiroCode-Zahldaten zu einer Rechnung."""

    NONE = "none"        # noch keine Zahldaten ermittelt
    READY = "ready"      # automatisch ermittelt
    EDITED = "edited"    # manuell im UI korrigiert
    FAILED = "failed"    # Extraktion fehlgeschlagen


class SevdeskStatus(StrEnum):
    NONE = "none"            # nicht für Export vorgemerkt
    QUEUED = "queued"        # vorgemerkt (Tag erkannt), Bestätigung ausstehend
    EXPORTING = "exporting"  # transienter Claim während des laufenden Uploads
    EXPORTED = "exported"    # erfolgreich als Beleg nach SevDesk übertragen
    FAILED = "failed"        # eindeutig fehlgeschlagen (kein Beleg angelegt) → retrybar
    UNCERTAIN = "uncertain"  # mehrdeutig (Beleg evtl. angelegt) → kein Auto-Retry


class InvoiceEventType(StrEnum):
    SYNCED = "synced"
    GIRO_EXTRACTED = "giro_extracted"
    GIRO_EDITED = "giro_edited"
    SEVDESK_QUEUED = "sevdesk_queued"
    SEVDESK_EXPORTED = "sevdesk_exported"
    SEVDESK_FAILED = "sevdesk_failed"
    WRITTEN_BACK = "written_back"
    MARKED_PAID = "marked_paid"


@dataclass
class PaperlessInvoice:
    id: int
    paperless_id: int
    title: str | None = None
    correspondent: str | None = None
    creditor_name: str | None = None
    iban: str | None = None
    bic: str | None = None
    amount: float | None = None
    currency: str = "EUR"
    purpose: str | None = None
    source: str | None = None
    giro_status: GiroStatus = GiroStatus.NONE
    sevdesk_status: SevdeskStatus = SevdeskStatus.NONE
    sevdesk_voucher_id: str | None = None
    paid: bool = False
    exported_at: datetime | None = None
    written_back_at: datetime | None = None
    last_synced_at: datetime | None = None
    error_message: str | None = None
    document_date: datetime | None = None
    created_at: datetime | None = None


class RecipientStatus(StrEnum):
    """Zustand des KI-Empfänger-Vorschlags zu einem Paperless-Dokument."""

    NONE = "none"            # kein Vorschlag vorhanden
    SUGGESTED = "suggested"  # Vorschlag liegt vor, wartet auf Bestätigung
    APPLIED = "applied"      # Vorschlag (oder manuelle Wahl) wurde nach Paperless geschrieben
    UNKNOWN = "unknown"      # KI konnte keinen Empfänger zuordnen


@dataclass
class RecipientSuggestion:
    """Ergebnis eines KI-Empfänger-Vorschlags."""

    label: str | None       # einer der erlaubten Optionen-Labels oder None ("unbekannt")
    confidence: float        # 0..1
    reasoning: str | None = None


@dataclass
class RecipientCache:
    """Lokaler Cache des KI-Vorschlags je Paperless-Dokument (Review-Status)."""

    paperless_id: int
    suggested_label: str | None = None
    confidence: float | None = None
    reasoning: str | None = None
    status: RecipientStatus = RecipientStatus.NONE
    updated_at: datetime | None = None


@dataclass
class RecipientRow:
    """Zeile der Empfänger-Übersicht: Live-Daten aus Paperless + Cache-Vorschlag."""

    paperless_id: int
    title: str
    correspondent: str | None
    document_date: datetime | None
    current_recipient: str | None
    cache: RecipientCache | None = None


@dataclass
class OcrToken:
    """Ein erkanntes Text-Token mit Bounding-Box in normalisierten Seitenkoordinaten (0..1)."""

    text: str
    # normalisierte Box: links, oben, rechts, unten (0..1, Ursprung oben-links)
    x0: float
    y0: float
    x1: float
    y1: float
    confidence: float = 1.0


@dataclass
class OcrPage:
    page_index: int
    width: float
    height: float
    tokens: list[OcrToken] = field(default_factory=list)


@dataclass
class OcrResult:
    pages: list[OcrPage] = field(default_factory=list)


def ocr_pages_to_payload(pages: list[OcrPage]) -> list[dict]:
    """Wandelt Seiten in JSON-taugliche Daten, um sie zwischenspeichern zu können."""
    return [
        {
            "page_index": p.page_index,
            "width": p.width,
            "height": p.height,
            "tokens": [
                {
                    "text": t.text,
                    "x0": t.x0,
                    "y0": t.y0,
                    "x1": t.x1,
                    "y1": t.y1,
                    "confidence": t.confidence,
                }
                for t in p.tokens
            ],
        }
        for p in pages
    ]


def _as_float(source: dict, key: str) -> float:
    value = source.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Feld {key!r} fehlt oder ist keine Zahl: {value!r}")
    return float(value)


def ocr_pages_from_payload(data: object) -> list[OcrPage]:
    """Baut Seiten aus zwischengespeicherten Daten zurück.

    Bewusst Feld für Feld statt generisch: Ein Zwischenspeicher, der halbe oder
    fremdartige Objekte zurückgibt, würde den Fehler erst im fertigen PDF sichtbar machen.
    Wirft `ValueError`, sobald etwas nicht passt — der Aufrufer behandelt den Eintrag dann,
    als gäbe es ihn nicht.
    """
    if not isinstance(data, list):
        raise ValueError(f"Erwartet wurde eine Liste von Seiten, nicht {type(data).__name__}")
    pages: list[OcrPage] = []
    for raw_page in data:
        if not isinstance(raw_page, dict):
            raise ValueError(f"Seite ist kein Objekt: {type(raw_page).__name__}")
        index = raw_page.get("page_index")
        if isinstance(index, bool) or not isinstance(index, int):
            raise ValueError(f"page_index fehlt oder ist keine ganze Zahl: {index!r}")
        page = OcrPage(
            page_index=index,
            width=_as_float(raw_page, "width"),
            height=_as_float(raw_page, "height"),
        )
        raw_tokens = raw_page.get("tokens", [])
        if not isinstance(raw_tokens, list):
            raise ValueError("tokens ist keine Liste")
        for raw_token in raw_tokens:
            if not isinstance(raw_token, dict):
                raise ValueError(f"Token ist kein Objekt: {type(raw_token).__name__}")
            text = raw_token.get("text")
            if not isinstance(text, str):
                raise ValueError(f"text fehlt oder ist keine Zeichenkette: {text!r}")
            page.tokens.append(
                OcrToken(
                    text=text,
                    x0=_as_float(raw_token, "x0"),
                    y0=_as_float(raw_token, "y0"),
                    x1=_as_float(raw_token, "x1"),
                    y1=_as_float(raw_token, "y1"),
                    confidence=_as_float(raw_token, "confidence"),
                )
            )
        pages.append(page)
    return pages
