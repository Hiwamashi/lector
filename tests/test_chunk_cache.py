"""Bewahrte Teilergebnisse der Texterkennung (openspec design.md D2/D6)."""

import sqlite3

from app.models import DocStatus, EventType, OcrPage, OcrToken
from app.repository import Repository

FP = "fingerabdruck-a"
FP_ANDERS = "fingerabdruck-b"


def _repo(tmp_path):
    return Repository(tmp_path / "lector.db")


def _doc(repo, name="scan.pdf"):
    return repo.create_document(original_filename=name, source_path=f"/scan-in/{name}")


def _pages(index=0, text="Wort"):
    return [
        OcrPage(
            page_index=index,
            width=1240.0,
            height=1754.0,
            tokens=[OcrToken(text=text, x0=0.1, y0=0.1, x1=0.2, y1=0.2, confidence=0.9)],
        )
    ]


def test_table_exists_with_expected_primary_key(tmp_path):
    repo = _repo(tmp_path)

    cols = {row["name"]: row for row in repo._conn.execute("PRAGMA table_info(ocr_chunk_cache)")}
    assert {"document_id", "chunk_index", "fingerprint", "page_count", "payload", "created_at"} <= (
        set(cols)
    )
    pk = sorted((c["name"] for c in cols.values() if c["pk"]), key=lambda n: cols[n]["pk"])
    assert pk == ["document_id", "chunk_index"]


def test_store_is_an_upsert(tmp_path):
    repo = _repo(tmp_path)
    doc_id = _doc(repo)

    repo.store_chunk_result(doc_id, 0, fingerprint=FP, pages=_pages(text="alt"))
    repo.store_chunk_result(doc_id, 0, fingerprint=FP, pages=_pages(text="neu"))

    assert repo.count_chunk_results(doc_id) == 1
    loaded = repo.load_chunk_result(doc_id, 0, fingerprint=FP)
    assert loaded[0].tokens[0].text == "neu"


def test_load_returns_pages_on_matching_fingerprint(tmp_path):
    repo = _repo(tmp_path)
    doc_id = _doc(repo)
    repo.store_chunk_result(doc_id, 2, fingerprint=FP, pages=_pages(index=2))

    loaded = repo.load_chunk_result(doc_id, 2, fingerprint=FP)

    assert loaded == _pages(index=2)


def test_load_returns_nothing_on_differing_fingerprint(tmp_path):
    repo = _repo(tmp_path)
    doc_id = _doc(repo)
    repo.store_chunk_result(doc_id, 0, fingerprint=FP, pages=_pages())

    assert repo.load_chunk_result(doc_id, 0, fingerprint=FP_ANDERS) is None


def test_load_returns_nothing_for_unknown_chunk(tmp_path):
    repo = _repo(tmp_path)
    doc_id = _doc(repo)

    assert repo.load_chunk_result(doc_id, 7, fingerprint=FP) is None


def test_unreadable_payload_is_treated_as_absent(tmp_path):
    """Lieber ein erneuter Engine-Aufruf als ein falscher Textlayer."""
    repo = _repo(tmp_path)
    doc_id = _doc(repo)
    repo.store_chunk_result(doc_id, 0, fingerprint=FP, pages=_pages())
    repo._conn.execute("UPDATE ocr_chunk_cache SET payload = '{kaputt'")
    repo._conn.commit()

    assert repo.load_chunk_result(doc_id, 0, fingerprint=FP) is None


def test_clear_affects_only_the_named_document(tmp_path):
    repo = _repo(tmp_path)
    a, b = _doc(repo, "a.pdf"), _doc(repo, "b.pdf")
    repo.store_chunk_result(a, 0, fingerprint=FP, pages=_pages())
    repo.store_chunk_result(a, 1, fingerprint=FP, pages=_pages(index=1))
    repo.store_chunk_result(b, 0, fingerprint=FP, pages=_pages())

    assert repo.clear_chunk_results(a) == 2

    assert repo.count_chunk_results(a) == 0
    assert repo.count_chunk_results(b) == 1


def _force_status(repo, doc_id, status):
    """Setzt den Zustand an `set_status` vorbei — simuliert eine Endzustandssetzung, die
    die sofortige Freigabe nicht mitgenommen hat. Genau dafür ist das Netz im
    Aufbewahrungsjob da."""
    repo._conn.execute("UPDATE documents SET status = ? WHERE id = ?", (status.value, doc_id))
    repo._conn.commit()


def test_purge_removes_final_states_and_expired_entries(tmp_path):
    """Vier Vorgänge: alt/neu × Endzustand/laufend. Weg müssen der Endzustand und der alte."""
    repo = _repo(tmp_path)
    fertig_neu = _doc(repo, "fertig.pdf")
    laufend_alt = _doc(repo, "alt.pdf")
    laufend_neu = _doc(repo, "neu.pdf")
    wartet = _doc(repo, "wartet.pdf")
    for doc_id in (fertig_neu, laufend_alt, laufend_neu, wartet):
        repo.store_chunk_result(doc_id, 0, fingerprint=FP, pages=_pages())
    _force_status(repo, fertig_neu, DocStatus.DONE)
    repo.set_status(laufend_alt, DocStatus.PROCESSING)
    repo.set_status(laufend_neu, DocStatus.PROCESSING)
    # laufend_alt künstlich altern lassen
    repo._conn.execute(
        "UPDATE ocr_chunk_cache SET created_at = datetime('now', '-30 days') "
        "WHERE document_id = ?",
        (laufend_alt,),
    )
    repo._conn.commit()

    removed = repo.purge_chunk_results(7)

    assert removed == 2
    assert repo.count_chunk_results(fertig_neu) == 0
    assert repo.count_chunk_results(laufend_alt) == 0
    assert repo.count_chunk_results(laufend_neu) == 1
    assert repo.count_chunk_results(wartet) == 1


