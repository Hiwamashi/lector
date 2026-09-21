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
    # SQLite liefert den Zeitstempel als Text. Ungeparst ist er weder formatierbar
    # noch in Ortszeit lesbar — genau daran ist die Detailansicht mit 500 gescheitert.
    from datetime import datetime

    assert all(isinstance(e["timestamp"], datetime) for e in events)
    assert all(e["timestamp"].tzinfo is not None for e in events)
    counts = repo.status_counts()
    assert counts.get("pending") == 1


def test_dedup_by_hash(tmp_path):
    repo = make_repo(tmp_path)
    repo.create_document(original_filename="a.pdf", source_path="/scan-in/a.pdf", file_hash="h1")
    assert repo.find_by_hash_active("h1") is not None
    assert repo.find_by_hash_active("nope") is None


def test_list_processing_returns_only_processing(tmp_path):
    repo = make_repo(tmp_path)
    pending_id = repo.create_document(original_filename="a.pdf", source_path="/scan-in/a.pdf")
    processing_id = repo.create_document(original_filename="b.pdf", source_path="/scan-in/b.pdf")
    done_id = repo.create_document(original_filename="c.pdf", source_path="/scan-in/c.pdf")
    repo.set_status(processing_id, DocStatus.PROCESSING)
    repo.set_status(done_id, DocStatus.DONE)
    result = repo.list_processing()
    assert [d.id for d in result] == [processing_id]
    assert pending_id not in [d.id for d in result]
    assert done_id not in [d.id for d in result]


def test_blocked_is_not_an_end_state(tmp_path):
    """`blocked` ist ein Wartezustand — kein Abschlusszeitpunkt, kein Ende."""
    repo = make_repo(tmp_path)
    doc_id = repo.create_document(original_filename="a.pdf", source_path="/scan-in/a.pdf")
    repo.set_status(doc_id, DocStatus.PROCESSING)

    repo.set_status(doc_id, DocStatus.BLOCKED)

    doc = repo.get_document(doc_id)
    assert doc.status == DocStatus.BLOCKED
    assert doc.finished_at is None


def test_new_event_types_are_recorded(tmp_path):
    repo = make_repo(tmp_path)
    doc_id = repo.create_document(original_filename="a.pdf", source_path="/scan-in/a.pdf")

    for event_type in (EventType.BLOCKED, EventType.RELEASED, EventType.DISCARDED):
        repo.add_event(doc_id, event_type, f"Meldung {event_type}")

    kinds = [e["event_type"] for e in repo.list_events(doc_id)]
    assert EventType.BLOCKED in kinds
    assert EventType.RELEASED in kinds
    assert EventType.DISCARDED in kinds


def test_page_limit_approved_defaults_to_false(tmp_path):
    repo = make_repo(tmp_path)
    doc_id = repo.create_document(original_filename="a.pdf", source_path="/scan-in/a.pdf")

    assert repo.get_document(doc_id).page_limit_approved is False


def test_migration_adds_page_limit_column_to_existing_db(tmp_path):
    """Bestandsdatenbanken haben die Spalte nicht — sie muss beim Öffnen nachgezogen
    werden, ohne bestehende Zeilen zu verlieren."""
    import sqlite3

    db_path = tmp_path / "alt.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE documents ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " original_filename TEXT NOT NULL,"
        " source_path TEXT NOT NULL,"
        " file_hash TEXT,"
        " status TEXT NOT NULL,"
        " doc_type TEXT,"
        " ocr_engine TEXT,"
        " total_pages INTEGER,"
        " processed_pages INTEGER NOT NULL DEFAULT 0,"
        " attempt_count INTEGER NOT NULL DEFAULT 0,"
        " next_retry_at TEXT,"
        " error_message TEXT,"
        " output_path TEXT,"
        " created_at TEXT NOT NULL DEFAULT (datetime('now')),"
        " started_at TEXT,"
        " finished_at TEXT)"
    )
    conn.execute(
        "INSERT INTO documents (original_filename, source_path, status) VALUES (?, ?, ?)",
        ("alt.pdf", "/scan-in/alt.pdf", DocStatus.DONE.value),
    )
    conn.commit()
    conn.close()

    repo = Repository(db_path)

    cols = {row["name"] for row in repo._conn.execute("PRAGMA table_info(documents)")}
    assert "page_limit_approved" in cols
    doc = repo.get_document(1)
    assert doc.original_filename == "alt.pdf"
    assert doc.page_limit_approved is False
