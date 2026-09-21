"""Freigeben und Verwerfen eines angehaltenen Vorgangs (openspec design.md D5)."""

from app.config import Settings
from app.decisions import DecisionResult, discard_document, release_document
from app.models import DocStatus, EventType
from app.repository import Repository


def _settings(tmp_path, **overrides):
    base = dict(
        WATCH_DIR=str(tmp_path / "scan-in"),
        CONSUME_DIR=str(tmp_path / "consume"),
        PROCESSED_DIR=str(tmp_path / "processed"),
        ERROR_DIR=str(tmp_path / "error"),
        DB_PATH=str(tmp_path / "data" / "lector.db"),
        MAX_PAGES_PER_DOCUMENT="3",
    )
    base.update(overrides)
    s = Settings(_env_file=None, **base)
    s.ensure_dirs()
    return s


def _blocked_doc(repo, settings, *, pages=9, name="stapel.pdf", with_file=True):
    src = settings.watch_dir / name
    if with_file:
        src.write_bytes(b"%PDF-1.4 inhalt")
    doc_id = repo.create_document(original_filename=name, source_path=str(src))
    repo.update_document(doc_id, total_pages=pages)
    repo.set_status(doc_id, DocStatus.BLOCKED)
    return doc_id, src


def _event_kinds(repo, doc_id):
    return [e["event_type"] for e in repo.list_events(doc_id)]


def test_release_requeues_and_marks_approval(tmp_path):
    s = _settings(tmp_path)
    repo = Repository(s.db_path)
    doc_id, src = _blocked_doc(repo, s)

    assert release_document(doc_id, repo, s) == DecisionResult.RELEASED

    doc = repo.get_document(doc_id)
    assert doc.status == DocStatus.PENDING
    assert doc.page_limit_approved is True
    assert doc.attempt_count == 0
    assert doc.next_retry_at is None
    assert EventType.RELEASED in _event_kinds(repo, doc_id)
    assert src.exists()
    assert [d.id for d in repo.claim_due_retries()] == [doc_id]


def test_release_without_original_fails_with_explanation(tmp_path):
    s = _settings(tmp_path)
    repo = Repository(s.db_path)
    doc_id, src = _blocked_doc(repo, s)
    src.unlink()

    assert release_document(doc_id, repo, s) == DecisionResult.SOURCE_MISSING

    doc = repo.get_document(doc_id)
    assert doc.status == DocStatus.FAILED
    assert "Eingangsordner" in doc.error_message
    assert not repo.claim_due_retries()


def test_discard_moves_original_to_error_dir(tmp_path):
    s = _settings(tmp_path)
    repo = Repository(s.db_path)
    doc_id, src = _blocked_doc(repo, s)

    assert discard_document(doc_id, repo, s) == DecisionResult.DISCARDED

    doc = repo.get_document(doc_id)
    assert doc.status == DocStatus.FAILED
    assert "Verworfen" in doc.error_message
    assert not src.exists()
    assert (s.error_dir / "stapel.pdf").exists()
    assert EventType.DISCARDED in _event_kinds(repo, doc_id)


def test_decision_on_a_document_that_is_not_blocked_does_nothing(tmp_path):
    s = _settings(tmp_path)
    repo = Repository(s.db_path)
    src = s.watch_dir / "normal.pdf"
    src.write_bytes(b"%PDF-1.4 inhalt")
    doc_id = repo.create_document(original_filename="normal.pdf", source_path=str(src))

    assert release_document(doc_id, repo, s) == DecisionResult.NOT_BLOCKED
    assert discard_document(doc_id, repo, s) == DecisionResult.NOT_BLOCKED

    doc = repo.get_document(doc_id)
    assert doc.status == DocStatus.PENDING
    assert doc.page_limit_approved is False
    assert src.exists()


def test_second_release_is_without_effect(tmp_path):
    s = _settings(tmp_path)
    repo = Repository(s.db_path)
    doc_id, _ = _blocked_doc(repo, s)

    assert release_document(doc_id, repo, s) == DecisionResult.RELEASED
    assert release_document(doc_id, repo, s) == DecisionResult.NOT_BLOCKED

    assert _event_kinds(repo, doc_id).count(EventType.RELEASED) == 1


