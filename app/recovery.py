"""Recovery: löst Vorgänge auf, die durch einen Prozessabbruch mitten in der Verarbeitung
(`status=processing`) hängen geblieben sind (Entscheidungstabelle D1, Grenzfall D2,
Abschluss D4 — siehe `openspec/changes/recovery-unterbrochener-verarbeitung/design.md`).

Die Verarbeitung ist streng seriell in genau einem Prozess: Ein Vorgang auf `processing`
gehört beim Neustart garantiert zu keinem lebenden Bearbeiter mehr. Es braucht deshalb
keine Lease- oder Heartbeat-Mechanik, um das festzustellen.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC
from enum import StrEnum
from pathlib import Path

from .config import Settings
from .fileops import file_hash as compute_file_hash
from .fileops import move_into
from .models import DocStatus, DocType, Document, EventType
from .repository import Repository

log = logging.getLogger("lector.recovery")


class OriginalLocation(StrEnum):
    """Wo das Original eines Vorgangs aktuell zu finden ist."""

    WATCH_DIR = "watch_dir"
    PROCESSED_DIR = "processed_dir"
    NOT_FOUND = "not_found"


def locate_original(document: Document, settings: Settings) -> OriginalLocation:
    """Bestimmt, wo das Original eines Vorgangs liegt: Eingang, verarbeitet oder nirgends.

    Betrifft ausdrücklich nur den Eingangsordner (`settings.watch_dir`) und den Ordner
    der verarbeiteten Dateien (`settings.processed_dir`) — der Ausgabeordner
    (`settings.consume_dir`) taugt nicht als Zeuge, weil Paperless ihn überwacht und
    jede eingelesene Datei daraus entfernt.

    Ein Namenstreffer im Verarbeitet-Ordner gilt erst als das gesuchte Original, wenn
    `document.file_hash` ihn bestätigt (siehe `_find_in_processed`) — sonst könnte ein
    fremdes, unbeteiligtes Dokument mit zufällig passendem Namen fälschlich als
    Fundort gelten.
    """
    if Path(document.source_path).exists():
        return OriginalLocation.WATCH_DIR
    match = _find_in_processed(
        settings.processed_dir, document.original_filename, document.file_hash
    )
    if match is not None:
        return OriginalLocation.PROCESSED_DIR
    return OriginalLocation.NOT_FOUND


def _find_in_processed(
    processed_dir: Path, original_filename: str, file_hash: str | None
) -> Path | None:
    """Sucht das Original im Ordner der verarbeiteten Dateien, auch unter Namenszusatz.

    `unique_target` (siehe `app/fileops.py`) hängt bei einer Namenskollision `_1`, `_2`,
    … vor die Dateiendung an — der Namensabgleich berücksichtigt deshalb sowohl den
    exakten Namen als auch diesen Zusatz.

    Der Name allein ist kein Beleg: Ein fremdes Dokument kann rein zufällig genauso
    heißen (mit oder ohne Zusatz), ohne mit dem gesuchten Original identisch zu sein.
    Ein Namenskandidat gilt deshalb erst als bestätigt, wenn sein Inhalt per
    `file_hash()` mit `file_hash` übereinstimmt — dem beim Eingang berechneten Hash
    des Originals (`document.file_hash`, siehe `Worker._intake_file`). Ist `file_hash`
    unbekannt (`None`), ist keine Bestätigung möglich; die Funktion liefert dann
    konsequent `None`, statt einen unbestätigten Namenstreffer zurückzugeben.

    Gehasht werden nur die per Name gefundenen Kandidaten (üblicherweise null bis
    zwei), nicht der gesamte Ordnerinhalt.
    """
    if file_hash is None:
        return None
    if not processed_dir.exists():
        return None
    stem = Path(original_filename).stem
    suffix = Path(original_filename).suffix
    pattern = re.compile(rf"^{re.escape(stem)}(_\d+)?{re.escape(suffix)}$")
    for entry in processed_dir.iterdir():
        if entry.is_file() and pattern.match(entry.name) and compute_file_hash(entry) == file_hash:
            return entry
    return None


def resolve_stale_processing(repo: Repository, settings: Settings) -> int:
    """Löst alle Vorgänge auf, die auf `status=processing` hängen geblieben sind.

    Wendet je Vorgang die Entscheidungstabelle D1 an (siehe `design.md`): Ort des
    Originals und ob ein Ablageort (`document.output_path`) vermerkt ist, entscheiden über
    Abschluss, erneute Einreihung oder endgültiges Scheitern — nie der Ausgabeordner allein.

    Bewusst nicht an die Startsequenz gebunden; wer sie aufruft (z.B. `app/main.py` in der
    `lifespan`), entscheidet über den Zeitpunkt. Ein Fehler bei einem einzelnen Vorgang wird
    mit Traceback protokolliert und bricht die Auflösung der übrigen nicht ab — dieselbe
    Haltung wie bei `Repository.reset_stale_exports`.

    Liefert die Anzahl der aufgelösten Vorgänge, einschließlich der als `failed`
    markierten.
    """
    resolved = 0
    for doc in repo.list_processing():
        try:
            _resolve_one(doc, repo, settings)
        except Exception:
            log.exception("Auflösung fehlgeschlagen für Dokument %s", doc.id)
        else:
            resolved += 1
    return resolved


def _resolve_one(doc: Document, repo: Repository, settings: Settings) -> None:
    """Wendet die Entscheidungstabelle D1 auf einen einzelnen Vorgang an.

    Ruling R13 (Befund 2, Abschluss-Review): `doc.output_path` wird **vor** der
    Ortsbestimmung geprüft, nicht danach. Ein vermerkter Ablageort belegt bereits, dass
    das Ergebnis in `consume` lag — unabhängig davon, wo (oder ob überhaupt noch) das
    Original zu finden ist. `_finish` verschiebt das Original ohnehin nur, wenn es noch
    existiert; fehlt es (etwa weil der Retention-Job es längst aus `processed` gelöscht
    hat — der im Design zugesicherte Migrationsfall für Altbestand), bleibt das
    folgenlos. Erst wenn kein Ablageort vermerkt ist, entscheidet `locate_original` nach
    der bisherigen Fallunterscheidung.
    """
    if doc.output_path:
        _finish(doc, repo, settings)
        return
    location = locate_original(doc, settings)
    if location == OriginalLocation.PROCESSED_DIR:
        _finish(doc, repo, settings)
        return
    if location == OriginalLocation.NOT_FOUND:
        message = (
            "Verarbeitung wurde durch einen Neustart unterbrochen; das Original ist "
            f"weder im Eingang noch im Verarbeitet-Ordner auffindbar (zuletzt bekannt "
            f"unter {doc.source_path})."
        )
        repo.set_status(doc.id, DocStatus.FAILED, error_message=message)
        repo.add_event(doc.id, EventType.FAILED, message)
        return
    # OriginalLocation.WATCH_DIR, kein output_path -> Grenzfall D2
    _resolve_ambiguous(doc, repo, settings)


def _resolve_ambiguous(doc: Document, repo: Repository, settings: Settings) -> None:
    """Grenzfall D2: Original im Eingang, kein Ablageort vermerkt.

    Unklar, ob der Vorgang vor der Ablage starb (dann ist ein Neuversuch richtig) oder
    exakt zwischen dem Verschieben der Ergebnisdatei und dem Vermerk (dann wäre ein
    Neuversuch eine Doppelablage). Die Stichprobe im Ausgabeordner (`_find_recent_in_consume`)
    ist nur in diesem Zweig zulässig, siehe `design.md` D2.

    Ruling R3: Ist `doc.doc_type` `None`, starb der Vorgang vor der Erkennung — dann kann
    nichts abgelegt worden sein, die Stichprobe entfällt und es wird direkt neu eingereiht.

    Ruling R10: Fällt die Stichprobe positiv aus (Treffer im Ausgabeordner), wird das
    Original zusätzlich in den Fehlerordner verschoben, bevor der Vorgang auf `failed`
    gesetzt wird — sonst bliebe es im Eingang liegen und der Watcher würde daraus beim
    nächsten Scan ein zweites, neues Dokument machen (siehe `_find_recent_in_consume`
    für die Kette).

    Ruling R14 (Befund 3, Abschluss-Review): Die erneute Einreihung (kein Treffer in der
    Stichprobe) folgt derselben Politik wie `_handle_failure` (`app/pipeline.py`) —
    `increment_attempt`, dann bei `attempt < settings.retry_max` erneutes Einreihen mit
    Backoff (`schedule_retry`), sonst endgültiges Scheitern samt Original im
    Fehlerordner. Ohne das griffe `RETRY_MAX` nie und ein Dokument, das den Prozess
    reproduzierbar zum Absturz bringt (z.B. ein sehr großer Scan, der den Speicher
    sprengt — dabei fliegt keine Exception, `_handle_failure` läuft nie), ergäbe eine
    Endlosschleife aus Neustart und erneut bezahlter Texterkennung.
    """
    candidate = _find_recent_in_consume(doc, settings) if doc.doc_type is not None else None
    if candidate is not None:
        message = (
            "Verarbeitung wurde durch einen Neustart unterbrochen, nachdem das Ergebnis "
            f"möglicherweise bereits als {candidate.name} in den Ausgabeordner abgelegt "
            "wurde — vor einer erneuten Ablage in Paperless prüfen, ob das Dokument dort "
            "schon existiert."
        )
        # Ruling R10: Original aus dem Eingang entfernen, bevor der Vorgang auf `failed`
        # gesetzt wird. Bliebe es im Eingang liegen, würde `find_by_hash_active`
        # (schließt `failed` per `status != 'failed'` aus, siehe app/repository.py)
        # diesen Vorgang beim nächsten Watcher-Scan nicht mehr als aktiv erkennen — der
        # Watcher legte dann ein zweites, neues Dokument an und verarbeitete es
        # vollständig durch: genau die Doppelablage, die dieser Zweig verhindern soll.
        # Muster wie im endgültigen Fehlerfall (`_handle_failure`, `app/pipeline.py`).
        source = Path(doc.source_path)
        if source.exists():
            move_into(source, settings.error_dir)
        repo.set_status(doc.id, DocStatus.FAILED, error_message=message)
        repo.add_event(doc.id, EventType.FAILED, message)
        return
    # Ruling R14: Struktur wie `_handle_failure` (`app/pipeline.py`) — Zähler hochsetzen,
    # dann je nach `retry_max` erneut einreihen (mit Backoff) oder endgültig scheitern.
    repo.increment_attempt(doc.id)
    refreshed = repo.get_document(doc.id)
    attempt = refreshed.attempt_count if refreshed else doc.attempt_count + 1
    if attempt < settings.retry_max:
        retry_at = repo.schedule_retry(doc.id, settings.retry_delay_minutes)
        repo.add_event(
            doc.id,
            EventType.RETRY_SCHEDULED,
            "Verarbeitung wurde durch einen Neustart unterbrochen, bevor eine Ablage "
            f"erkennbar war — Vorgang wird erneut eingereiht (Versuch "
            f"{attempt}/{settings.retry_max}, erneut um {retry_at:%Y-%m-%d %H:%M} UTC).",
        )
        return
    message = (
        "Verarbeitung wurde wiederholt durch einen Neustart unterbrochen, bevor eine "
        f"Ablage erkennbar war, und hat damit die maximale Anzahl Versuche "
        f"({settings.retry_max}) erreicht — vermutlich bringt dieses Dokument den "
        "Prozess reproduzierbar zum Absturz."
    )
    source = Path(doc.source_path)
    if source.exists():
        move_into(source, settings.error_dir)
    repo.set_status(doc.id, DocStatus.FAILED, error_message=message)
    repo.add_event(doc.id, EventType.FAILED, message)


def _find_recent_in_consume(doc: Document, settings: Settings) -> Path | None:
    """Stichprobe im Ausgabeordner — ausschließlich im Grenzfall D2 zulässig.

    Es geht hier nicht darum, ob überhaupt abgelegt wurde (das kann der Ausgabeordner nicht
    beweisen, siehe `locate_original`), sondern ob eine namentlich passende Datei **nach**
    dem Beginn dieses Vorgangs verändert wurde und damit auf eine mögliche, aber unsichere
    Ablage genau in diesem Absturzfenster hindeutet.

    Ruling R8 (ersetzt die ursprüngliche, zu pauschale Namensregel): Der erwartete Name
    hängt vom Dokumenttyp ab, weil die beiden Wege unterschiedlich ablegen. Der
    E-Rechnungs-Weg (`_handle_erechnung`, `app/pipeline.py`) legt per
    `copy_into(source, consume_dir, ...)` ab — `unique_target` verwendet dort `src.name`,
    also den **unveränderten** Originalnamen samt Endung (z.B. `.xml`). Nur der OCR-Weg
    (`_handle_ocr`) erzeugt tatsächlich `<Stamm>.pdf` (`_output_pdf_name`,
    `app/pipeline.py`). Beide Fälle berücksichtigen weiterhin den `_1`, `_2`, …-Zusatz aus
    `unique_target` (`app/fileops.py`) bei Namenskollision.

    Ruling R2: `document.started_at` kommt aus SQLite als UTC (`Repository.set_status`,
    `datetime('now')`, siehe `app/repository.py`). `Path.stat().st_mtime` ist ein
    Epoch-Wert. Um beide vergleichbar zu machen, wird `started_at` hier **explizit** als
    UTC in Epoch umgerechnet — nie über eine implizite (System-)Zeitzone.

    Ruling R12 (Befund 1, Abschluss-Review): Verglichen wird das **spätere** von
    `st_mtime` und `st_ctime`, nicht `st_mtime` allein. Der E-Rechnungs-Weg
    (`_handle_erechnung`, `app/pipeline.py`) legt per `copy_into` ab, das intern
    `shutil.copy2` nutzt — und `copy2` überträgt die mtime der **Quelle** auf die Kopie.
    Die Ablage im Ausgabeordner trägt für E-Rechnungen also die (typischerweise frühere)
    mtime des Originals aus dem Eingang, nicht den tatsächlichen Ablagezeitpunkt; ein
    reiner `st_mtime`-Vergleich gegen `started_at` schlüge deshalb strukturell **immer**
    fehl. `st_ctime` spiegelt dagegen das Ablegen selbst wider (Erzeugen, Verschieben,
    und das `chown` aus `set_ownership`) und liegt zuverlässig nach `started_at` — auf
    beiden Wegen (OCR wie E-Rechnung). `copy_into`/`_handle_erechnung` selbst bleiben
    unverändert: Das unveränderte Durchreichen der E-Rechnung ist eine zugesicherte
    Eigenschaft.
    """
    if doc.started_at is None or not settings.consume_dir.exists():
        return None
    started_epoch = doc.started_at.replace(tzinfo=UTC).timestamp()
    if doc.doc_type in (DocType.ERECHNUNG_XML, DocType.ERECHNUNG_PDF):
        expected_name = doc.original_filename  # unverändert durchgereicht, siehe Ruling R8
    else:
        expected_name = f"{Path(doc.original_filename).stem}.pdf"
    stem = Path(expected_name).stem
    suffix = Path(expected_name).suffix
    pattern = re.compile(rf"^{re.escape(stem)}(_\d+)?{re.escape(suffix)}$")
    for entry in settings.consume_dir.iterdir():
        if not (entry.is_file() and pattern.match(entry.name)):
            continue
        st = entry.stat()
        if max(st.st_mtime, st.st_ctime) > started_epoch:
            return entry
    return None


def _finish(doc: Document, repo: Repository, settings: Settings) -> None:
    """Abschluss D4 — dieselben Schritte wie im regulären Ablauf: Original nachziehen
    (sofern noch im Eingang), zum Dokumenttyp passenden Endzustand setzen,
    Verlaufseintrag schreiben. Reihenfolge und Repository-Aufrufe wie in `_handle_ocr`
    bzw. `_handle_erechnung` (`app/pipeline.py`).
    """
    source = Path(doc.source_path)
    if source.exists():
        move_into(source, settings.processed_dir)
    if doc.doc_type in (DocType.ERECHNUNG_XML, DocType.ERECHNUNG_PDF):
        status, event_type, detail = (
            DocStatus.SKIPPED_ERECHNUNG,
            EventType.SKIPPED_ERECHNUNG,
            "E-Rechnung unverändert durchgereicht",
        )
    else:
        status, event_type, detail = DocStatus.DONE, EventType.DONE, "fertig"
    repo.set_status(doc.id, status)
    repo.add_event(
        doc.id,
        event_type,
        "Verarbeitung wurde durch einen Neustart unterbrochen; die Ablage war bereits "
        f"erfolgt, Vorgang nachträglich als abgeschlossen aufgelöst ({detail}).",
    )