def test_purge_with_disabled_retention_still_clears_final_states(tmp_path):
    repo = _repo(tmp_path)
    fertig = _doc(repo, "fertig.pdf")
    alt = _doc(repo, "alt.pdf")
    repo.store_chunk_result(fertig, 0, fingerprint=FP, pages=_pages())
    repo.store_chunk_result(alt, 0, fingerprint=FP, pages=_pages())
    _force_status(repo, fertig, DocStatus.FAILED)
    repo.set_status(alt, DocStatus.PROCESSING)
    repo._conn.execute(
        "UPDATE ocr_chunk_cache SET created_at = datetime('now', '-99 days') "
        "WHERE document_id = ?",
        (alt,),
    )
    repo._conn.commit()

    assert repo.purge_chunk_results(0) == 1

    assert repo.count_chunk_results(fertig) == 0
    assert repo.count_chunk_results(alt) == 1  # Verfallen ist abgeschaltet


def test_entries_are_bound_to_the_document_row(tmp_path):
    """Fremdschlüssel mit CASCADE: Ein gelöschter Vorgang lässt keine Waisen zurück."""
    repo = _repo(tmp_path)
    doc_id = _doc(repo)
    repo.store_chunk_result(doc_id, 0, fingerprint=FP, pages=_pages())

    repo._conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    repo._conn.commit()

    assert repo.count_chunk_results(doc_id) == 0


def test_store_rejects_unknown_document(tmp_path):
    repo = _repo(tmp_path)

    try:
        repo.store_chunk_result(999, 0, fingerprint=FP, pages=_pages())
    except sqlite3.IntegrityError:
        return
    raise AssertionError("Fremdschlüssel hätte greifen müssen")


def test_reaching_a_final_state_releases_the_entries_immediately(tmp_path):
    """6.2: Die Freigabe greift schon beim Zustandsübergang, nicht erst im Job."""
    for status in (DocStatus.DONE, DocStatus.SKIPPED_ERECHNUNG, DocStatus.FAILED):
        repo = Repository(tmp_path / f"{status.value}.db")
        doc_id = _doc(repo)
        repo.store_chunk_result(doc_id, 0, fingerprint=FP, pages=_pages())
        repo.add_event(doc_id, EventType.DETECTED)

        repo.set_status(doc_id, status)

        assert repo.count_chunk_results(doc_id) == 0
        # Vorgang und Verlauf bleiben vollständig erhalten
        assert repo.get_document(doc_id).status == status
        assert len(repo.list_events(doc_id)) == 1


def test_scheduling_a_retry_keeps_the_entries(tmp_path):
    """6.4: Gerade dann werden sie gebraucht."""
    repo = _repo(tmp_path)
    doc_id = _doc(repo)
    repo.store_chunk_result(doc_id, 0, fingerprint=FP, pages=_pages())

    repo.increment_attempt(doc_id)
    repo.schedule_retry(doc_id, 15)

    assert repo.count_chunk_results(doc_id) == 1


def test_discarding_a_blocked_document_releases_the_entries(tmp_path):
    """6.3: `transition_from_blocked` umgeht `set_status` und braucht die Freigabe eigens."""
    repo = _repo(tmp_path)
    doc_id = _doc(repo)
    repo.store_chunk_result(doc_id, 0, fingerprint=FP, pages=_pages())
    repo.set_status(doc_id, DocStatus.BLOCKED)
    assert repo.count_chunk_results(doc_id) == 1  # Blockade ist kein Endzustand

    assert repo.transition_from_blocked(doc_id, DocStatus.FAILED, error_message="verworfen")

    assert repo.count_chunk_results(doc_id) == 0


def test_releasing_a_blocked_document_keeps_the_entries(tmp_path):
    """Die Freigabe führt zurück in die Reihe — die Teilergebnisse werden noch gebraucht."""
    repo = _repo(tmp_path)
    doc_id = _doc(repo)
    repo.store_chunk_result(doc_id, 0, fingerprint=FP, pages=_pages())
    repo.set_status(doc_id, DocStatus.BLOCKED)

    assert repo.transition_from_blocked(doc_id, DocStatus.PENDING, approve_page_limit=True)

    assert repo.count_chunk_results(doc_id) == 1


def test_retention_helper_reports_and_survives_a_broken_repo(tmp_path):
    """6.5: Der Job darf an einem Fehler des Zwischenspeichers nicht hängenbleiben."""
    from app.retention import purge_chunk_cache

    repo = _repo(tmp_path)
    doc_id = _doc(repo)
    repo.store_chunk_result(doc_id, 0, fingerprint=FP, pages=_pages())
    _force_status(repo, doc_id, DocStatus.DONE)

    assert purge_chunk_cache(repo, 7) == 1

    class Kaputt:
        def purge_chunk_results(self, days):
            raise RuntimeError("DB weg")

    assert purge_chunk_cache(Kaputt(), 7) == 0
