import os
import time

from app import recovery
from app.config import Settings
from app.fileops import copy_into
from app.fileops import file_hash as compute_file_hash
from app.models import DocStatus, DocType, Document, EventType
from app.recovery import (
    OriginalLocation,
    _find_in_processed,
    locate_original,
    resolve_stale_processing,
)
from app.repository import Repository


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


# ---- resolve_stale_processing: Entscheidungstabelle D1 (Aufgabe 2.1) -----------------


def _stale(repo, s, *, filename="scan.pdf", in_watch_dir=True, doc_type=None, output_path=None):
    """Legt einen Vorgang an, der auf `processing` haengt, und ruft ihn ueber das
    Repository ab -- wie beim echten Prozessabbruch, statt `Document` roh zu
    konstruieren, damit `resolve_stale_processing` (das `repo.list_processing()` nutzt)
    ihn findet.
    """
    src = s.watch_dir / filename
    if in_watch_dir:
        src.write_bytes(b"original")
    doc_id = repo.create_document(original_filename=filename, source_path=str(src))
    repo.set_status(doc_id, DocStatus.PROCESSING)  # setzt started_at
    fields = {}
    if doc_type is not None:
        fields["doc_type"] = doc_type
    if output_path is not None:
        fields["output_path"] = output_path
    if fields:
        repo.update_document(doc_id, **fields)
    return doc_id, src


def test_resolve_processed_dir_row_finishes_regardless_of_output_path(tmp_path):
    """Tabellenzeile 1: Original im Verarbeitet-Ordner -> abschliessen, `output_path`
    ist dabei "egal" -- hier bewusst gesetzt, um genau das zu belegen."""
    s = _settings(tmp_path)
    repo = Repository(s.db_path)
    content = b"original"
    processed_file = s.processed_dir / "scan.pdf"
    processed_file.write_bytes(content)
    doc_id = repo.create_document(
        original_filename="scan.pdf",
        source_path=str(s.watch_dir / "scan.pdf"),  # existiert nicht mehr
        file_hash=compute_file_hash(processed_file),
    )
    repo.set_status(doc_id, DocStatus.PROCESSING)
    repo.update_document(
        doc_id, doc_type=DocType.PDF, output_path=str(s.consume_dir / "irrelevant.pdf")
    )

    resolved = resolve_stale_processing(repo, s)

    assert resolved == 1
    doc = repo.get_document(doc_id)
    assert doc.status == DocStatus.DONE
    assert processed_file.exists()  # lag schon dort, `move_into` war nicht noetig


def test_resolve_watch_dir_with_output_path_finishes_and_moves_original(tmp_path):
    """Tabellenzeile 2: Original im Eingang, `output_path` gesetzt -> abschliessen,
    Original nachziehen (D4, OCR-Weg -> `done`)."""
    s = _settings(tmp_path)
    repo = Repository(s.db_path)
    doc_id, src = _stale(
        repo, s, doc_type=DocType.PDF, output_path=str(s.consume_dir / "scan.pdf")
    )

    resolved = resolve_stale_processing(repo, s)

    assert resolved == 1
    doc = repo.get_document(doc_id)
    assert doc.status == DocStatus.DONE
    assert not src.exists()
    assert (s.processed_dir / "scan.pdf").exists()


def test_resolve_not_found_row_fails_with_explanatory_message(tmp_path):
    """Tabellenzeile 4: Original nirgends auffindbar -> gescheitert mit Meldung."""
    s = _settings(tmp_path)
    repo = Repository(s.db_path)
    doc_id, _src = _stale(repo, s, in_watch_dir=False, doc_type=DocType.PDF)

    resolved = resolve_stale_processing(repo, s)

    assert resolved == 1
    doc = repo.get_document(doc_id)
    assert doc.status == DocStatus.FAILED
    assert doc.error_message and "auffindbar" in doc.error_message


# ---- Befund 2 (Abschluss-Review), Ruling R13: output_path vor der Ortsbestimmung -----


