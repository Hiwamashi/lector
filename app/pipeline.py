"""Verarbeitungs-Pipeline für ein einzelnes Dokument (siehe PRD §4.4).

Läuft synchron (im Thread-Pool des Workers). Deckt beide Wege ab: E-Rechnungs-Bypass und
OCR-Veredelung. Fehler führen zu Auto-Retry (bis `retry_max`) bzw. endgültigem `failed`.
"""

from __future__ import annotations

import hashlib
import logging
import tempfile
from pathlib import Path

from .config import Settings
from .detection import detect
from .fileops import copy_into, move_into
from .fileops import file_hash as compute_file_hash
from .models import DocStatus, EventType
from .ocr.base import OcrAdapter, SafeChunkStore
from .pages import PDF_RENDER_DPI, count_pages, extract_pages
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


def _block_oversized(doc, repo: Repository, pages: int, limit: int) -> None:
    """Hält einen Vorgang an, statt ihn zu verarbeiten — ohne Fehlversuch zu zählen.

    Das Original bleibt im Eingangsordner: Es ist nicht verarbeitet und nicht gescheitert,
    und der Dublettenschutz (`find_by_hash_active`) hält `blocked` für aktiv, sodass der
    Watcher es nicht erneut aufnimmt.
    """
    repo.set_status(doc.id, DocStatus.BLOCKED)
    repo.add_event(
        doc.id,
        EventType.BLOCKED,
        f"{pages} Seiten überschreiten die Grenze von {limit} Seiten "
        "(MAX_PAGES_PER_DOCUMENT). Keine Texterkennung ausgeführt — "
        "im Web-UI freigeben oder verwerfen.",
    )
    log.info(
        "Dokument %s angehalten: %s Seiten über der Grenze von %s", doc.id, pages, limit
    )


def chunk_fingerprint(file_hash: str, settings: Settings, adapter: OcrAdapter) -> str:
    """Bindet einen bewahrten Block an Inhalt und Bedingungen seines Laufs.

    Enthalten ist alles, was das Erkennungsergebnis beeinflusst: der Inhalt des Originals,
    die Blockgrenzen, die Aufbereitung der Bilder und die befragte Engine (`adapter.identity`
    statt einzelner Einstellungen — der Fingerabdruck bleibt so engine-unabhängig, siehe
    `OcrAdapter.identity`). Ändert sich eine dieser Größen, passt der Fingerabdruck nicht
    mehr und der Block wird neu erkannt.

    `file_hash` ist die Prüfsumme der tatsächlich gelesenen Datei zum Zeitpunkt dieses
    Laufs — bewusst nicht `doc.file_hash` aus der Datenbank, das seit der Aufnahme veraltet
    sein kann (siehe `_handle_ocr`).

    Bewusst NICHT über die erzeugten Bilder: Dass Rasterung und Schieflagenkorrektur
    bitgenau reproduzierbar sind, ist nirgends belegt — ein einziges abweichendes Pixel
    würde den Zwischenspeicher dauerhaft ins Leere greifen lassen.
    """
    parts = [
        file_hash,
        str(adapter.page_limit),
        str(settings.chunk_size_pages),
        str(bool(settings.preprocess_deskew)),
        str(bool(settings.preprocess_contrast)),
        str(PDF_RENDER_DPI),
        adapter.identity,
    ]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


class _RepositoryChunkStore:
    """Bindet den engine-unabhängigen Ablageort an Vorgang und Fingerabdruck."""

    def __init__(self, repo: Repository, document_id: int, fingerprint: str) -> None:
        self._repo = repo
        self._document_id = document_id
        self._fingerprint = fingerprint

    def get(self, chunk_index: int):
        return self._repo.load_chunk_result(
            self._document_id, chunk_index, fingerprint=self._fingerprint
        )

    def put(self, chunk_index: int, pages) -> None:
        self._repo.store_chunk_result(
            self._document_id, chunk_index, fingerprint=self._fingerprint, pages=pages
        )


def _handle_ocr(doc, repo: Repository, settings: Settings, adapter: OcrAdapter) -> None:
    source = Path(doc.source_path)

    # Zählen, bevor gerastert wird: `extract_pages` rendert jede Seite bei 200 DPI, die
    # Entscheidung muss davor fallen — sonst spart die Grenze Geld und kostet Speicher.
    limit = settings.max_pages_per_document
    page_count = count_pages(source, doc.doc_type)
    repo.update_document(doc.id, total_pages=page_count)
    if limit > 0 and page_count > limit and not doc.page_limit_approved:
        _block_oversized(doc, repo, page_count, limit)
        return

    images = extract_pages(source, doc.doc_type)
    total = len(images)
    repo.update_document(doc.id, total_pages=total, ocr_engine=adapter.name, processed_pages=0)

    repo.add_event(doc.id, EventType.PREPROCESSING, f"{total} Seite(n) vorverarbeiten")
    preprocessed = [preprocess_page(img, settings) for img in images]

    def on_progress(processed: int, from_cache: bool = False) -> None:
        repo.set_progress(doc.id, processed)
        herkunft = " (aus Zwischenspeicher, keine erneute Erkennung)" if from_cache else ""
        repo.add_event(doc.id, EventType.OCR_CHUNK, f"Seite {processed} von {total}{herkunft}")

    # Ohne Prüfsumme am Vorgang kein Zwischenspeicher: Der Schlüssel trüge nicht, und ein
    # falsch zugeordnetes Ergebnis wäre schlimmer als eine erneute Erkennung.
    store = None
    if doc.file_hash:
        # Der Hash wird HIER neu aus der Datei auf der Platte gebildet, nicht aus
        # doc.file_hash übernommen: Bei einem eingeplanten Wiederholversuch bleibt das
        # Original bis zu RETRY_DELAY_MINUTES im Eingang liegen — landet in diesem Fenster
        # eine andere Datei unter demselben Namen, wäre doc.file_hash veraltet und
        # bewahrte Blöcke des alten Dokuments landeten über den Bildern des neuen.
        try:
            current_hash = compute_file_hash(source)
        except OSError:
            current_hash = None
        if current_hash is not None:
            if current_hash != doc.file_hash:
                log.warning(
                    "Prüfsumme der Datei auf der Platte weicht vom gespeicherten Wert ab "
                    "(Dokument %s): gespeichert %s…, aktuell %s… — bewahrte Blöcke greifen "
                    "dadurch von selbst nicht mehr",
                    doc.id,
                    doc.file_hash[:12],
                    current_hash[:12],
                )
            store = SafeChunkStore(
                _RepositoryChunkStore(
                    repo, doc.id, chunk_fingerprint(current_hash, settings, adapter)
                )
            )

    ocr = adapter.process(preprocessed, on_progress, store)

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
