import threading

from app.models import DocStatus, DocType, EventType
from app.repository import DatabaseHealthState, Repository


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


def test_check_health_regulaer_ist_benutzbar(tmp_path):
    """4.6 (regulär): Ohne Konkurrenz um den Lock liefert die Testabfrage sofort 'usable'."""
    repo = make_repo(tmp_path)

    health = repo.check_health()

    assert health.state == DatabaseHealthState.USABLE
    assert health.error is None


def test_check_health_meldet_beschaeftigt_wenn_lock_von_anderem_thread_gehalten(tmp_path):
    """4.6 (beschäftigt): Hält ein anderer Thread den Lock, darf `check_health` nicht
    warten — die kurze Frist läuft ab, die Datenbank gilt als benutzt, nicht als kaputt."""
    repo = make_repo(tmp_path)
    lock_held = threading.Event()
    release_lock = threading.Event()

    def hold_lock():
        with repo._lock:
            lock_held.set()
            release_lock.wait(timeout=5)

    holder = threading.Thread(target=hold_lock)
    holder.start()
    try:
        assert lock_held.wait(timeout=5)

        health = repo.check_health(timeout=0.05)

        assert health.state == DatabaseHealthState.BUSY
        assert health.error is None
    finally:
        release_lock.set()
        holder.join(timeout=5)


def test_check_health_meldet_nicht_benutzbar_bei_geschlossener_verbindung(tmp_path):
    """4.6 (geschlossene Verbindung): Der Lock ist frei, aber die Testabfrage schlägt
    fehl — das ist der Fall 'nicht benutzbar', nicht 'beschäftigt'."""
    repo = make_repo(tmp_path)
    repo.close()

    health = repo.check_health()

    assert health.state == DatabaseHealthState.UNUSABLE
    assert health.error is not None
    # Minor 5 (Fix-Runde 1): genau auf diesem Pfad (Lock erhalten, Abfrage schlägt fehl)
    # könnte ein entferntes `finally` den Lock verwaist zurücklassen — ohne diese
    # Zusicherung bliebe der Test grün, während im Betrieb nach einem einzigen
    # fehlgeschlagenen Health-Check jeder weitere Datenbankzugriff dauerhaft blockiert.
    assert repo._lock.acquire(timeout=1)
    repo._lock.release()


def test_database_health_state_healthy_unterscheidet_gesund_von_ungesund():
    """Minor 3: 'beschäftigt' gilt als gesund — sonst würde ein naheliegendes
    `db.state == USABLE` an der Verbrauchsstelle (Gruppe 5) jeden Container unter
    Last als ungesund einstufen, genau dann, wenn man den Zustand liest."""
    assert DatabaseHealthState.USABLE.healthy is True
    assert DatabaseHealthState.BUSY.healthy is True
    assert DatabaseHealthState.UNUSABLE.healthy is False


def _db_alt_ohne_verknuepfung(tmp_path):
    import sqlite3

    db_path = tmp_path / "alt.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE documents ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " original_filename TEXT NOT NULL, source_path TEXT NOT NULL, file_hash TEXT,"
        " status TEXT NOT NULL, doc_type TEXT, ocr_engine TEXT, total_pages INTEGER,"
        " processed_pages INTEGER NOT NULL DEFAULT 0, attempt_count INTEGER NOT NULL DEFAULT 0,"
        " next_retry_at TEXT, error_message TEXT, output_path TEXT,"
        " page_limit_approved INTEGER NOT NULL DEFAULT 0,"
        " created_at TEXT NOT NULL DEFAULT (datetime('now')), started_at TEXT, finished_at TEXT)"
    )
    conn.execute(
        "INSERT INTO documents (original_filename, source_path, status) VALUES (?, ?, ?)",
        ("alt.pdf", "/scan-in/alt.pdf", DocStatus.DONE.value),
    )
    conn.commit()
    conn.close()
    return db_path


def test_migration_adds_paperless_link_columns_and_index(tmp_path):
    repo = Repository(_db_alt_ohne_verknuepfung(tmp_path))

    cols = {row["name"] for row in repo._conn.execute("PRAGMA table_info(documents)")}
    assert {
        "output_hash",
        "original_path",
        "consumed_at",
        "paperless_id",
        "paperless_link",
        "paperless_checked_at",
    } <= cols
    indexes = {row["name"] for row in repo._conn.execute("PRAGMA index_list(documents)")}
    assert "idx_documents_paperless_link" in indexes
    doc = repo.get_document(1)
    assert doc.original_filename == "alt.pdf"
    assert doc.paperless_link is None
    assert doc.output_hash is None
    # zweites Öffnen ist idempotent
    Repository(tmp_path / "alt.db")


