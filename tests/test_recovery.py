from app.config import Settings
from app.fileops import file_hash as compute_file_hash
from app.models import DocStatus, Document
from app.recovery import OriginalLocation, _find_in_processed, locate_original


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


def _document(source_path, original_filename="scan.pdf", file_hash=None):
    return Document(
        id=1,
        original_filename=original_filename,
        source_path=str(source_path),
        status=DocStatus.PROCESSING,
        file_hash=file_hash,
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
    target = s.processed_dir / "scan.pdf"
    target.write_text("original")
    doc = _document(src, file_hash=compute_file_hash(target))
    assert locate_original(doc, s) == OriginalLocation.PROCESSED_DIR


def test_locate_original_in_processed_dir_with_unique_suffix(tmp_path):
    s = _settings(tmp_path)
    src = s.watch_dir / "scan.pdf"
    # unique_target haengt bei Namenskollision einen Zusatz an
    real = s.processed_dir / "scan_1.pdf"
    real.write_text("original")
    # fremde Datei mit gleichem Namensstamm und -schema, aber anderem Inhalt — eine
    # blosse `startswith(stem)`-Pruefung ohne Hash-Bestaetigung koennte sie statt der
    # echten Datei zurueckliefern und wuerde diesen Test dennoch bestehen, wenn hier
    # nur die Kategorie (PROCESSED_DIR) statt der konkreten Datei geprueft wuerde
    decoy = s.processed_dir / "scan_9.pdf"
    decoy.write_text("fremder Inhalt")
    doc = _document(src, file_hash=compute_file_hash(real))
    assert locate_original(doc, s) == OriginalLocation.PROCESSED_DIR
    assert _find_in_processed(s.processed_dir, "scan.pdf", doc.file_hash) == real


def test_locate_original_not_found(tmp_path):
    s = _settings(tmp_path)
    src = s.watch_dir / "scan.pdf"
    doc = _document(src)
    assert locate_original(doc, s) == OriginalLocation.NOT_FOUND


def test_locate_original_not_found_when_hash_missing(tmp_path):
    """Ohne bekannten `file_hash` darf ein blosser Namenstreffer nicht genuegen."""
    s = _settings(tmp_path)
    src = s.watch_dir / "scan.pdf"
    (s.processed_dir / "scan.pdf").write_text("original")
    doc = _document(src, file_hash=None)
    assert locate_original(doc, s) == OriginalLocation.NOT_FOUND


def test_locate_original_not_found_when_processed_match_has_wrong_hash(tmp_path):
    """Fehlszenario aus dem Review: Ein fremdes Dokument Y heisst zufaellig so, wie es
    `unique_target` fuer eine Namenskollision des gesuchten Originals X vergeben haette.
    X ist tatsaechlich verloren (`source_path` existiert nicht mehr) und muss `NOT_FOUND`
    liefern, statt Y als seinen Fundort zu melden.
    """
    s = _settings(tmp_path)
    src = s.watch_dir / "Rechnung.pdf"  # X: existiert nicht mehr, nie nach processed gelangt
    fremd = s.processed_dir / "Rechnung_1.pdf"  # Y: eigener, unveraenderter Name seit je her
    fremd.write_text("Inhalt von Dokument Y")
    doc = _document(src, original_filename="Rechnung.pdf", file_hash="a" * 64)
    assert compute_file_hash(fremd) != doc.file_hash
    assert locate_original(doc, s) == OriginalLocation.NOT_FOUND