def test_resolve_output_path_set_finishes_even_when_original_not_found(tmp_path):
    """Befund 2: Ein vermerkter Ablageort ist der staerkere Beleg als der Ort des
    Originals -- z.B. weil der Retention-Job das Original bereits aus `processed`
    geloescht hat (zugesicherter Migrationsfall fuer Altbestand, siehe design.md). Ohne
    Ruling R13 wuerde `locate_original` hier NOT_FOUND liefern und der Vorgang
    faelschlich auf `failed` laufen, obwohl die Ablage laengst erfolgt war."""
    s = _settings(tmp_path)
    repo = Repository(s.db_path)
    doc_id, _src = _stale(
        repo,
        s,
        in_watch_dir=False,
        doc_type=DocType.PDF,
        output_path=str(s.consume_dir / "scan.pdf"),
    )

    resolved = resolve_stale_processing(repo, s)

    assert resolved == 1
    doc = repo.get_document(doc_id)
    assert doc.status == DocStatus.DONE
    assert doc.error_message is None


def test_resolve_output_path_set_finishes_erechnung_even_when_original_not_found(tmp_path):
    """Wie oben, aber fuer den E-Rechnungs-Weg -- Endzustand `skipped_erechnung`, nicht
    `done` (Ruling R13 gilt fuer beide Wege gleich)."""
    s = _settings(tmp_path)
    repo = Repository(s.db_path)
    doc_id, _src = _stale(
        repo,
        s,
        filename="rechnung.xml",
        in_watch_dir=False,
        doc_type=DocType.ERECHNUNG_XML,
        output_path=str(s.consume_dir / "rechnung.xml"),
    )

    resolved = resolve_stale_processing(repo, s)

    assert resolved == 1
    assert repo.get_document(doc_id).status == DocStatus.SKIPPED_ERECHNUNG


# ---- Grenzfall D2 (Aufgabe 2.2) -------------------------------------------------------


def test_resolve_ambiguous_with_recent_consume_file_fails(tmp_path):
    """Datei mit erwartetem Namen im Ausgabeordner, veraendert NACH `started_at` ->
    `failed` mit Pruefhinweis fuer Paperless. Ruling R10: Das Original muss dabei aus dem
    Eingang in den Fehlerordner wandern (siehe die beiden dedizierten R10-Tests unten fuer
    die Begruendung) -- bleibe es im Eingang liegen, wuerde der Watcher es beim naechsten
    Scan als neues Dokument aufnehmen."""
    s = _settings(tmp_path)
    repo = Repository(s.db_path)
    doc_id, src = _stale(repo, s, doc_type=DocType.PDF)  # kein output_path -> Grenzfall D2

    time.sleep(1.1)  # klar nach started_at (Sekundenaufloesung in SQLite)
    (s.consume_dir / "scan.pdf").write_bytes(b"moeglicherweise schon abgelegtes Ergebnis")

    resolved = resolve_stale_processing(repo, s)

    assert resolved == 1
    doc = repo.get_document(doc_id)
    assert doc.status == DocStatus.FAILED
    assert doc.error_message and "Paperless" in doc.error_message
    assert not src.exists()  # nicht mehr im Eingang -- kein erneuter Watcher-Fund moeglich
    assert (s.error_dir / "scan.pdf").exists()  # zur manuellen Pruefung erhalten


def test_resolve_ambiguous_erechnung_uses_original_name_not_pdf_and_fails_when_recent(
    tmp_path,
):
    """Fix-Runde 1, Ruling R8: Der E-Rechnungs-Weg legt per `copy_into` unter dem
    UNVERAENDERTEN Originalnamen ab (`unique_target` nutzt `src.name`, siehe
    `_handle_erechnung` in `app/pipeline.py`), nicht unter `<Stamm>.pdf`. Die Stichprobe
    im Grenzfall D2 muss deshalb nach `rechnung.xml` suchen. Suchte sie faelschlich nach
    `rechnung.pdf` (die urspruengliche, zu pauschale Regel aus Brief/Aufgabe 2.2), wuerde
    der Treffer nie gefunden und der Vorgang faelschlich neu eingereiht -- beim naechsten
    Durchlauf legt `_handle_erechnung` die Datei ein zweites Mal ab (Doppelablage)."""
    s = _settings(tmp_path)
    repo = Repository(s.db_path)
    doc_id, src = _stale(repo, s, filename="rechnung.xml", doc_type=DocType.ERECHNUNG_XML)

    time.sleep(1.1)  # klar nach started_at
    (s.consume_dir / "rechnung.xml").write_bytes(b"moeglicherweise schon abgelegte E-Rechnung")

    resolved = resolve_stale_processing(repo, s)

    assert resolved == 1
    doc = repo.get_document(doc_id)
    assert doc.status == DocStatus.FAILED
    assert doc.error_message and "Paperless" in doc.error_message
    assert not src.exists()  # Ruling R10: nicht mehr im Eingang
    assert (s.error_dir / "rechnung.xml").exists()


