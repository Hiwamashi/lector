"""Verarbeitungs-Pipeline für ein einzelnes Dokument (siehe PRD §4.4).

Läuft synchron (im Thread-Pool des Workers). Deckt beide Wege ab: E-Rechnungs-Bypass und
OCR-Veredelung. Fehler führen zu Auto-Retry (bis `retry_max`) bzw. endgültigem `failed`.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from .config import Settings
from .detection import detect
from .fileops import copy_into, move_into
from .models import DocStatus, EventType
from .ocr.base import OcrAdapter
from .pages import extract_pages
from .pdfbuilder import build_sandwich_pdf
from .preprocessing import preprocess_page
from .repository import Repository

log = logging.getLogger("lector.pipeline")


def _output_pdf_name(original_filename: str) -> str:
    return f"{Path(original_filename).stem}.pdf"


def _handle_erechnung(doc, repo: Repository, settings: Settings) -> None:
    source = Path(doc.source_path)
    target = copy_into(source, settings.consume_dir, uid=settings.puid, gid=settings.pgid)
    repo.update_document(doc.id, output_path=str(target))
    repo.add_event(doc.id, EventType.MOVED_TO_CONSUME, f"unverändert nach {target.name}")
    move_into(source, settings.processed_dir)
    repo.set_status(doc.id, DocStatus.SKIPPED_ERECHNUNG)
    repo.add_event(doc.id, EventType.SKIPPED_ERECHNUNG, "E-Rechnung unverändert durchgereicht")


def _handle_ocr(doc, repo: Repository, settings: Settings, adapter: OcrAdapter) -> None:
    source = Path(doc.source_path)
    images = extract_pages(source, doc.doc_type)
    total = len(images)
    repo.update_document(doc.id, total_pages=total, ocr_engine=adapter.name, processed_pages=0)

    repo.add_event(doc.id, EventType.PREPROCESSING, f"{total} Seite(n) vorverarbeiten")
    preprocessed = [preprocess_page(img, settings) for img in images]

    def on_progress(processed: int) -> None:
        repo.set_progress(doc.id, processed)
        repo.add_event(doc.id, EventType.OCR_CHUNK, f"Seite {processed} von {total}")

    ocr = adapter.process(preprocessed, on_progress)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_pdf = Path(tmp) / _output_pdf_name(doc.original_filename)
        build_sandwich_pdf(preprocessed, ocr, tmp_pdf)
        repo.add_event(doc.id, EventType.BUILT_PDF, "Sandwich-PDF erzeugt")
        renamed = tmp_pdf.with_name(_output_pdf_name(doc.original_filename))
        if renamed != tmp_pdf:
            tmp_pdf.rename(renamed)
        target = move_into(renamed, settings.consume_dir, uid=settings.puid, gid=settings.pgid)

    repo.update_document(doc.id, output_path=str(target))
    repo.add_event(doc.id, EventType.MOVED_TO_CONSUME, f"nach {target.name}")
    move_into(source, settings.processed_dir)
    repo.set_status(doc.id, DocStatus.DONE)
    repo.add_event(doc.id, EventType.DONE, "fertig")


def _handle_failure(doc, repo: Repository, settings: Settings, error: Exception) -> None:
    repo.increment_attempt(doc.id)
    refreshed = repo.get_document(doc.id)
    attempt = refreshed.attempt_count if refreshed else doc.attempt_count + 1
    message = f"{type(error).__name__}: {error}"
    log.exception("Verarbeitung fehlgeschlagen für Dokument %s", doc.id)
    if attempt < settings.retry_max:
        retry_at = repo.schedule_retry(doc.id, settings.retry_delay_minutes)
        repo.add_event(
            doc.id,
            EventType.RETRY_SCHEDULED,
            f"Versuch {attempt}/{settings.retry_max} fehlgeschlagen; erneut um "
            f"{retry_at:%Y-%m-%d %H:%M} UTC. Grund: {message}",
        )
    else:
        source = Path(doc.source_path)
        if source.exists():
            move_into(source, settings.error_dir)
        repo.set_status(doc.id, DocStatus.FAILED, error_message=message)
        repo.add_event(doc.id, EventType.FAILED, f"endgültig fehlgeschlagen: {message}")


def run_pipeline(
    document_id: int, repo: Repository, settings: Settings, adapter: OcrAdapter
) -> None:
    doc = repo.get_document(document_id)
    if doc is None:
        log.warning("Dokument %s nicht gefunden", document_id)
        return

    repo.set_status(doc.id, DocStatus.PROCESSING)
    try:
        detection = detect(Path(doc.source_path))
        repo.update_document(doc.id, doc_type=detection.doc_type)
        repo.add_event(
            doc.id,
            EventType.DETECTED,
            f"Typ={detection.doc_type}, E-Rechnung={detection.is_erechnung}",
        )
        if detection.is_erechnung:
            _handle_erechnung(doc, repo, settings)
        else:
            # doc neu laden, damit doc_type für die Seitenextraktion gesetzt ist
            doc = repo.get_document(document_id)
            _handle_ocr(doc, repo, settings, adapter)
    except Exception as error:  # noqa: BLE001 — bewusst breit für Retry-Logik
        _handle_failure(doc, repo, settings, error)
