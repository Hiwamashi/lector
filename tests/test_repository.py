from app.models import DocStatus, DocType, EventType
from app.repository import Repository


def make_repo(tmp_path):
    return Repository(tmp_path / "lector.db")


def test_create_and_get_document(tmp_path):
    repo = make_repo(tmp_path)
    doc_id = repo.create_document(original_filename="scan.pdf", source_path="/scan-in/scan.pdf")
    doc = repo.get_document(doc_id)
    assert doc is not None
    assert doc.original_filename == "scan.pdf"
    assert doc.status == DocStatus.PENDING
    assert doc.attempt_count == 0
    assert doc.created_at is not None


def test_status_transitions_set_timestamps(tmp_path):
    repo = make_repo(tmp_path)
    doc_id = repo.create_document(original_filename="a.pdf", source_path="/scan-in/a.pdf")
    repo.set_status(doc_id, DocStatus.PROCESSING)
    assert repo.get_document(doc_id).started_at is not None
    repo.set_status(doc_id, DocStatus.DONE)
    doc = repo.get_document(doc_id)
    assert doc.status == DocStatus.DONE
    assert doc.finished_at is not None


def test_progress_and_attempts(tmp_path):
    repo = make_repo(tmp_path)
    doc_id = repo.create_document(original_filename="a.pdf", source_path="/scan-in/a.pdf")
    repo.update_document(doc_id, total_pages=20, doc_type=DocType.PDF)
    repo.set_progress(doc_id, 5)
    repo.increment_attempt(doc_id)
    doc = repo.get_document(doc_id)
    assert doc.total_pages == 20
    assert doc.doc_type == DocType.PDF
    assert doc.processed_pages == 5
    assert doc.attempt_count == 1


def test_retry_scheduling_and_claim(tmp_path):
    repo = make_repo(tmp_path)
    doc_id = repo.create_document(original_filename="a.pdf", source_path="/scan-in/a.pdf")
    # frische pending-Dokumente ohne next_retry_at werden sofort beansprucht
    assert any(d.id == doc_id for d in repo.claim_due_retries())
    # in 15 min eingeplant -> nicht mehr fällig
    repo.schedule_retry(doc_id, 15)
    assert not any(d.id == doc_id for d in repo.claim_due_retries())


def test_events_and_counts(tmp_path):
    repo = make_repo(tmp_path)
    doc_id = repo.create_document(original_filename="a.pdf", source_path="/scan-in/a.pdf")
    repo.add_event(doc_id, EventType.DETECTED, "erkannt")
    repo.add_event(doc_id, EventType.DONE, "fertig")
    events = repo.list_events(doc_id)
    assert [e["event_type"] for e in events] == ["detected", "done"]
    counts = repo.status_counts()
    assert counts.get("pending") == 1


def test_dedup_by_hash(tmp_path):
    repo = make_repo(tmp_path)
    repo.create_document(original_filename="a.pdf", source_path="/scan-in/a.pdf", file_hash="h1")
    assert repo.find_by_hash_active("h1") is not None
    assert repo.find_by_hash_active("nope") is None
