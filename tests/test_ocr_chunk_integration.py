"""Integrationstest: echter `DocumentAiAdapter` + echtes `Repository` + echter Ablageort aus
der Pipeline (Befund 12 des Abschlussreviews zu e5c99df).

Kein bisheriger Test verband die reale Blockschleife mit dem realen Ablageort: `PartialFailAdapter`
in tests/test_pipeline.py reimplementiert die Blockschleife selbst, tests/test_ocr_chunk_reuse.py
fährt den echten Adapter gegen einen `MemoryStore` im Speicher, und tests/test_chunk_cache.py
testet nur das Repository für sich. Dieser Test schließt die Lücke über `run_pipeline` — den
echten Aufrufweg, der `_RepositoryChunkStore`/`SafeChunkStore` genauso baut wie im Betrieb.
"""

from types import SimpleNamespace

from pypdf import PdfReader
from reportlab.pdfgen import canvas

from app.config import Settings
from app.models import DocStatus
from app.ocr.documentai import DocumentAiAdapter
from app.pipeline import run_pipeline
from app.repository import Repository


def _settings(tmp_path, **overrides):
    base = dict(
        WATCH_DIR=str(tmp_path / "scan-in"),
        CONSUME_DIR=str(tmp_path / "consume"),
        PROCESSED_DIR=str(tmp_path / "processed"),
        ERROR_DIR=str(tmp_path / "error"),
        DB_PATH=str(tmp_path / "data" / "lector.db"),
        CHUNK_SIZE_PAGES="1",
        DOCAI_MAX_PAGES_PER_MINUTE="0",
        PREPROCESS_DESKEW="false",
        PREPROCESS_CONTRAST="false",
    )
    base.update(overrides)
    s = Settings(**base)
    s.ensure_dirs()
    return s


def _make_pdf(path, pages):
    c = canvas.Canvas(str(path))
    for i in range(pages):
        c.drawString(100, 700, f"Seite {i + 1}")
        c.showPage()
    c.save()


def _fake_document():
    """Dupliziert die Document-AI-Antwortstruktur (duck-typed, wie in tests/test_ocr.py)."""
    token = SimpleNamespace(
        layout=SimpleNamespace(
            text_anchor=SimpleNamespace(
                text_segments=[SimpleNamespace(start_index=0, end_index=4)]
            ),
            bounding_poly=SimpleNamespace(
                normalized_vertices=[
                    SimpleNamespace(x=0.1, y=0.1),
                    SimpleNamespace(x=0.4, y=0.2),
                ]
            ),
            confidence=0.9,
        )
    )
    page = SimpleNamespace(dimension=SimpleNamespace(width=100.0, height=200.0), tokens=[token])
    return SimpleNamespace(text="Wort", pages=[page])


def _empty_document():
    """HTTP 200, aber ohne Seiten — der in Befund 1 belegte Fall."""
    return SimpleNamespace(text="", pages=[])


class _EngineDouble:
    """Ersetzt `_process_chunk` hinter der Netzwerkgrenze (wie in test_ocr_chunk_reuse.py),
    damit die echte Blockschleife des Adapters ohne echte Document-AI-API läuft."""

    def __init__(self, *, fail_from=None, empty_at=None):
        self.calls: list[int] = []  # eine Seitenzahl je tatsächlichem Engine-Aufruf
        self.fail_from = fail_from
        self.empty_at = empty_at

    def __call__(self, pages):
        index = len(self.calls)
        self.calls.append(len(pages))
        if self.fail_from is not None and index >= self.fail_from:
            raise RuntimeError("Engine weg")
        if self.empty_at is not None and index == self.empty_at:
            return _empty_document()
        return _fake_document()


def _hashed_doc(repo, settings, pages):
    import hashlib

    src = settings.watch_dir / "scan.pdf"
    _make_pdf(src, pages)
    digest = hashlib.sha256(src.read_bytes()).hexdigest()
    doc_id = repo.create_document(
        original_filename="scan.pdf", source_path=str(src), file_hash=digest
    )
    return doc_id, src


def _adapter(settings, engine):
    adapter = DocumentAiAdapter(settings)
    adapter._process_chunk = engine
    return adapter


def test_real_adapter_and_real_repository_reuse_paid_chunks_across_a_retry(tmp_path):
    """Zwei Läufe: Der erste scheitert direkt nach dem ersten (bezahlten) Block, der zweite
    fragt die Engine nur noch für den Rest — mit dem echten Adapter-Loop und dem echten
    Repository-Store, so wie `run_pipeline` sie tatsächlich verdrahtet."""
    s = _settings(tmp_path)
    repo = Repository(s.db_path)
    doc_id, _ = _hashed_doc(repo, s, pages=3)

    erste_engine = _EngineDouble(fail_from=1)
    run_pipeline(doc_id, repo, s, _adapter(s, erste_engine))

    assert repo.get_document(doc_id).status == DocStatus.PENDING
    assert erste_engine.calls == [1, 1]  # Block 0 bezahlt, Block 1 versucht und gescheitert
    assert repo.count_chunk_results(doc_id) == 1  # nur der erfolgreiche Block liegt bereit

    zweite_engine = _EngineDouble()
    run_pipeline(doc_id, repo, s, _adapter(s, zweite_engine))

    assert repo.get_document(doc_id).status == DocStatus.DONE
    assert zweite_engine.calls == [1, 1]  # nur die beiden zuvor fehlenden Blöcke
    out = list(s.consume_dir.glob("*.pdf"))
    assert len(out) == 1
    assert "Wort" in PdfReader(str(out[0])).pages[0].extract_text()


def test_an_empty_engine_response_is_not_reused_on_the_retry(tmp_path):
    """Befund 1, an der echten Naht geprüft: Liefert die Engine ein Document ohne Seiten
    (HTTP 200, aber leerer Inhalt), darf dieser Block beim Wiederholversuch nicht als Treffer
    gelten — sonst heilt der fehlende Textlayer nie mehr."""
    s = _settings(tmp_path)
    repo = Repository(s.db_path)
    doc_id, _ = _hashed_doc(repo, s, pages=2)

    # Block 0 liefert eine leere Antwort (kein Fehler!), Block 1 scheitert — der Lauf endet
    # mit genau einem (leeren) bewahrten Eintrag.
    erste_engine = _EngineDouble(fail_from=1, empty_at=0)
    run_pipeline(doc_id, repo, s, _adapter(s, erste_engine))

    assert repo.get_document(doc_id).status == DocStatus.PENDING
    assert erste_engine.calls == [1, 1]
    assert repo.count_chunk_results(doc_id) == 1  # der leere Block wurde abgelegt ...

    zweite_engine = _EngineDouble()
    run_pipeline(doc_id, repo, s, _adapter(s, zweite_engine))

    assert repo.get_document(doc_id).status == DocStatus.DONE
    # ... gilt aber nicht als Treffer: Beide Blöcke wurden neu erkannt, keiner übersprungen.
    assert zweite_engine.calls == [1, 1]
    out = list(s.consume_dir.glob("*.pdf"))
    assert len(out) == 1
    assert "Wort" in PdfReader(str(out[0])).pages[0].extract_text()
    assert "Wort" in PdfReader(str(out[0])).pages[1].extract_text()