def _fertig(repo, name, *, status=DocStatus.DONE, link=None, doc_type=None):
    doc_id = repo.create_document(original_filename=name, source_path=f"/scan-in/{name}")
    repo.update_document(doc_id, status=status, doc_type=doc_type)
    if link is not None:
        repo.set_paperless_link(doc_id, link)
    return doc_id


def test_mark_consumed_and_set_paperless_link(tmp_path):
    from app.models import PaperlessLink

    repo = make_repo(tmp_path)
    doc_id = _fertig(repo, "a.pdf")

    repo.mark_consumed(
        doc_id, output_path="/consume/a.pdf", output_hash="ab" * 32, link_pending=True
    )
    doc = repo.get_document(doc_id)
    assert doc.output_hash == "ab" * 32
    assert doc.consumed_at is not None
    assert doc.paperless_link == PaperlessLink.PENDING

    repo.set_paperless_link(doc_id, PaperlessLink.LINKED, paperless_id=42)
    doc = repo.get_document(doc_id)
    assert (doc.paperless_link, doc.paperless_id) == (PaperlessLink.LINKED, 42)
    assert doc.paperless_checked_at is not None

    # missing behält die bisherige ID
    repo.set_paperless_link(doc_id, PaperlessLink.MISSING)
    doc = repo.get_document(doc_id)
    assert (doc.paperless_link, doc.paperless_id) == (PaperlessLink.MISSING, 42)


def test_list_paperless_pending_only_pending_done_documents(tmp_path):
    from app.models import PaperlessLink

    repo = make_repo(tmp_path)
    offen = _fertig(repo, "a.pdf", link=PaperlessLink.PENDING)
    _fertig(repo, "b.pdf", link=PaperlessLink.LINKED)
    _fertig(repo, "c.pdf", status=DocStatus.FAILED, link=PaperlessLink.PENDING)
    _fertig(repo, "d.pdf")  # NULL

    assert [d.id for d in repo.list_paperless_pending()] == [offen]


def test_list_paperless_catchup_selects_null_and_stale_not_found(tmp_path):
    from datetime import UTC, datetime, timedelta

    from app.models import PaperlessLink

    repo = make_repo(tmp_path)
    null_done = _fertig(repo, "a.pdf")
    null_skipped = _fertig(repo, "b.xml", status=DocStatus.SKIPPED_ERECHNUNG)
    _fertig(repo, "c.pdf", status=DocStatus.FAILED)  # nie
    _fertig(repo, "d.pdf", status=DocStatus.PENDING)  # nie
    _fertig(repo, "e.pdf", link=PaperlessLink.LINKED)
    alt_nf = _fertig(repo, "f.pdf", link=PaperlessLink.NOT_FOUND)
    repo._conn.execute(
        "UPDATE documents SET paperless_checked_at = '2000-01-01 00:00:00' WHERE id = ?", (alt_nf,)
    )
    repo._conn.commit()
    frisch_nf = _fertig(repo, "g.pdf", link=PaperlessLink.NOT_FOUND)  # gerade geprüft

    seit = datetime.now(UTC) - timedelta(minutes=1)
    ids = [d.id for d in repo.list_paperless_catchup(recheck_before=seit)]

    assert ids == [null_done, null_skipped, alt_nf]
    assert frisch_nf not in ids


def test_list_documents_filter_paperless_missing(tmp_path):
    from app.models import PaperlessLink

    repo = make_repo(tmp_path)
    wartet = _fertig(repo, "a.pdf", link=PaperlessLink.PENDING)
    nf = _fertig(repo, "b.pdf", link=PaperlessLink.NOT_FOUND)
    weg = _fertig(repo, "c.xml", status=DocStatus.SKIPPED_ERECHNUNG, link=PaperlessLink.MISSING)
    _fertig(repo, "d.pdf", link=PaperlessLink.LINKED)
    _fertig(repo, "e.pdf", link=PaperlessLink.LINKED_BY_NAME)
    _fertig(repo, "f.pdf", status=DocStatus.FAILED, link=PaperlessLink.NOT_FOUND)
    _fertig(repo, "g.pdf")

    ids = {d.id for d in repo.list_documents(paperless_missing=True)}

    assert ids == {wartet, nf, weg}