def test_discard_after_release_does_not_move_the_original(tmp_path):
    """Sonst wanderte das Original in den Fehlerordner, während der Vorgang schon läuft."""
    s = _settings(tmp_path)
    repo = Repository(s.db_path)
    doc_id, src = _blocked_doc(repo, s)

    assert release_document(doc_id, repo, s) == DecisionResult.RELEASED
    assert discard_document(doc_id, repo, s) == DecisionResult.NOT_BLOCKED

    assert src.exists()
    assert not list(s.error_dir.iterdir())
    assert repo.get_document(doc_id).status == DocStatus.PENDING


def test_release_after_discard_does_not_requeue(tmp_path):
    s = _settings(tmp_path)
    repo = Repository(s.db_path)
    doc_id, _ = _blocked_doc(repo, s)

    assert discard_document(doc_id, repo, s) == DecisionResult.DISCARDED
    assert release_document(doc_id, repo, s) == DecisionResult.NOT_BLOCKED

    doc = repo.get_document(doc_id)
    assert doc.status == DocStatus.FAILED
    assert doc.page_limit_approved is False
    assert not repo.claim_due_retries()


def test_transition_from_blocked_reports_whether_it_applied(tmp_path):
    s = _settings(tmp_path)
    repo = Repository(s.db_path)
    doc_id, _ = _blocked_doc(repo, s)

    assert repo.transition_from_blocked(doc_id, DocStatus.PENDING) is True
    assert repo.transition_from_blocked(doc_id, DocStatus.PENDING) is False


def test_failed_move_rolls_the_document_back_to_blocked(tmp_path, monkeypatch):
    """Ein Vorgang auf `failed`, dessen Original noch im Eingang liegt, ist die Falle aus
    Ruling R10: `find_by_hash_active` schließt genau `failed` aus, der Watcher legte die
    Datei beim nächsten Durchgang als zweiten Vorgang an."""
    s = _settings(tmp_path)
    repo = Repository(s.db_path)
    doc_id, src = _blocked_doc(repo, s)

    def boom(*args, **kwargs):
        raise PermissionError("Zielordner gehört root")

    monkeypatch.setattr("app.decisions.move_into", boom)

    assert discard_document(doc_id, repo, s) == DecisionResult.DISCARD_FAILED

    doc = repo.get_document(doc_id)
    assert doc.status == DocStatus.BLOCKED  # kein „failed" mit Datei im Eingang
    assert doc.finished_at is None
    assert "Verwerfen fehlgeschlagen" in doc.error_message
    assert src.exists()
    kinds = _event_kinds(repo, doc_id)
    assert EventType.DISCARDED not in kinds
    assert kinds.count(EventType.BLOCKED) == 1  # der Rollback ist im Verlauf vermerkt


def test_rollback_keeps_the_document_shielded_from_a_second_intake(tmp_path, monkeypatch):
    """Nach dem Rollback muss der Dublettenschutz weiter greifen."""
    import hashlib

    s = _settings(tmp_path)
    repo = Repository(s.db_path)
    doc_id, src = _blocked_doc(repo, s)
    digest = hashlib.sha256(src.read_bytes()).hexdigest()
    repo.update_document(doc_id, file_hash=digest)
    monkeypatch.setattr(
        "app.decisions.move_into", lambda *a, **k: (_ for _ in ()).throw(OSError("voll"))
    )

    discard_document(doc_id, repo, s)

    assert repo.find_by_hash_active(digest).id == doc_id


def test_rollback_allows_a_second_attempt(tmp_path, monkeypatch):
    s = _settings(tmp_path)
    repo = Repository(s.db_path)
    doc_id, src = _blocked_doc(repo, s)
    monkeypatch.setattr(
        "app.decisions.move_into",
        lambda *a, **k: (_ for _ in ()).throw(OSError("kurzzeitig")),
    )
    assert discard_document(doc_id, repo, s) == DecisionResult.DISCARD_FAILED

    monkeypatch.undo()
    assert discard_document(doc_id, repo, s) == DecisionResult.DISCARDED

    assert repo.get_document(doc_id).status == DocStatus.FAILED
    assert not src.exists()
    assert (s.error_dir / "stapel.pdf").exists()


def test_unknown_document_is_not_found(tmp_path):
    s = _settings(tmp_path)
    repo = Repository(s.db_path)

    assert release_document(9999, repo, s) == DecisionResult.NOT_FOUND
    assert discard_document(9999, repo, s) == DecisionResult.NOT_FOUND