def test_resolve_ambiguous_erechnung_requeues_when_consume_file_is_older(tmp_path):
    """Gegentest zu obigem: eine gleichnamige Datei im Ausgabeordner VOR `started_at` ist
    harmloser Altbestand -> neu einreihen, wie beim OCR-Weg."""
    s = _settings(tmp_path)
    repo = Repository(s.db_path)
    src = s.watch_dir / "rechnung.xml"
    src.write_bytes(b"original")
    doc_id = repo.create_document(original_filename="rechnung.xml", source_path=str(src))

    (s.consume_dir / "rechnung.xml").write_bytes(b"alter, unbeteiligter Bestand")
    time.sleep(1.1)  # started_at liegt danach

    repo.set_status(doc_id, DocStatus.PROCESSING)
    repo.update_document(doc_id, doc_type=DocType.ERECHNUNG_XML)

    resolved = resolve_stale_processing(repo, s)

    assert resolved == 1
    assert repo.get_document(doc_id).status == DocStatus.PENDING


# ---- Befund 1 (Abschluss-Review), Ruling R12: st_ctime statt st_mtime ----------------


def test_resolve_ambiguous_erechnung_via_real_copy_into_is_detected_as_recent(tmp_path):
    """Befund 1: `_handle_erechnung` legt per `copy_into` ab (`shutil.copy2`, siehe
    `app/fileops.py`) -- `copy2` ueberträgt die mtime der QUELLE auf die Kopie. Die Ablage
    im Ausgabeordner traegt deshalb die (fruehere) mtime des Originals aus dem Eingang,
    nicht den tatsaechlichen Ablagezeitpunkt. Ein reiner `st_mtime`-Vergleich gegen
    `started_at` schlaegt fuer E-Rechnungen deshalb STRUKTURELL immer fehl -- die
    Schutzstichprobe griffe nie, siehe Bericht.

    Dieser Test stellt die Ablage ueber den echten `copy_into`-Weg her (wie
    `_handle_erechnung` es tut), nicht per `write_bytes` wie in
    `test_resolve_ambiguous_erechnung_uses_original_name_not_pdf_and_fails_when_recent` --
    jener Test umgeht mit `write_bytes` genau die Stelle, an der es bricht, und bleibt
    deshalb gruen, obwohl der Fehler vorliegt.

    Ruling R12: `st_ctime` spiegelt das Ablegen selbst (hier: den `copy2`-Aufruf) und liegt
    zuverlaessig nach `started_at`, unabhaengig von der mtime der Quelle -- der Vergleich
    nimmt deshalb das juengere von `st_mtime` und `st_ctime`.
    """
    s = _settings(tmp_path)
    repo = Repository(s.db_path)
    doc_id, src = _stale(repo, s, filename="rechnung.xml", doc_type=DocType.ERECHNUNG_XML)

    # Quelle traegt eine mtime deutlich VOR started_at -- simuliert eine Datei, die schon
    # eine Weile im Eingang lag (Stabilitaetsfenster), bevor sie aufgenommen wurde.
    old = time.time() - 3600
    os.utime(src, (old, old))

    time.sleep(1.1)  # Ablage (per copy_into) findet klar NACH started_at statt
    copy_into(src, s.consume_dir)  # echter Weg wie _handle_erechnung, nicht write_bytes

    resolved = resolve_stale_processing(repo, s)

    assert resolved == 1
    doc = repo.get_document(doc_id)
    assert doc.status == DocStatus.FAILED
    assert doc.error_message and "Paperless" in doc.error_message


# ---- Ruling R10 (Fix-Runde 2): Original beim Treffer im Ausgabeordner in den ----------
# ---- Fehlerordner verschieben, statt es im Eingang liegen zu lassen -------------------


