"""Entscheidung über einen angehaltenen Vorgang: freigeben oder verwerfen.

Ein Vorgang auf `blocked` wartet auf den Anwender. Ohne diesen zweiten Ausgang wäre der
Wartezustand eine Sackgasse: Das Original bleibt im Eingangsordner liegen (sonst nähme der
Watcher es erneut auf), und der Vorgang stünde auf Dauer in der Übersicht.

Eigenes Modul statt in `pipeline.py`, weil beide Entscheidungen aus der Weboberfläche
kommen und nicht aus dem Worker — analog zu `recovery.py`, das ebenfalls außerhalb der
Verarbeitung an den Zuständen arbeitet.
"""

from __future__ import annotations

import logging
from enum import StrEnum
from pathlib import Path

from .config import Settings
from .fileops import move_into
from .models import DocStatus, EventType
from .repository import Repository

log = logging.getLogger("lector.decisions")


class DecisionResult(StrEnum):
    RELEASED = "released"
    DISCARDED = "discarded"
    # Es gibt keinen Vorgang mit dieser Kennung.
    NOT_FOUND = "not_found"
    # Der Vorgang stand nicht (mehr) auf `blocked` — die Entscheidung war wirkungslos.
    NOT_BLOCKED = "not_blocked"
    # Freigabe ohne Original: Es gibt nichts mehr zu verarbeiten.
    SOURCE_MISSING = "source_missing"
    # Das Original ließ sich nicht in den Fehlerordner bewegen; der Vorgang wurde
    # zurück auf `blocked` gesetzt und kann erneut entschieden werden.
    DISCARD_FAILED = "discard_failed"


def release_document(document_id: int, repo: Repository, settings: Settings) -> DecisionResult:
    """Gibt einen angehaltenen Vorgang frei: zurück in die Reihe, Grenze übergangen."""
    doc = repo.get_document(document_id)
    if doc is None:
        return DecisionResult.NOT_FOUND
    if doc.status != DocStatus.BLOCKED:
        return DecisionResult.NOT_BLOCKED

    source = Path(doc.source_path)
    if not source.exists():
        # Ohne Original liefe die Freigabe ins Leere: Der Vorgang würde eingereiht und
        # scheiterte drei Versuche lang an derselben fehlenden Datei.
        message = (
            f"Freigabe nicht möglich: Das Original {source.name} liegt nicht mehr im "
            "Eingangsordner."
        )
        if not repo.transition_from_blocked(
            document_id, DocStatus.FAILED, error_message=message
        ):
            return DecisionResult.NOT_BLOCKED
        repo.add_event(document_id, EventType.FAILED, message)
        return DecisionResult.SOURCE_MISSING

    if not repo.transition_from_blocked(
        document_id, DocStatus.PENDING, approve_page_limit=True
    ):
        return DecisionResult.NOT_BLOCKED

    pages = doc.total_pages if doc.total_pages is not None else "?"
    repo.add_event(
        document_id,
        EventType.RELEASED,
        f"Freigegeben: {pages} Seiten werden trotz der Grenze von "
        f"{settings.max_pages_per_document} Seiten verarbeitet.",
    )
    log.info("Dokument %s freigegeben (%s Seiten)", document_id, pages)
    return DecisionResult.RELEASED


def discard_document(document_id: int, repo: Repository, settings: Settings) -> DecisionResult:
    """Verwirft einen angehaltenen Vorgang: Original in den Fehlerordner, `failed`."""
    doc = repo.get_document(document_id)
    if doc is None:
        return DecisionResult.NOT_FOUND
    if doc.status != DocStatus.BLOCKED:
        return DecisionResult.NOT_BLOCKED

    message = "Verworfen: Das Dokument wurde nicht verarbeitet (Seitenobergrenze)."
    if not repo.transition_from_blocked(
        document_id, DocStatus.FAILED, error_message=message
    ):
        return DecisionResult.NOT_BLOCKED

    # Erst nach dem beanspruchten Übergang bewegen — sonst könnte eine zweite,
    # gleichzeitige Entscheidung das Original verschieben, obwohl sie wirkungslos war.
    source = Path(doc.source_path)
    if source.exists():
        try:
            target = move_into(source, settings.error_dir)
        except OSError as error:
            # Der Vorgang DARF nicht auf `failed` stehen bleiben, während das Original
            # im Eingangsordner liegt: `find_by_hash_active` schließt genau `failed`
            # aus, der Watcher nähme die Datei beim nächsten Durchgang als neuen
            # Vorgang auf (dieselbe Falle wie Ruling R10 in `recovery.py`). `_handle_failure`
            # löst das, indem es zuerst bewegt; hier geht das nicht, weil der Übergang
            # gegen eine zeitgleiche Freigabe beansprucht sein muss. Also zurücknehmen.
            repo.update_document(
                document_id,
                status=DocStatus.BLOCKED,
                finished_at=None,
                error_message=f"Verwerfen fehlgeschlagen: {error}",
            )
            repo.add_event(
                document_id,
                EventType.BLOCKED,
                f"Verwerfen fehlgeschlagen ({error}). Der Vorgang bleibt angehalten, "
                "das Original liegt weiterhin im Eingangsordner.",
            )
            log.exception("Verwerfen von Dokument %s fehlgeschlagen", document_id)
            return DecisionResult.DISCARD_FAILED
        log.info("Dokument %s verworfen, Original nach %s", document_id, target)
    repo.add_event(document_id, EventType.DISCARDED, message)
    return DecisionResult.DISCARDED
