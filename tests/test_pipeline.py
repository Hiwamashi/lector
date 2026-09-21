import os
import time

from pypdf import PdfReader
from reportlab.pdfgen import canvas

from app.config import Settings
from app.models import DocStatus, EventType, OcrPage, OcrResult, OcrToken
from app.ocr.base import OcrAdapter
from app.pipeline import run_pipeline
from app.repository import Repository
from app.retention import purge_processed

CII_INVOICE = (
    '<?xml version="1.0"?>'
    '<rsm:CrossIndustryInvoice '
    'xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100">'
    "<rsm:ExchangedDocument/></rsm:CrossIndustryInvoice>"
)


class FakeAdapter(OcrAdapter):
    name = "fake"

    def __init__(self, *, fail=False):
        self.fail = fail

    @property
    def page_limit(self):
        return 15

    def process(self, pages, progress=None):
        if self.fail:
            raise RuntimeError("OCR kaputt")
        result = OcrResult()
        for i, _ in enumerate(pages):
            result.pages.append(
                OcrPage(i, 400, 560, tokens=[OcrToken("Wort", 0.1, 0.1, 0.4, 0.15)])
            )
            if progress:
                progress(i + 1)
        return result


def _settings(tmp_path, **overrides):
    base = dict(
        WATCH_DIR=str(tmp_path / "scan-in"),
        CONSUME_DIR=str(tmp_path / "consume"),
        PROCESSED_DIR=str(tmp_path / "processed"),
        ERROR_DIR=str(tmp_path / "error"),
        DB_PATH=str(tmp_path / "data" / "lector.db"),
        RETRY_MAX="3",
        PREPROCESS_DESKEW="false",
        PREPROCESS_CONTRAST="false",
    )
    base.update(overrides)
    s = Settings(**base)
    s.ensure_dirs()
    return s


def _make_pdf(path, pages=2):
    c = canvas.Canvas(str(path))
    for i in range(pages):
        c.drawString(100, 700, f"Seite {i + 1}")
        c.showPage()
    c.save()


def test_ocr_path_produces_searchable_pdf(tmp_path):
    s = _settings(tmp_path)
    repo = Repository(s.db_path)
    src = s.watch_dir / "scan.pdf"
    _make_pdf(src, pages=2)
    doc_id = repo.create_document(original_filename="scan.pdf", source_path=str(src))

    run_pipeline(doc_id, repo, s, FakeAdapter())

    doc = repo.get_document(doc_id)
    assert doc.status == DocStatus.DONE
    assert doc.total_pages == 2
    assert doc.processed_pages == 2
    assert not src.exists()  # Original verschoben
    assert (s.processed_dir / "scan.pdf").exists()
    out = list(s.consume_dir.glob("*.pdf"))
    assert len(out) == 1
    assert "Wort" in PdfReader(str(out[0])).pages[0].extract_text()


def test_erechnung_bypass(tmp_path):
    s = _settings(tmp_path)
    repo = Repository(s.db_path)
    src = s.watch_dir / "rechnung.xml"
    src.write_text(CII_INVOICE, encoding="utf-8")
    doc_id = repo.create_document(original_filename="rechnung.xml", source_path=str(src))

    run_pipeline(doc_id, repo, s, FakeAdapter())

    doc = repo.get_document(doc_id)
    assert doc.status == DocStatus.SKIPPED_ERECHNUNG
    assert (s.consume_dir / "rechnung.xml").exists()  # unverändert durchgereicht
    assert (s.processed_dir / "rechnung.xml").exists()
    assert not list(s.consume_dir.glob("*.pdf"))  # keine OCR


def test_failure_schedules_retry_then_fails(tmp_path):
    s = _settings(tmp_path, RETRY_MAX="3")
    repo = Repository(s.db_path)
    src = s.watch_dir / "scan.pdf"
    _make_pdf(src, pages=1)
    doc_id = repo.create_document(original_filename="scan.pdf", source_path=str(src))
    adapter = FakeAdapter(fail=True)

    # Versuch 1 + 2 -> Retry eingeplant, Status zurück auf pending
    run_pipeline(doc_id, repo, s, adapter)
    d = repo.get_document(doc_id)
    assert d.status == DocStatus.PENDING
    assert d.attempt_count == 1
    assert d.next_retry_at is not None

    run_pipeline(doc_id, repo, s, adapter)
    assert repo.get_document(doc_id).attempt_count == 2

    # Versuch 3 -> endgültig failed, Original nach error
    run_pipeline(doc_id, repo, s, adapter)
    d = repo.get_document(doc_id)
    assert d.status == DocStatus.FAILED
    assert d.attempt_count == 3
    assert d.error_message and "OCR kaputt" in d.error_message
    assert (s.error_dir / "scan.pdf").exists()


def test_retention_purges_old_files(tmp_path):
    s = _settings(tmp_path, PROCESSED_RETENTION_DAYS="30")
    old = s.processed_dir / "old.pdf"
    new = s.processed_dir / "new.pdf"
    old.write_bytes(b"x")
    new.write_bytes(b"y")
    old_time = time.time() - 40 * 86400
    os.utime(old, (old_time, old_time))

    deleted = purge_processed(s.processed_dir, 30)
    assert deleted == 1
    assert not old.exists()
    assert new.exists()


class CountingAdapter(FakeAdapter):
    """Merkt sich, ob die Engine überhaupt befragt wurde."""

    def __init__(self):
        super().__init__()
        self.calls = 0

    def process(self, pages, progress=None):
        self.calls += 1
        return super().process(pages, progress)