def test_resolve_ambiguous_recent_hit_moves_original_to_error_dir(tmp_path):
    """Ohne das Verschieben bliebe das Original im Eingang liegen, obwohl der Vorgang auf
    `failed` steht. `find_by_hash_active` schliesst `failed` per `status != 'failed'`
    (`app/repository.py`) explizit aus -- der Watcher (`Worker._intake_file`) wuerde die
    liegen gebliebene Datei beim naechsten Scan deshalb als *neues*, aktives Dokument
    aufnehmen und vollstaendig durchverarbeiten: genau die Doppelablage, die dieser Zweig
    verhindern soll. Das Original muss deshalb im Fehlerordner ankommen (zur manuellen
    Pruefung erhalten), nicht im Eingang bleiben."""
    s = _settings(tmp_path)
    repo = Repository(s.db_path)
    doc_id, src = _stale(repo, s, doc_type=DocType.PDF)  # kein output_path -> Grenzfall D2

    time.sleep(1.1)  # klar nach started_at
    (s.consume_dir / "scan.pdf").write_bytes(b"moeglicherweise schon abgelegtes Ergebnis")

    resolved = resolve_stale_processing(repo, s)

    assert resolved == 1
    assert repo.get_document(doc_id).status == DocStatus.FAILED
    assert not src.exists()
    assert (s.error_dir / "scan.pdf").exists()


def test_resolve_ambiguous_recent_hit_leaves_nothing_for_watcher_to_reintake(tmp_path):
    """Nachweis, dass die Wiedereinschleusung tatsaechlich ausgeschlossen ist. Ein
    vollstaendiger Worker-Lauf ist dafuer nicht noetig: `Worker._scan_loop` iteriert
    einzig ueber Dateien in `settings.watch_dir` (siehe `app/worker.py`) -- ist der
    Eingang nach der Aufloesung leer, gibt es dort nichts mehr, worueber der Scan
    stolpern und `_intake_file` ausloesen koennte. Die Kette ist also bereits am
    Dateisystem geschlossen. Ergaenzend belegt `find_by_hash_active` fuer denselben Hash
    weiterhin `None`: selbst wenn eine gleich gehashte Datei anderswo aufgetaucht waere,
    wuerde der bereits `failed` stehende Vorgang nicht als aktives Duplikat durchgehen --
    das bestaetigt, dass die Dedup-Abfrage selbst unveraendert und korrekt bleibt
    (Ruling R10 aendert nur das Liegenlassen der Datei, nicht `find_by_hash_active`)."""
    s = _settings(tmp_path)
    repo = Repository(s.db_path)
    file_hash_value = "f" * 64
    doc_id, src = _stale(repo, s, doc_type=DocType.PDF)
    repo.update_document(doc_id, file_hash=file_hash_value)

    time.sleep(1.1)  # klar nach started_at
    (s.consume_dir / "scan.pdf").write_bytes(b"moeglicherweise schon abgelegtes Ergebnis")

    resolved = resolve_stale_processing(repo, s)

    assert resolved == 1
    assert not any(s.watch_dir.iterdir())  # nichts mehr da, worueber der Scan stolpern koennte
    assert repo.find_by_hash_active(file_hash_value) is None


def test_resolve_ambiguous_without_recent_consume_file_requeues(tmp_path):
    """Unterscheidet sich von obigem Test nur im Aenderungszeitpunkt der Datei: liegt sie
    VOR `started_at`, ist sie ein harmloser Altbestand -> neu einreihen (`pending`)."""
    s = _settings(tmp_path)
    repo = Repository(s.db_path)
    src = s.watch_dir / "scan.pdf"
    src.write_bytes(b"original")
    doc_id = repo.create_document(original_filename="scan.pdf", source_path=str(src))

    (s.consume_dir / "scan.pdf").write_bytes(b"alter, unbeteiligter Bestand")
    time.sleep(1.1)  # started_at liegt danach

    repo.set_status(doc_id, DocStatus.PROCESSING)
    repo.update_document(doc_id, doc_type=DocType.PDF)

    resolved = resolve_stale_processing(repo, s)

    assert resolved == 1
    assert repo.get_document(doc_id).status == DocStatus.PENDING


# ---- Befund 3 (Abschluss-Review), Ruling R14: Requeue mit Zaehler und Backoff --------


