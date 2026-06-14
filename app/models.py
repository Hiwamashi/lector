"""Domänenmodelle: Status- und Typ-Enums sowie Datencontainer (siehe PRD §4.3)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class DocStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
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
