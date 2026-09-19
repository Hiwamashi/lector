from app.config import Settings
from app.models import DocStatus, Document
from app.recovery import OriginalLocation, locate_original


def _settings(tmp_path, **overrides):
    base = dict(
        WATCH_DIR=str(tmp_path / "scan-in"),
        CONSUME_DIR=str(tmp_path / "consume"),
        PROCESSED_DIR=str(tmp_path / "processed"),
        ERROR_DIR=str(tmp_path / "error"),
        DB_PATH=str(tmp_path / "data" / "lector.db"),
    )
    base.update(overrides)
    s = Settings(**base)
    s.ensure_dirs()
    return s


def _document(source_path, original_filename="scan.pdf"):
    return Document(
        id=1,
        original_filename=original_filename,
        source_path=str(source_path),
        status=DocStatus.PROCESSING,
    )


def test_locate_original_in_watch_dir(tmp_path):
    s = _settings(tmp_path)
    src = s.watch_dir / "scan.pdf"
    src.write_text("original")
    doc = _document(src)
    assert locate_original(doc, s) == OriginalLocation.WATCH_DIR


def test_locate_original_in_processed_dir(tmp_path):
    s = _settings(tmp_path)
    src = s.watch_dir / "scan.pdf"  # existierte einst hier, ist inzwischen verschoben
    (s.processed_dir / "scan.pdf").write_text("original")
    doc = _document(src)
    assert locate_original(doc, s) == OriginalLocation.PROCESSED_DIR


def test_locate_original_in_processed_dir_with_unique_suffix(tmp_path):
    s = _settings(tmp_path)
    src = s.watch_dir / "scan.pdf"
    # unique_target haengt bei Namenskollision einen Zusatz an
    (s.processed_dir / "scan_1.pdf").write_text("original")
    doc = _document(src)
    assert locate_original(doc, s) == OriginalLocation.PROCESSED_DIR


def test_locate_original_not_found(tmp_path):
    s = _settings(tmp_path)
    src = s.watch_dir / "scan.pdf"
    doc = _document(src)
    assert locate_original(doc, s) == OriginalLocation.NOT_FOUND