def test_resolve_ambiguous_requeue_increments_attempt_and_schedules_retry(tmp_path):
    """Befund 3: Ohne Ruling R14 setzte die erneute Einreihung nur `status=pending`, ohne
    `attempt_count` hochzusetzen oder `next_retry_at` zu setzen -- `RETRY_MAX` griff nie,
    und der Vorgang waere beim naechsten Start sofort wieder dran (kein Backoff). Dieser
    Test belegt, dass beides jetzt geschieht, solange `retry_max` noch nicht erreicht
    ist."""
    s = _settings(tmp_path)
    repo = Repository(s.db_path)
    doc_id, _src = _stale(repo, s, doc_type=DocType.PDF)  # -> Grenzfall D2, kein Konsum-Treffer

    resolved = resolve_stale_processing(repo, s)

    assert resolved == 1
    doc = repo.get_document(doc_id)
    assert doc.status == DocStatus.PENDING
    assert doc.attempt_count == 1
    assert doc.next_retry_at is not None


def test_resolve_ambiguous_requeue_fails_permanently_at_retry_max(tmp_path):
    """Gegentest: Ist `retry_max` mit diesem Versuch erreicht, endet der Vorgang
    endgueltig auf `failed` -- wie bei `_handle_failure` (`app/pipeline.py`) -- und das
    Original wandert in den Fehlerordner, statt im Eingang liegen zu bleiben (sonst
    naehme der Watcher es beim naechsten Scan wieder als neues Dokument auf)."""
    s = _settings(tmp_path, RETRY_MAX=2)
    repo = Repository(s.db_path)
    doc_id, src = _stale(repo, s, doc_type=DocType.PDF)
    repo.update_document(doc_id, attempt_count=1)  # ein Versuch bereits verbraucht

    resolved = resolve_stale_processing(repo, s)

    assert resolved == 1
    doc = repo.get_document(doc_id)
    assert doc.status == DocStatus.FAILED
    assert doc.attempt_count == 2
    assert doc.error_message and "Versuche" in doc.error_message
    assert not src.exists()
    assert (s.error_dir / "scan.pdf").exists()


def test_resolve_ambiguous_without_doc_type_requeues_without_consume_probe(tmp_path):
    """Ruling R3: Ohne erkannten `doc_type` starb der Vorgang vor der Erkennung -- die
    Stichprobe im Ausgabeordner entfaellt, selbst wenn dort zufaellig eine juengere,
    namentlich passende Datei liegt."""
    s = _settings(tmp_path)
    repo = Repository(s.db_path)
    doc_id, _src = _stale(repo, s)  # doc_type bleibt None

    time.sleep(1.1)
    (s.consume_dir / "scan.pdf").write_bytes(b"waere ohne R3 als 'kuerzlich' gewertet worden")

    resolved = resolve_stale_processing(repo, s)

    assert resolved == 1
    assert repo.get_document(doc_id).status == DocStatus.PENDING


def test_resolve_ambiguous_time_comparison_is_utc_not_local(tmp_path):
    """Ruling R2, Regressionsschutz: Der Vergleich muss `started_at` explizit als UTC in
    Epoch umrechnen. Die Ausgabedatei entsteht hier klar VOR dem echten (UTC-)
    Prozessbeginn -- korrekt aufgeloest also `pending`. Eine Zeitzone oestlich von UTC
    (Europe/Berlin, im September UTC+2) faellt bei einer naiven Lokalzeit-Interpretation
    von `started_at` (z.B. via `time.mktime`) rechnerisch um zwei Stunden VOR die Datei
    zurueck; der Vergleich wuerde dann faelschlich `> started_at` ergeben und diesen Test
    mit `failed` statt `pending` zum Scheitern bringen.

    Ruling R12 aendert den Aufbau dieses Tests: Anders als `st_mtime` laesst sich
    `st_ctime` nicht per `os.utime` zurueckdatieren -- jede Metadatenaenderung an einer
    Datei (auch `os.utime` selbst) hebt `ctime` auf "jetzt" an. Die Ausgabedatei muss
    deshalb tatsaechlich VOR dem Start des Vorgangs angelegt werden, nicht nachher mit
    zurueckdatierter mtime -- wie bei den anderen "Altbestand"-Tests oben (z.B.
    `test_resolve_ambiguous_without_recent_consume_file_requeues`). Die Zwei-Stunden-
    Groessenordnung des Zeitzonenfehlers bleibt dabei bequem messbar, auch wenn der reale
    Abstand hier nur eine gute Sekunde betraegt.
    """
    original_tz = os.environ.get("TZ")
    os.environ["TZ"] = "Europe/Berlin"
    time.tzset()
    try:
        s = _settings(tmp_path)
        repo = Repository(s.db_path)
        src = s.watch_dir / "scan.pdf"
        src.write_bytes(b"original")

        consume_file = s.consume_dir / "scan.pdf"
        consume_file.write_bytes(b"vor Prozessbeginn abgelegter, unbeteiligter Bestand")
        time.sleep(1.1)  # started_at liegt danach -- echte UTC-Zeit, keine Lokalzeit

        doc_id = repo.create_document(original_filename="scan.pdf", source_path=str(src))
        repo.set_status(doc_id, DocStatus.PROCESSING)
        repo.update_document(doc_id, doc_type=DocType.PDF)

        resolved = resolve_stale_processing(repo, s)

        assert resolved == 1
        assert repo.get_document(doc_id).status == DocStatus.PENDING
    finally:
        if original_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = original_tz
        time.tzset()


