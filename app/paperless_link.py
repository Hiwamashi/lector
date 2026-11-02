"""Verknüpfung Lector-Vorgang -> Paperless-Dokument (Change scan-paperless-verknuepfung).

Paperless speichert als Prüfsumme die SHA-256 der eingelieferten Datei. Lector hält beim
Ablegen die SHA-256 der Datei in `consume` fest (`documents.output_hash`) und sucht das
Dokument regelmäßig über diese Prüfsumme. Für den Altbestand ohne Ausgabe-Prüfsumme gibt es
eine gekennzeichnete Ausnahme über Dateiname und enges Zeitfenster.

Ein Lauf (`PaperlessLinker.run_once`):

1. offene Vorgänge (`pending`) in Stapeln über die Prüfsumme suchen,
2. Altbestand nachholen (abgeschlossene Vorgänge ohne Verknüpfung; nach jedem Start außerdem
   einmal die als `not_found` markierten),
3. bei Netz-/Serverfehlern abbrechen, ohne den Zustand des gerade geprüften Vorgangs zu ändern.

Ob ein verknüpftes Dokument in Paperless gelöscht wurde (`missing`), prüft dieser Job bewusst
nicht — das passiert beim Öffnen der Ansicht.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from .config import Settings
from .models import DocType, Document, EventType, PaperlessLink
from .paperless import (
    FIND_MAX_HITS,
    DocumentHit,
    PaperlessClient,
    PaperlessError,
    TooManyHitsError,
)
from .repository import Repository

log = logging.getLogger("lector.paperless_link")

# Filternamen der Paperless-API (gegen die echte Instanz geprüft, Aufgabe 1.1). Als
# Konstanten, damit eine Anpassung an einer Stelle genügt.
FILTER_CHECKSUM = "checksum__iexact"
FILTER_ORIGINAL_NAME = "original_filename__iexact"
FILTER_ADDED_FROM = "added__gte"
FILTER_ADDED_TO = "added__lte"

# Stapelgröße je Lauf (getrennt für offene Vorgänge und Nachholen).
BATCH_SIZE = 50
# Frist, nach der ein nicht gefundenes Dokument als `not_found` gilt; zugleich Breite des
# Zeitfensters der Namenssuche.
NOT_FOUND_AFTER = timedelta(hours=24)
# Tägliche Wiederholung für `not_found`-Vorgänge mit Prüfsumme (Paperless war länger aus),
# solange die Ablage nicht älter ist als diese Frist.
DAILY_RECHECK_INTERVAL = timedelta(hours=24)
DAILY_RECHECK_MAX_AGE = timedelta(days=14)
# Kurze Pause statt des vollen Takts, solange noch ein voller Nachhol-Stapel ansteht.
BACKLOG_SLEEP_SECONDS = 5.0

_ERECHNUNG_TYPES = (DocType.ERECHNUNG_XML, DocType.ERECHNUNG_PDF)


def link_configured(settings: Settings) -> bool:
    """Paperless-Anbindung vorhanden (Adresse und Zugangsschlüssel)."""
    return bool(settings.paperless_url and settings.paperless_token)


@dataclass
class LinkRunResult:
    """Ergebnis eines Laufs — für Logs und Tests."""

    linked: int = 0
    linked_by_name: int = 0
    not_found: int = 0
    checked: int = 0
    aborted: bool = False
    more_work: bool = False


def _iso_z(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_added(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


class PaperlessLinker:
    def __init__(
        self,
        settings: Settings,
        repo: Repository,
        *,
        client_factory: Callable[[], PaperlessClient] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings = settings
        self.repo = repo
        self._client_factory = client_factory or (
            lambda: PaperlessClient(settings.paperless_url, settings.paperless_token)
        )
        self._now = now or (lambda: datetime.now(UTC))
        # Nach dem Start werden einmal auch `not_found`-Vorgänge erneut gesucht.
        self._started_at = self._now()

    @property
    def enabled(self) -> bool:
        return link_configured(self.settings)

    # ---- Lauf ---------------------------------------------------------------

    async def run_once(self) -> LinkRunResult:
        result = LinkRunResult()
        try:
            async with self._client_factory() as client:
                for doc in self.repo.list_paperless_pending(BATCH_SIZE):
                    await self._resolve(client, doc, result)
                now = self._now()
                catchup = self.repo.list_paperless_catchup(
                    recheck_before=self._started_at,
                    daily_before=now - DAILY_RECHECK_INTERVAL,
                    daily_consumed_after=now - DAILY_RECHECK_MAX_AGE,
                    limit=BATCH_SIZE,
                )
                for doc in catchup:
                    await self._resolve(client, doc, result)
                result.more_work = len(catchup) >= BATCH_SIZE
        except (httpx.HTTPError, PaperlessError) as error:
            # Der Zustand des gerade geprüften Vorgangs bleibt unverändert; der nächste
            # Lauf versucht es erneut.
            log.warning(
                "Paperless-Verknüpfung abgebrochen: %s: %s", type(error).__name__, error
            )
            result.aborted = True
            result.more_work = False
        if result.linked or result.linked_by_name or result.not_found:
            log.info(
                "Paperless-Verknüpfung: %s verknüpft, %s über Dateinamen, %s nicht gefunden",
                result.linked,
                result.linked_by_name,
                result.not_found,
            )
        return result

    # ---- Einzelner Vorgang --------------------------------------------------

    def _consumed_at(self, doc: Document) -> datetime:
        """Zeitpunkt der Ablage; für den Altbestand aus Ereignis, `finished_at`, `created_at`."""
        stamp = doc.consumed_at
        if stamp is None:
            stamp = self.repo.event_timestamp(doc.id, EventType.MOVED_TO_CONSUME)
        if stamp is None:
            stamp = doc.finished_at or doc.created_at or self._now()
        if doc.consumed_at is None:
            self.repo.update_document(
                doc.id, consumed_at=stamp.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")
            )
        return stamp

    @staticmethod
    def _checksum(doc: Document) -> str | None:
        if doc.output_hash:
            return doc.output_hash
        if doc.doc_type in _ERECHNUNG_TYPES and doc.file_hash:
            return doc.file_hash  # unverändert durchgereicht: gleiche Bytes
        return None

    async def _resolve(
        self, client: PaperlessClient, doc: Document, result: LinkRunResult
    ) -> None:
        result.checked += 1
        consumed_at = self._consumed_at(doc)
        checksum = self._checksum(doc)
        if checksum:
            await self._resolve_by_checksum(client, doc, checksum, consumed_at, result)
        else:
            await self._resolve_by_name(client, doc, consumed_at, result)

    async def _resolve_by_checksum(
        self,
        client: PaperlessClient,
        doc: Document,
        checksum: str,
        consumed_at: datetime,
        result: LinkRunResult,
    ) -> None:
        hits = await client.find_documents(**{FILTER_CHECKSUM: checksum})
        if len(hits) == 1:
            self._link(doc, PaperlessLink.LINKED, hits[0].id, "über die Prüfsumme", result)
            return
        if len(hits) > 1:
            # Prüfsummen sind in Paperless eindeutig — mehrere Treffer sprechen für einen
            # unbrauchbaren Filter. Nicht verknüpfen, nicht als `not_found` markieren.
            log.warning(
                "Dokument %s: %s Treffer für eine Prüfsumme (max. %s erwartet 1) — "
                "nicht verknüpft",
                doc.id,
                len(hits),
                FIND_MAX_HITS,
            )
            self.repo.touch_paperless_checked(doc.id)
            return
        if doc.paperless_link == PaperlessLink.NOT_FOUND:
            self.repo.touch_paperless_checked(doc.id)
        elif self._now() - consumed_at > NOT_FOUND_AFTER:
            self._not_found(doc, result)
        elif doc.paperless_link is None:
            self.repo.set_paperless_link(doc.id, PaperlessLink.PENDING)
        else:
            self.repo.touch_paperless_checked(doc.id)

    async def _resolve_by_name(
        self,
        client: PaperlessClient,
        doc: Document,
        consumed_at: datetime,
        result: LinkRunResult,
    ) -> None:
        name = Path(doc.output_path).name if doc.output_path else None
        if not name:
            self._not_found(doc, result)
            return
        window_end = consumed_at + NOT_FOUND_AFTER
        try:
            hits = await client.find_documents(
                **{
                    FILTER_ORIGINAL_NAME: name,
                    FILTER_ADDED_FROM: _iso_z(consumed_at),
                    FILTER_ADDED_TO: _iso_z(window_end),
                }
            )
        except TooManyHitsError:
            # Ein häufiger Name (z. B. `scan.pdf`) ist mehrdeutig, kein Filterfehler — der
            # Filter selbst wurde im Prüfsummenpfad schon als unterstützt erkannt.
            log.info("Dokument %s: zu viele Treffer für den Dateinamen — mehrdeutig", doc.id)
            self._not_found(doc, result)
            return
        # Paperless ignoriert Filter, die es nicht kennt — Name und Zeitfenster daher
        # am Treffer selbst gegenprüfen. Treffer, die schon zu einem anderen Vorgang
        # gehören, scheiden aus (zwei gleichnamige Scans, einer davon bereits verknüpft).
        matching = [
            hit
            for hit in hits
            if self._name_hit_ok(hit, name, consumed_at, window_end)
            and not self.repo.paperless_id_taken(hit.id, exclude_document_id=doc.id)
        ]
        if len(matching) == 1:
            self._link(
                doc, PaperlessLink.LINKED_BY_NAME, matching[0].id, "über den Dateinamen", result
            )
        else:
            self._not_found(doc, result)

    @staticmethod
    def _name_hit_ok(
        hit: DocumentHit, name: str, window_start: datetime, window_end: datetime
    ) -> bool:
        if (hit.original_file_name or "").casefold() != name.casefold():
            return False
        added = _parse_added(hit.added)
        return added is not None and window_start <= added <= window_end

    # ---- Zustände schreiben ---------------------------------------------------

    def _link(
        self,
        doc: Document,
        link: PaperlessLink,
        paperless_id: int,
        how: str,
        result: LinkRunResult,
    ) -> None:
        self.repo.set_paperless_link(doc.id, link, paperless_id=paperless_id)
        self.repo.add_event(
            doc.id,
            EventType.PAPERLESS_LINKED,
            f"Mit Paperless-Dokument #{paperless_id} verknüpft ({how})",
        )
        if link == PaperlessLink.LINKED_BY_NAME:
            result.linked_by_name += 1
        else:
            result.linked += 1

    def _not_found(self, doc: Document, result: LinkRunResult) -> None:
        if doc.paperless_link == PaperlessLink.NOT_FOUND:
            self.repo.touch_paperless_checked(doc.id)
            return
        self.repo.set_paperless_link(doc.id, PaperlessLink.NOT_FOUND)
        result.not_found += 1