def test_oversized_document_is_blocked_without_calling_the_engine(tmp_path):
    s = _settings(tmp_path, MAX_PAGES_PER_DOCUMENT="3")
    repo = Repository(s.db_path)
    src = s.watch_dir / "stapel.pdf"
    _make_pdf(src, pages=5)
    doc_id = repo.create_document(original_filename="stapel.pdf", source_path=str(src))
    adapter = CountingAdapter()

    run_pipeline(doc_id, repo, s, adapter)

    doc = repo.get_document(doc_id)
    assert doc.status == DocStatus.BLOCKED
    assert adapter.calls == 0
    assert doc.total_pages == 5
    assert src.exists()  # Original bleibt im Eingang
    assert not list(s.consume_dir.glob("*"))


def test_document_exactly_on_the_limit_is_processed(tmp_path):
    s = _settings(tmp_path, MAX_PAGES_PER_DOCUMENT="2")
    repo = Repository(s.db_path)
    src = s.watch_dir / "scan.pdf"
    _make_pdf(src, pages=2)
    doc_id = repo.create_document(original_filename="scan.pdf", source_path=str(src))

    run_pipeline(doc_id, repo, s, FakeAdapter())

    assert repo.get_document(doc_id).status == DocStatus.DONE


def test_limit_zero_disables_the_check(tmp_path):
    s = _settings(tmp_path, MAX_PAGES_PER_DOCUMENT="0")
    repo = Repository(s.db_path)
    src = s.watch_dir / "stapel.pdf"
    _make_pdf(src, pages=6)
    doc_id = repo.create_document(original_filename="stapel.pdf", source_path=str(src))

    run_pipeline(doc_id, repo, s, FakeAdapter())

    assert repo.get_document(doc_id).status == DocStatus.DONE


def test_erechnung_over_the_limit_passes_through(tmp_path):
    """An E-Rechnungen findet keine Texterkennung statt — die Grenze greift dort nicht."""
    s = _settings(tmp_path, MAX_PAGES_PER_DOCUMENT="1")
    repo = Repository(s.db_path)
    src = s.watch_dir / "rechnung.xml"
    src.write_text(CII_INVOICE, encoding="utf-8")
    doc_id = repo.create_document(original_filename="rechnung.xml", source_path=str(src))

    run_pipeline(doc_id, repo, s, FakeAdapter())

    assert repo.get_document(doc_id).status == DocStatus.SKIPPED_ERECHNUNG
    assert (s.consume_dir / "rechnung.xml").exists()


def test_blocking_counts_no_attempt_and_schedules_no_retry(tmp_path):
    s = _settings(tmp_path, MAX_PAGES_PER_DOCUMENT="1")
    repo = Repository(s.db_path)
    src = s.watch_dir / "stapel.pdf"
    _make_pdf(src, pages=4)
    doc_id = repo.create_document(original_filename="stapel.pdf", source_path=str(src))

    run_pipeline(doc_id, repo, s, FakeAdapter())

    doc = repo.get_document(doc_id)
    assert doc.attempt_count == 0
    assert doc.next_retry_at is None
    assert doc.finished_at is None
    assert not repo.claim_due_retries()  # wird nicht wieder eingereiht


def test_block_event_names_pages_and_limit(tmp_path):
    s = _settings(tmp_path, MAX_PAGES_PER_DOCUMENT="3")
    repo = Repository(s.db_path)
    src = s.watch_dir / "stapel.pdf"
    _make_pdf(src, pages=9)
    doc_id = repo.create_document(original_filename="stapel.pdf", source_path=str(src))

    run_pipeline(doc_id, repo, s, FakeAdapter())

    blocked = [e for e in repo.list_events(doc_id) if e["event_type"] == EventType.BLOCKED]
    assert len(blocked) == 1
    assert "9" in blocked[0]["message"]
    assert "3" in blocked[0]["message"]


def test_approved_document_skips_the_check(tmp_path):
    s = _settings(tmp_path, MAX_PAGES_PER_DOCUMENT="2")
    repo = Repository(s.db_path)
    src = s.watch_dir / "stapel.pdf"
    _make_pdf(src, pages=5)
    doc_id = repo.create_document(original_filename="stapel.pdf", source_path=str(src))
    repo.update_document(doc_id, page_limit_approved=True)

    run_pipeline(doc_id, repo, s, FakeAdapter())

    doc = repo.get_document(doc_id)
    assert doc.status == DocStatus.DONE
    assert doc.processed_pages == 5


def test_uncountable_file_goes_to_the_normal_failure_path(tmp_path):
    """Eine Datei, die sich nicht zählen lässt, ist ein Fehler — keine Blockade."""
    s = _settings(tmp_path, MAX_PAGES_PER_DOCUMENT="3")
    repo = Repository(s.db_path)
    src = s.watch_dir / "kaputt.pdf"
    src.write_bytes(b"%PDF-1.4 das ist kein gueltiges PDF")
    doc_id = repo.create_document(original_filename="kaputt.pdf", source_path=str(src))

    run_pipeline(doc_id, repo, s, FakeAdapter())

    doc = repo.get_document(doc_id)
    assert doc.status == DocStatus.PENDING  # Wiederholversuch eingeplant
    assert doc.attempt_count == 1
    assert doc.next_retry_at is not None


def test_retention_leaves_blocked_originals_in_the_watch_folder(tmp_path):
    """6.4: Angehaltene Originale liegen im Eingang, nicht in `processed` — der
    Aufbewahrungsjob darf sie nicht anfassen, egal wie alt sie sind."""
    s = _settings(tmp_path, PROCESSED_RETENTION_DAYS="30")
    src = s.watch_dir / "stapel.pdf"
    _make_pdf(src, pages=3)
    alt = time.time() - 60 * 60 * 24 * 90
    os.utime(src, (alt, alt))

    assert purge_processed(s.processed_dir, 30) == 0
    assert src.exists()