# ---- Abschluss D4 (Aufgabe 2.3) -------------------------------------------------------


def test_resolve_finishes_erechnung_to_skipped_status(tmp_path):
    """E-Rechnungs-Weg: eigener Endzustand `skipped_erechnung`, nicht `done`."""
    s = _settings(tmp_path)
    repo = Repository(s.db_path)
    doc_id, src = _stale(
        repo,
        s,
        filename="rechnung.xml",
        doc_type=DocType.ERECHNUNG_XML,
        output_path=str(s.consume_dir / "rechnung.xml"),
    )

    resolved = resolve_stale_processing(repo, s)

    assert resolved == 1
    doc = repo.get_document(doc_id)
    assert doc.status == DocStatus.SKIPPED_ERECHNUNG
    assert not src.exists()
    assert (s.processed_dir / "rechnung.xml").exists()


# ---- Verlaufseintrag (Aufgabe 2.4) ----------------------------------------------------


def test_resolve_writes_event_naming_interruption_and_resolution(tmp_path):
    s = _settings(tmp_path)
    repo = Repository(s.db_path)
    doc_id, _src = _stale(repo, s, doc_type=DocType.PDF)  # -> Grenzfall D2, ohne Konsum-Datei

    resolve_stale_processing(repo, s)

    events = repo.list_events(doc_id)
    assert events
    last = events[-1]
    assert last["event_type"] == EventType.RETRY_SCHEDULED.value
    assert "Neustart" in last["message"]
    assert "eingereiht" in last["message"]


# ---- Fehlerkapselung (Aufgabe 2.5) ----------------------------------------------------


def test_resolve_isolates_failure_of_a_single_document(tmp_path, monkeypatch):
    """Drei Vorgaenge, der mittlere loest beim Auflösen eine Ausnahme aus -- die beiden
    anderen werden dennoch aufgeloest, und der Rueckgabewert zaehlt nur diese beiden.

    Fault-Injection sitzt an `_finish`, nicht mehr an `locate_original`: Seit Ruling R13
    (Befund 2, Abschluss-Review) wird bei gesetztem `output_path` -- wie bei allen drei
    Vorgaengen hier -- direkt `_finish` aufgerufen; `locate_original` kommt in diesem Fall
    gar nicht mehr zum Zug und waere als Injektionspunkt wirkungslos."""
    s = _settings(tmp_path)
    repo = Repository(s.db_path)

    doc_ids = []
    for i in range(3):
        doc_id, _src = _stale(
            repo,
            s,
            filename=f"scan{i}.pdf",
            doc_type=DocType.PDF,
            output_path=str(s.consume_dir / f"scan{i}.pdf"),
        )
        doc_ids.append(doc_id)

    broken_id = doc_ids[1]
    real_finish = recovery._finish

    def flaky_finish(document, repo_, settings_):
        if document.id == broken_id:
            raise RuntimeError("kaputt")
        return real_finish(document, repo_, settings_)

    monkeypatch.setattr(recovery, "_finish", flaky_finish)

    resolved = resolve_stale_processing(repo, s)

    assert resolved == 2
    assert repo.get_document(doc_ids[0]).status == DocStatus.DONE
    assert repo.get_document(broken_id).status == DocStatus.PROCESSING  # unangetastet
    assert repo.get_document(doc_ids[2]).status == DocStatus.DONE
