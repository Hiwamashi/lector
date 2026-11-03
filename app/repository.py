"""Repository-Schicht: CRUD für documents/document_events, Event-Logging, Fortschritt.

Threadsicher (eine geteilte Verbindung + Lock), da der Worker in einem Thread-Pool läuft,
während FastAPI-Handler asynchron auf dieselbe DB zugreifen. Bei jeder Statusänderung wird
optional ein Notifier aufgerufen, damit die SSE-Schicht Live-Updates verteilen kann.
"""

from __future__ import annotations

import json
import logging
import secrets
import sqlite3
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path

from .context_classification import same_label
from .db import connect, init_db
from .models import (
    CorrespondentHistory,
    DocStatus,
    DocType,
    Document,
    EventType,
    GiroStatus,
    InvoiceEventType,
    InvoiceVoucherMatch,
    MatchKind,
    OcrPage,
    PaperlessInvoice,
    PaperlessLink,
    RecipientCache,
    RecipientStatus,
    SevdeskStatus,
    SevdeskSyncState,
    SevdeskVoucher,
    ocr_pages_from_payload,
    ocr_pages_to_payload,
)

log = logging.getLogger("lector.repository")

# Kurze Frist für `check_health`: Alle Zugriffe teilen eine Verbindung hinter `self._lock`
# (Pipeline im Thread-Pool wie asyncio-Requests). Die Prüfung darf nicht warten — sonst
# meldete ein Container unter Last sich selbst als ungesund, genau dann, wenn man den
# Zustand liest (design.md D5). Bruchteil einer Sekunde: kurz genug, um unter Last nicht
# selbst zu blockieren, lang genug, um eine kurze, reguläre Transaktion nicht fälschlich
# als "beschäftigt" auszuweisen.
_HEALTH_CHECK_LOCK_TIMEOUT_SECONDS = 0.2

# Gültigkeit der Web-Sitzungen (design.md D10): Leerlauf gleitend, Gesamtdauer absolut.
WEB_SESSION_IDLE = timedelta(days=30)
WEB_SESSION_ABSOLUTE = timedelta(days=90)
WEB_SESSION_TS_FORMAT = "%Y-%m-%d %H:%M:%S"


def _ts(now: datetime | None = None) -> str:
    """UTC-Zeitstempel im Repository-Format; ``now`` macht die Uhr für Tests injizierbar."""
    return (now or datetime.now(UTC)).astimezone(UTC).strftime(WEB_SESSION_TS_FORMAT)


class DatabaseHealthState(StrEnum):
    """Ausgang der Zustandsprüfung der Datenbank (siehe `Repository.check_health`)."""

    USABLE = "usable"
    # Lock in der Frist nicht erhalten — die Datenbank wird benutzt, sie ist nicht kaputt.
    BUSY = "busy"
    UNUSABLE = "unusable"

    @property
    def healthy(self) -> bool:
        """`USABLE` und `BUSY` gelten beide als gesund — nur `BUSY` unterlassen zu
        werten würde jeden Container unter Last als ungesund melden, genau in dem
        Moment, in dem man den Zustand liest (design.md D5). Als Eigenschaft am Enum
        statt als Vergleich beim Aufrufer, damit diese Bewertung nicht an jeder
        Verbrauchsstelle erneut abgeleitet werden muss.
        """
        return self in (DatabaseHealthState.USABLE, DatabaseHealthState.BUSY)


@dataclass
class DatabaseHealth:
    """Zustandsauskunft der Datenbank — rein lesend ermittelt, keine Selbstheilung."""

    state: DatabaseHealthState
    error: str | None = None


_INVOICE_COLUMNS = (
    "id, paperless_id, title, correspondent, creditor_name, iban, bic, amount, currency, "
    "purpose, source, giro_status, sevdesk_status, sevdesk_voucher_id, paid, exported_at, "
    "written_back_at, last_synced_at, error_message, document_date, created_at, "
    "recipient_label, paperless_voucher_ref, review_reason"
)

_DOC_COLUMNS = (
    "id, original_filename, source_path, file_hash, status, doc_type, ocr_engine, "
    "total_pages, processed_pages, attempt_count, next_retry_at, error_message, "
    "output_path, page_limit_approved, created_at, started_at, finished_at, "
    "output_hash, original_path, consumed_at, paperless_id, paperless_link, "
    "paperless_checked_at"
)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    # SQLite datetime('now') liefert "YYYY-MM-DD HH:MM:SS" (UTC, ohne tz-Info)
    try:
        return datetime.fromisoformat(value).replace(tzinfo=UTC)
    except ValueError:
        return None


def _normalize_doc_date(value: str | None) -> str | None:
    """Bringt ein Dokumentdatum auf eine kanonische, lexikografisch sortierbare Form.

    Paperless liefert ``created`` als ISO-8601 mit Zeitzonen-Offset (z.B. ``+01:00`` bzw.
    ``+02:00`` über die DST-Grenze). Da ``ORDER BY`` auf dem rohen TEXT arbeitet, würde der
    Offset-Suffix die lexikografische Sortierung gegenüber der wahren Reihenfolge verfälschen.
    Wir verwerfen den Offset (konsistent zu ``_parse_dt``, das die Wall-Clock-Zeit als UTC liest),
    sodass die Sortierung der Wall-Clock-Zeit entspricht. Nicht parsebare Werte bleiben unverändert.
    """
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None).isoformat()
    except ValueError:
        return value


def _row_to_document(row: sqlite3.Row) -> Document:
    return Document(
        id=row["id"],
        original_filename=row["original_filename"],
        source_path=row["source_path"],
        file_hash=row["file_hash"],
        status=DocStatus(row["status"]),
        doc_type=DocType(row["doc_type"]) if row["doc_type"] else None,
        ocr_engine=row["ocr_engine"],
        total_pages=row["total_pages"],
        processed_pages=row["processed_pages"],
        attempt_count=row["attempt_count"],
        next_retry_at=_parse_dt(row["next_retry_at"]),
        error_message=row["error_message"],
        output_path=row["output_path"],
        page_limit_approved=bool(row["page_limit_approved"]),
        created_at=_parse_dt(row["created_at"]),
        started_at=_parse_dt(row["started_at"]),
        finished_at=_parse_dt(row["finished_at"]),
        output_hash=row["output_hash"],
        original_path=row["original_path"],
        consumed_at=_parse_dt(row["consumed_at"]),
        paperless_id=row["paperless_id"],
        paperless_link=PaperlessLink(row["paperless_link"]) if row["paperless_link"] else None,
        paperless_checked_at=_parse_dt(row["paperless_checked_at"]),
    )


def _parse_invoice(row: sqlite3.Row) -> PaperlessInvoice:
    return PaperlessInvoice(
        id=row["id"],
        paperless_id=row["paperless_id"],
        title=row["title"],
        correspondent=row["correspondent"],
        creditor_name=row["creditor_name"],
        iban=row["iban"],
        bic=row["bic"],
        amount=row["amount"],
        currency=row["currency"] or "EUR",
        purpose=row["purpose"],
        source=row["source"],
        giro_status=GiroStatus(row["giro_status"]),
        sevdesk_status=SevdeskStatus(row["sevdesk_status"]),
        sevdesk_voucher_id=row["sevdesk_voucher_id"],
        paid=bool(row["paid"]),
        exported_at=_parse_dt(row["exported_at"]),
        written_back_at=_parse_dt(row["written_back_at"]),
        last_synced_at=_parse_dt(row["last_synced_at"]),
        error_message=row["error_message"],
        document_date=_parse_dt(row["document_date"]),
        created_at=_parse_dt(row["created_at"]),
        recipient_label=row["recipient_label"],
        paperless_voucher_ref=row["paperless_voucher_ref"],
        review_reason=row["review_reason"],
    )


class _Unset:
    """Marker für „Argument nicht übergeben“ — unterscheidet sich von ``None`` (= NULL setzen)."""

    def __repr__(self) -> str:
        return "<unset>"


_UNSET = _Unset()


class UpsertResult(StrEnum):
    NEW = "new"
    CHANGED = "changed"
    UNCHANGED = "unchanged"


@dataclass(frozen=True)
class InvoiceUpsert:
    """Eingabe für ``Repository.upsert_invoices`` (Felder wie bei ``upsert_invoice``)."""

    paperless_id: int
    title: str | None
    # ``_UNSET``: Name nicht ermittelbar — gespeicherter Wert bleibt stehen (beim INSERT NULL).
    correspondent: str | None | _Unset
    document_date: str | None = None
    recipient_label: str | None | _Unset = _UNSET
    paperless_voucher_ref: str | None | _Unset = _UNSET


@dataclass(frozen=True)
class InvoiceUpsertOutcome:
    """Ergebnis je Rechnung: ID, was passiert ist und der Stand davor (``None`` bei neu)."""

    invoice_id: int
    result: UpsertResult
    before: PaperlessInvoice | None

# Sevdesk-Stati, die ein laufender oder abgeschlossener Export belegt; set_review/dismiss
# dürfen sie nicht überschreiben (analog zur Ausschlussliste von claim_for_export).
_EXPORT_LOCKED_STATUSES = (
    SevdeskStatus.EXPORTED.value,
    SevdeskStatus.EXPORTING.value,
    SevdeskStatus.UNCERTAIN.value,
)

_VOUCHER_COLUMNS = (
    "voucher_id, voucher_date, supplier_name, sum_gross, currency, description, status, "
    "last_seen_at"
)


def _parse_voucher(row: sqlite3.Row) -> SevdeskVoucher:
    return SevdeskVoucher(
        voucher_id=row["voucher_id"],
        voucher_date=row["voucher_date"],
        supplier_name=row["supplier_name"],
        sum_gross=row["sum_gross"],
        currency=row["currency"],
        description=row["description"],
        status=row["status"],
        last_seen_at=_parse_dt(row["last_seen_at"]),
    )


def _parse_match(row: sqlite3.Row) -> InvoiceVoucherMatch:
    return InvoiceVoucherMatch(
        invoice_id=row["invoice_id"],
        voucher_id=row["voucher_id"],
        kind=MatchKind(row["kind"]),
        score=row["score"],
        decided_at=_parse_dt(row["decided_at"]),
        created_at=_parse_dt(row["created_at"]),
    )


class Repository:
    def __init__(self, db_path: Path, notifier: Callable[[str], None] | None = None) -> None:
        self._conn = connect(db_path)
        init_db(self._conn)
        self._lock = threading.Lock()
        self._notifier = notifier

    def set_notifier(self, notifier: Callable[[str], None]) -> None:
        self._notifier = notifier

    def _emit(self, token: str) -> None:
        if self._notifier:
            try:
                self._notifier(token)
            except Exception:
                pass

    def _notify(self, document_id: int) -> None:
        self._emit(f"doc:{document_id}")

    def _notify_invoice(self, invoice_id: int) -> None:
        self._emit(f"inv:{invoice_id}")

    def notify_recipient(self, paperless_id: int) -> None:
        """Signalisiert der UI eine Änderung an der Empfänger-Übersicht (SSE-Token)."""
        self._emit(f"rec:{paperless_id}")

    def notify_batch(self) -> None:
        """Signalisiert der UI den Fortschritt des KI-Batch-Laufs (SSE-Token)."""
        self._emit("batch:recipient")

    def notify_vouchers(self) -> None:
        """Signalisiert den Listenseiten einen neuen Belegabzug/Abrufstand (SSE-Token).

        Listenseiten laden bei jedem Token neu (``app.js``); Detailseiten reagieren nur auf
        ihr eigenes ``inv:<id>`` und werden über Rechnungs-Ereignisse benachrichtigt."""
        self._emit("vouchers:sync")

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def check_health(
        self, timeout: float = _HEALTH_CHECK_LOCK_TIMEOUT_SECONDS
    ) -> DatabaseHealth:
        """Prüft, ob die Datenbank benutzbar ist — wartet dabei höchstens `timeout`
        Sekunden auf den geteilten Lock, statt unbegrenzt zu blockieren.

        Nimmt `self._lock` nur mit kurzer Frist. Läuft sie ab, gilt die Datenbank als
        *beschäftigt* — nicht als kaputt, denn ein anderer Zugriff (Pipeline im
        Thread-Pool oder ein anderer Request) hält den Lock gerade. Erst wenn der Lock
        erhalten wird und die anschließende, rein lesende Testabfrage fehlschlägt, gilt
        die Datenbank als *nicht benutzbar*.

        Legt keinen Vorgang an, schreibt keinen Verlaufseintrag und verändert keinen
        Zustand.
        """
        if not self._lock.acquire(timeout=timeout):
            return DatabaseHealth(DatabaseHealthState.BUSY)
        try:
            self._conn.execute("SELECT 1").fetchone()
        except sqlite3.Error as exc:
            return DatabaseHealth(
                DatabaseHealthState.UNUSABLE, error=f"{type(exc).__name__}: {exc}"
            )
        finally:
            self._lock.release()
        return DatabaseHealth(DatabaseHealthState.USABLE)

    # ---- documents -------------------------------------------------------

    def create_document(
        self, *, original_filename: str, source_path: str, file_hash: str | None = None
    ) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO documents (original_filename, source_path, file_hash, status) "
                "VALUES (?, ?, ?, ?)",
                (original_filename, source_path, file_hash, DocStatus.PENDING),
            )
            self._conn.commit()
            doc_id = int(cur.lastrowid)
        self._notify(doc_id)
        return doc_id

    def get_document(self, document_id: int) -> Document | None:
        with self._lock:
            row = self._conn.execute(
                f"SELECT {_DOC_COLUMNS} FROM documents WHERE id = ?", (document_id,)
            ).fetchone()
        return _row_to_document(row) if row else None

    def find_by_hash_active(self, file_hash: str) -> Document | None:
        """Findet ein nicht endgültig fehlgeschlagenes Dokument mit gleichem Hash."""
        with self._lock:
            row = self._conn.execute(
                f"SELECT {_DOC_COLUMNS} FROM documents "
                "WHERE file_hash = ? AND status != ? ORDER BY id DESC LIMIT 1",
                (file_hash, DocStatus.FAILED),
            ).fetchone()
        return _row_to_document(row) if row else None

    def list_documents(
        self,
        *,
        status: DocStatus | None = None,
        search: str | None = None,
        since: datetime | None = None,
        paperless_missing: bool = False,
        limit: int = 200,
        offset: int = 0,
    ) -> list[Document]:
        clauses: list[str] = []
        params: list[object] = []
        if paperless_missing:
            # Schnellfilter „Nicht in Paperless“: abgeschlossene Vorgänge ohne Verknüpfung.
            clauses.append("status IN (?, ?)")
            params.extend([DocStatus.DONE.value, DocStatus.SKIPPED_ERECHNUNG.value])
            clauses.append("paperless_link IN (?, ?, ?)")
            params.extend(
                [
                    PaperlessLink.PENDING.value,
                    PaperlessLink.NOT_FOUND.value,
                    PaperlessLink.MISSING.value,
                ]
            )
        if status:
            clauses.append("status = ?")
            params.append(status.value)
        if search:
            clauses.append("original_filename LIKE ?")
            params.append(f"%{search}%")
        if since:
            clauses.append("created_at >= ?")
            params.append(since.strftime("%Y-%m-%d %H:%M:%S"))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend([limit, offset])
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {_DOC_COLUMNS} FROM documents {where} "
                "ORDER BY id DESC LIMIT ? OFFSET ?",
                params,
            ).fetchall()
        return [_row_to_document(r) for r in rows]

    # ---- Verknüpfung mit Paperless ----------------------------------------

    def mark_consumed(
        self,
        document_id: int,
        *,
        output_path: str,
        output_hash: str,
        link_pending: bool,
    ) -> None:
        """Hält die Ablage in `consume` fest: Pfad, SHA-256 der abgelegten Datei, Zeitpunkt.

        `link_pending` setzt den Verknüpfungszustand auf `pending` (Paperless-Anbindung
        konfiguriert); sonst bleibt er `NULL`, und ein späteres Nachholen holt den Vorgang ein.
        """
        with self._lock:
            self._conn.execute(
                "UPDATE documents SET output_path = ?, output_hash = ?, "
                "consumed_at = datetime('now'), paperless_link = ? WHERE id = ?",
                (
                    output_path,
                    output_hash,
                    PaperlessLink.PENDING.value if link_pending else None,
                    document_id,
                ),
            )
            self._conn.commit()
        self._notify(document_id)

    def set_paperless_link(
        self,
        document_id: int,
        link: PaperlessLink,
        *,
        paperless_id: int | None = None,
    ) -> None:
        """Setzt den Verknüpfungszustand und vermerkt die Suche (`paperless_checked_at`).

        Ohne `paperless_id` bleibt eine vorhandene ID erhalten (z. B. bei `missing`).
        """
        with self._lock:
            self._conn.execute(
                "UPDATE documents SET paperless_link = ?, "
                "paperless_id = COALESCE(?, paperless_id), "
                "paperless_checked_at = datetime('now') WHERE id = ?",
                (link.value, paperless_id, document_id),
            )
            self._conn.commit()
        self._notify(document_id)

    def touch_paperless_checked(self, document_id: int) -> None:
        """Vermerkt eine Suche ohne Zustandsänderung (Fortschritt für Stapel und Nachholen)."""
        with self._lock:
            self._conn.execute(
                "UPDATE documents SET paperless_checked_at = datetime('now') WHERE id = ?",
                (document_id,),
            )
            self._conn.commit()

    def list_paperless_pending(self, limit: int = 50) -> list[Document]:
        """Abgeschlossene Vorgänge mit Zustand `pending`; die am längsten ungeprüften zuerst."""
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {_DOC_COLUMNS} FROM documents "
                "WHERE status IN (?, ?) AND paperless_link = ? "
                "ORDER BY paperless_checked_at IS NOT NULL, paperless_checked_at, id LIMIT ?",
                (
                    DocStatus.DONE.value,
                    DocStatus.SKIPPED_ERECHNUNG.value,
                    PaperlessLink.PENDING.value,
                    limit,
                ),
            ).fetchall()
        return [_row_to_document(r) for r in rows]

    def list_paperless_catchup(
        self,
        *,
        recheck_before: datetime,
        daily_before: datetime | None = None,
        daily_consumed_after: datetime | None = None,
        limit: int = 50,
    ) -> list[Document]:
        """Nachzuholende Vorgänge: abgeschlossen und ohne Verknüpfung (`NULL`), außerdem
        `not_found`-Vorgänge, die seit `recheck_before` (Start des Dienstes) nicht erneut
        gesucht wurden.

        Mit `daily_before` und `daily_consumed_after` kommen `not_found`-Vorgänge MIT
        Prüfsumme (`output_hash`, bei E-Rechnungen `file_hash`) hinzu, die seit
        `daily_before` nicht gesucht wurden und deren Ablage nicht älter als
        `daily_consumed_after` ist (tägliche Wiederholung, falls Paperless länger aus war).

        Reihenfolge wie bei `list_paperless_pending`: am längsten ungeprüfte zuerst, damit
        Dauerfälle nicht dauerhaft vorne stehen. Fehlgeschlagene und verworfene Vorgänge
        kommen nie vor (nur `done`/`skipped_erechnung`).
        """
        fmt = "%Y-%m-%d %H:%M:%S"
        not_found_conditions = ["paperless_checked_at IS NULL", "paperless_checked_at < ?"]
        params: list[object] = [
            DocStatus.DONE.value,
            DocStatus.SKIPPED_ERECHNUNG.value,
            PaperlessLink.NOT_FOUND.value,
            recheck_before.strftime(fmt),
        ]
        if daily_before is not None and daily_consumed_after is not None:
            not_found_conditions.append(
                "(paperless_checked_at < ? AND consumed_at >= ? AND "
                "(output_hash IS NOT NULL OR (doc_type IN (?, ?) AND file_hash IS NOT NULL)))"
            )
            params.extend(
                [
                    daily_before.strftime(fmt),
                    daily_consumed_after.strftime(fmt),
                    DocType.ERECHNUNG_XML.value,
                    DocType.ERECHNUNG_PDF.value,
                ]
            )
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {_DOC_COLUMNS} FROM documents "
                "WHERE status IN (?, ?) AND (paperless_link IS NULL OR "
                f"(paperless_link = ? AND ({' OR '.join(not_found_conditions)}))) "
                "ORDER BY paperless_checked_at IS NOT NULL, paperless_checked_at, id LIMIT ?",
                params,
            ).fetchall()
        return [_row_to_document(r) for r in rows]

    def paperless_id_taken(self, paperless_id: int, *, exclude_document_id: int) -> bool:
        """Ob die Paperless-ID bereits einem anderen Vorgang zugeordnet ist."""
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM documents WHERE paperless_id = ? AND id != ? "
                "AND paperless_link IN (?, ?) LIMIT 1",
                (
                    paperless_id,
                    exclude_document_id,
                    PaperlessLink.LINKED.value,
                    PaperlessLink.LINKED_BY_NAME.value,
                ),
            ).fetchone()
        return row is not None

    def event_timestamp(self, document_id: int, event_type: EventType) -> datetime | None:
        """Zeitpunkt des jüngsten Ereignisses dieser Art (z. B. `moved_to_consume`)."""
        with self._lock:
            row = self._conn.execute(
                "SELECT MAX(timestamp) AS ts FROM document_events "
                "WHERE document_id = ? AND event_type = ?",
                (document_id, event_type.value),
            ).fetchone()
        return _parse_dt(row["ts"]) if row else None

    def status_counts(self) -> dict[str, int]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT status, COUNT(*) AS n FROM documents GROUP BY status"
            ).fetchall()
        return {r["status"]: r["n"] for r in rows}

    def update_document(self, document_id: int, **fields: object) -> None:
        if not fields:
            return
        # Enums auf ihre Werte abbilden
        clean = {k: (v.value if hasattr(v, "value") else v) for k, v in fields.items()}
        assignments = ", ".join(f"{k} = ?" for k in clean)
        with self._lock:
            self._conn.execute(
                f"UPDATE documents SET {assignments} WHERE id = ?",
                [*clean.values(), document_id],
            )
            self._conn.commit()
        self._notify(document_id)

    def set_status(
        self, document_id: int, status: DocStatus, *, error_message: str | None = None
    ) -> None:
        fields: dict[str, object] = {"status": status}
        now = "datetime('now')"
        if status == DocStatus.PROCESSING:
            with self._lock:
                self._conn.execute(
                    f"UPDATE documents SET status = ?, started_at = {now} WHERE id = ?",
                    (status.value, document_id),
                )
                self._conn.commit()
            self._notify(document_id)
            return
        if status in (DocStatus.DONE, DocStatus.SKIPPED_ERECHNUNG, DocStatus.FAILED):
            with self._lock:
                self._conn.execute(
                    f"UPDATE documents SET status = ?, finished_at = {now}, error_message = ? "
                    "WHERE id = ?",
                    (status.value, error_message, document_id),
                )
                self._conn.commit()
            # Endzustand: Es kommt kein Wiederholversuch mehr, der die bewahrten
            # Teilergebnisse brauchen koennte.
            self.clear_chunk_results(document_id)
            self._notify(document_id)
            return
        self.update_document(document_id, **fields)

    def transition_from_blocked(
        self,
        document_id: int,
        status: DocStatus,
        *,
        error_message: str | None = None,
        approve_page_limit: bool = False,
    ) -> bool:
        """Führt einen angehaltenen Vorgang in einen anderen Zustand — bedingt und atomar.

        Prüfen und Schreiben in einem Schritt, weil sonst ein Doppelklick auf „Freigeben"
        oder ein Freigeben in der einen und ein Verwerfen in einer zweiten Ansicht beide
        Zweige ausführen würde: Das Original wanderte in den Fehlerordner, während der
        Vorgang bereits in der Verarbeitungsreihe steht.

        Gibt zurück, ob der Übergang stattgefunden hat. `False` heißt: Der Vorgang stand
        nicht (mehr) auf `blocked` — die Entscheidung war wirkungslos.
        """
        assignments = ["status = ?"]
        params: list[object] = [status.value]
        if approve_page_limit:
            assignments.append("page_limit_approved = 1")
        if status in (DocStatus.DONE, DocStatus.SKIPPED_ERECHNUNG, DocStatus.FAILED):
            assignments.append("finished_at = datetime('now')")
            assignments.append("error_message = ?")
            params.append(error_message)
        else:
            # Zurück in die Reihe: sofort fällig, und der Versuchszähler bleibt unberührt —
            # die Blockade war kein Fehlversuch.
            assignments.append("next_retry_at = NULL")
        with self._lock:
            cur = self._conn.execute(
                f"UPDATE documents SET {', '.join(assignments)} "
                "WHERE id = ? AND status = ?",
                [*params, document_id, DocStatus.BLOCKED.value],
            )
            self._conn.commit()
            changed = cur.rowcount > 0
        if changed:
            # Dieser Weg umgeht `set_status` — die Freigabe muss hier eigens erfolgen.
            if status in (DocStatus.DONE, DocStatus.SKIPPED_ERECHNUNG, DocStatus.FAILED):
                self.clear_chunk_results(document_id)
            self._notify(document_id)
        return changed

    def set_progress(self, document_id: int, processed_pages: int) -> None:
        self.update_document(document_id, processed_pages=processed_pages)

    def increment_attempt(self, document_id: int) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE documents SET attempt_count = attempt_count + 1 WHERE id = ?",
                (document_id,),
            )
            self._conn.commit()
        self._notify(document_id)

    def schedule_retry(self, document_id: int, delay_minutes: int) -> datetime:
        retry_at = datetime.now(UTC) + timedelta(minutes=delay_minutes)
        with self._lock:
            self._conn.execute(
                "UPDATE documents SET status = ?, next_retry_at = ? WHERE id = ?",
                (
                    DocStatus.PENDING.value,
                    retry_at.strftime("%Y-%m-%d %H:%M:%S"),
                    document_id,
                ),
            )
            self._conn.commit()
        self._notify(document_id)
        return retry_at

    def claim_due_retries(self) -> list[Document]:
        """Liefert pending-Dokumente, deren Retry-Zeitpunkt erreicht ist (oder nie gesetzt)."""
        now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {_DOC_COLUMNS} FROM documents "
                "WHERE status = ? AND (next_retry_at IS NULL OR next_retry_at <= ?) "
                "ORDER BY id ASC",
                (DocStatus.PENDING.value, now),
            ).fetchall()
        return [_row_to_document(r) for r in rows]

    def list_processing(self) -> list[Document]:
        """Liefert alle Vorgänge im Zustand `processing`, nach `id` geordnet.

        Grundlage für die Recovery beim Start: Da die Verarbeitung streng seriell in
        genau einem Prozess läuft, gehört ein Vorgang auf `processing` beim Neustart
        garantiert zu keinem lebenden Bearbeiter mehr.
        """
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {_DOC_COLUMNS} FROM documents WHERE status = ? ORDER BY id ASC",
                (DocStatus.PROCESSING.value,),
            ).fetchall()
        return [_row_to_document(r) for r in rows]

    # ---- ocr_chunk_cache (bewahrte Teilergebnisse der Texterkennung) ------

    def store_chunk_result(
        self,
        document_id: int,
        chunk_index: int,
        *,
        fingerprint: str,
        pages: list[OcrPage],
    ) -> None:
        """Legt das Ergebnis eines Blocks ab (Upsert je Vorgang und Blockindex).

        Ein Lauf mit abweichendem Fingerabdruck überschreibt den alten Eintrag, statt ihn
        als Müll liegen zu lassen — deshalb steht der Fingerabdruck neben dem Schlüssel,
        nicht darin.
        """
        payload = json.dumps(ocr_pages_to_payload(pages), ensure_ascii=False)
        with self._lock:
            self._conn.execute(
                "INSERT INTO ocr_chunk_cache "
                "(document_id, chunk_index, fingerprint, page_count, payload) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(document_id, chunk_index) DO UPDATE SET "
                "fingerprint = excluded.fingerprint, page_count = excluded.page_count, "
                "payload = excluded.payload, created_at = datetime('now')",
                (document_id, chunk_index, fingerprint, len(pages), payload),
            )
            self._conn.commit()

    def load_chunk_result(
        self, document_id: int, chunk_index: int, *, fingerprint: str
    ) -> list[OcrPage] | None:
        """Liefert ein bewahrtes Blockergebnis — nur bei passendem Fingerabdruck.

        Eine unlesbare oder nicht deutbare Zeile wird behandelt, als gäbe es sie nicht:
        Ein erneuter Engine-Aufruf kostet Geld, ein falscher Textlayer kostet Vertrauen.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT page_count, payload FROM ocr_chunk_cache "
                "WHERE document_id = ? AND chunk_index = ? AND fingerprint = ?",
                (document_id, chunk_index, fingerprint),
            ).fetchone()
        if row is None:
            return None
        if row["page_count"] <= 0:
            # Eine leere Antwort (HTTP 200, aber ohne Seiten) ist kein gültiger Treffer —
            # sonst heilt kein Wiederholversuch den fehlenden Textlayer je wieder.
            log.warning(
                "Bewahrtes Blockergebnis ohne Seiten (Dokument %s, Block %s) — wird neu erkannt",
                document_id,
                chunk_index,
            )
            return None
        try:
            return ocr_pages_from_payload(json.loads(row["payload"]))
        except (ValueError, TypeError):
            log.warning(
                "Bewahrtes Blockergebnis unbrauchbar (Dokument %s, Block %s) — wird neu erkannt",
                document_id,
                chunk_index,
            )
            return None

    def clear_chunk_results(self, document_id: int) -> int:
        """Gibt alle bewahrten Blockergebnisse eines Vorgangs frei."""
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM ocr_chunk_cache WHERE document_id = ?", (document_id,)
            )
            self._conn.commit()
            return cur.rowcount

    def count_chunk_results(self, document_id: int) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM ocr_chunk_cache WHERE document_id = ?",
                (document_id,),
            ).fetchone()
        return int(row["n"])

    def purge_chunk_results(self, retention_days: int) -> int:
        """Räumt bewahrte Blockergebnisse auf, die niemand mehr braucht.

        Zwei Gründe, beide hier statt verstreut an den Aufrufstellen: Einträge zu Vorgängen,
        die einen Endzustand erreicht haben (es kommt kein Wiederholversuch mehr), und
        Einträge, deren Frist abgelaufen ist (Reste eines abgebrochenen Laufs). Die
        Zustandsprüfung greift unabhängig von der Frist, damit ein Wert <= 0 nur das
        Verfallen abschaltet, nicht das Aufräumen.
        """
        final = (DocStatus.DONE.value, DocStatus.SKIPPED_ERECHNUNG.value, DocStatus.FAILED.value)
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM ocr_chunk_cache WHERE document_id IN ("
                f"  SELECT id FROM documents WHERE status IN ({','.join('?' * len(final))})"
                ")",
                final,
            )
            deleted = cur.rowcount
            if retention_days > 0:
                cutoff = datetime.now(UTC) - timedelta(days=retention_days)
                cur = self._conn.execute(
                    "DELETE FROM ocr_chunk_cache WHERE created_at < ?",
                    (cutoff.strftime("%Y-%m-%d %H:%M:%S"),),
                )
                deleted += cur.rowcount
            self._conn.commit()
        return deleted

    # ---- Web-Sitzungen (AUTH_MODE=paperless) ----------------------------------
    # Lösen bewusst keinen Notifier/SSE-Token aus: Sitzungen sind kein UI-Zustand.

    def create_web_session(self, username: str, now: datetime | None = None) -> str:
        """Legt eine neue Sitzung an und liefert ihre serverseitig erzeugte, zufällige `sid`."""
        stamp = _ts(now)
        sid = secrets.token_urlsafe(32)
        with self._lock:
            self._conn.execute(
                "INSERT INTO web_sessions (id, username, created_at, last_seen_at) "
                "VALUES (?, ?, ?, ?)",
                (sid, username, stamp, stamp),
            )
            self._conn.commit()
        return sid

    def get_web_session(self, sid: str) -> tuple[str, str, str] | None:
        """``(username, created_at, last_seen_at)`` oder ``None``, wenn die `sid` unbekannt ist."""
        with self._lock:
            row = self._conn.execute(
                "SELECT username, created_at, last_seen_at FROM web_sessions WHERE id = ?",
                (sid,),
            ).fetchone()
        if row is None:
            return None
        return row["username"], row["created_at"], row["last_seen_at"]

    def touch_web_session(self, sid: str, now: datetime | None = None) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE web_sessions SET last_seen_at = ? WHERE id = ?", (_ts(now), sid)
            )
            self._conn.commit()

    def delete_web_session(self, sid: str) -> None:
        """Löscht genau diese Sitzung; andere Sitzungen derselben Person bleiben bestehen."""
        with self._lock:
            self._conn.execute("DELETE FROM web_sessions WHERE id = ?", (sid,))
            self._conn.commit()

    def purge_web_sessions(
        self,
        now: datetime | None = None,
        idle: timedelta = WEB_SESSION_IDLE,
        absolute: timedelta = WEB_SESSION_ABSOLUTE,
    ) -> int:
        """Entfernt Sitzungen mit Leerlauf über `idle` oder Alter über `absolute`."""
        current = now or datetime.now(UTC)
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM web_sessions WHERE last_seen_at < ? OR created_at < ?",
                (_ts(current - idle), _ts(current - absolute)),
            )
            self._conn.commit()
            return cur.rowcount

    # ---- events ----------------------------------------------------------

    def add_event(
        self, document_id: int, event_type: EventType, message: str | None = None
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO document_events (document_id, event_type, message) VALUES (?, ?, ?)",
                (document_id, event_type.value, message),
            )
            self._conn.commit()
        self._notify(document_id)

    def list_events(self, document_id: int) -> list[dict[str, object]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, document_id, timestamp, event_type, message "
                "FROM document_events WHERE document_id = ? ORDER BY id ASC",
                (document_id,),
            ).fetchall()
        # ``timestamp`` kommt als SQLite-Text ("YYYY-MM-DD HH:MM:SS", UTC ohne tz-Info).
        # Ungeparst ist er nicht formatierbar (``fmt_dt`` erwartet ein datetime) und wuerde
        # ausserdem in UTC angezeigt, waehrend die uebrige App Ortszeit zeigt. Jeder andere
        # Zeitstempel im Repository laeuft ebenfalls durch _parse_dt.
        return [dict(r) | {"timestamp": _parse_dt(r["timestamp"])} for r in rows]

    # ---- paperless_invoices (entkoppeltes GiroCode/SevDesk-Feature) ------

    def upsert_invoice(
        self,
        *,
        paperless_id: int,
        title: str | None,
        correspondent: str | None | _Unset,
        document_date: str | None = None,
        recipient_label: str | None | _Unset = _UNSET,
        paperless_voucher_ref: str | None | _Unset = _UNSET,
    ) -> int:
        """Legt eine Rechnung an bzw. aktualisiert Titel/Korrespondent/Datum + Änderungszeitpunkt.

        Bereits ermittelte Zahldaten und der Export-/Bezahlt-Status bleiben unangetastet.

        ``recipient_label`` und ``paperless_voucher_ref`` spiegeln Paperless-Felder: Wird ein
        Wert übergeben, ersetzt er den lokalen — ``None`` heißt „in Paperless leer“ und setzt
        die Spalte auf NULL. Wird das Argument weggelassen, bleibt die Spalte unangetastet
        (bestehende Aufrufer, die die Felder nicht kennen, löschen so nichts). Dasselbe gilt
        für ``correspondent=_UNSET`` („Name nicht ermittelbar“); ``None`` leert das Feld.

        Geschrieben wird nur, wenn die Rechnung neu ist oder sich eine übergebene Angabe
        (in der gespeicherten Form) unterscheidet. Eine unveränderte Rechnung löst weder einen
        Schreibzugriff noch ein Live-Signal aus und lässt ``last_synced_at`` („zuletzt
        geändert“) stehen.
        """
        row = InvoiceUpsert(
            paperless_id=paperless_id,
            title=title,
            correspondent=correspondent,
            document_date=document_date,
            recipient_label=recipient_label,
            paperless_voucher_ref=paperless_voucher_ref,
        )
        with self._lock:
            try:
                outcome = self._upsert_invoice_locked(row, _ts())
                if outcome.result is not UpsertResult.UNCHANGED:
                    self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
        if outcome.result is not UpsertResult.UNCHANGED:
            self._notify_invoice(outcome.invoice_id)
        return outcome.invoice_id

    def upsert_invoices(self, rows: list[InvoiceUpsert]) -> dict[int, InvoiceUpsertOutcome]:
        """Gesammeltes ``upsert_invoice``: alle Änderungen in EINER Transaktion, ein Commit.

        Dieselbe Vergleichslogik wie ``upsert_invoice``. Die Live-Signale (``inv:<id>``)
        gehen erst nach dem Commit und nur für neue bzw. geänderte Rechnungen raus. Der Lock
        wird nur für die (rein synchrone) Schreibphase gehalten, nie über ein ``await``.
        Rückgabe je ``paperless_id``: Rechnungs-ID, Ergebnis und Stand vor dem Schreiben.
        """
        if not rows:
            return {}
        stamp = _ts()
        outcomes: dict[int, InvoiceUpsertOutcome] = {}
        with self._lock:
            try:
                for row in rows:
                    # Doppelte paperless_id (z. B. verschobene Seiten beim Paginieren):
                    # das erste Ergebnis gilt, sonst überschriebe „unverändert“ ein „neu“.
                    if row.paperless_id in outcomes:
                        continue
                    outcomes[row.paperless_id] = self._upsert_invoice_locked(row, stamp)
                if any(o.result is not UpsertResult.UNCHANGED for o in outcomes.values()):
                    self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
        for outcome in outcomes.values():
            if outcome.result is not UpsertResult.UNCHANGED:
                self._notify_invoice(outcome.invoice_id)
        return outcomes

    def _upsert_invoice_locked(self, row: InvoiceUpsert, stamp: str) -> InvoiceUpsertOutcome:
        """Vergleichen und ggf. schreiben — ohne Commit; der Aufrufer hält ``self._lock``."""
        values: dict[str, object] = {
            "title": row.title,
            "document_date": _normalize_doc_date(row.document_date),
        }
        if not isinstance(row.correspondent, _Unset):
            values["correspondent"] = row.correspondent
        for name, value in (
            ("recipient_label", row.recipient_label),
            ("paperless_voucher_ref", row.paperless_voucher_ref),
        ):
            if not isinstance(value, _Unset):
                # Leerer Text und None bedeuten beide „kein Wert“.
                values[name] = value or None
        existing = self._conn.execute(
            f"SELECT {_INVOICE_COLUMNS} FROM paperless_invoices WHERE paperless_id = ?",
            (row.paperless_id,),
        ).fetchone()
        if existing is not None:
            before = _parse_invoice(existing)
            if all(existing[name] == value for name, value in values.items()):
                return InvoiceUpsertOutcome(before.id, UpsertResult.UNCHANGED, before)
            assignments = ", ".join(f"{name} = ?" for name in values)
            self._conn.execute(
                f"UPDATE paperless_invoices SET {assignments}, last_synced_at = ? "
                "WHERE paperless_id = ?",
                [*values.values(), stamp, row.paperless_id],
            )
            return InvoiceUpsertOutcome(before.id, UpsertResult.CHANGED, before)
        columns = ["paperless_id", *values, "last_synced_at"]
        cur = self._conn.execute(
            f"INSERT INTO paperless_invoices ({', '.join(columns)}) "
            f"VALUES ({', '.join('?' for _ in columns)})",
            [row.paperless_id, *values.values(), stamp],
        )
        return InvoiceUpsertOutcome(int(cur.lastrowid), UpsertResult.NEW, None)

    def get_invoice(self, invoice_id: int) -> PaperlessInvoice | None:
        with self._lock:
            row = self._conn.execute(
                f"SELECT {_INVOICE_COLUMNS} FROM paperless_invoices WHERE id = ?", (invoice_id,)
            ).fetchone()
        return _parse_invoice(row) if row else None

    def get_invoice_by_paperless(self, paperless_id: int) -> PaperlessInvoice | None:
        with self._lock:
            row = self._conn.execute(
                f"SELECT {_INVOICE_COLUMNS} FROM paperless_invoices WHERE paperless_id = ?",
                (paperless_id,),
            ).fetchone()
        return _parse_invoice(row) if row else None

    # Sortierbare Spalten der Rechnungsliste → SQL-Ausdruck (Whitelist gegen SQL-Injection).
    INVOICE_SORT_COLUMNS = {
        "date": "document_date",
        "title": "title",
        "correspondent": "correspondent",
        "amount": "amount",
        "giro": "giro_status",
        "sevdesk": "sevdesk_status",
        "paid": "paid",
    }

    def list_invoices(
        self,
        *,
        sevdesk_status: SevdeskStatus | None = None,
        search: str | None = None,
        sort: str | None = None,
        descending: bool = True,
        limit: int = 200,
        offset: int = 0,
    ) -> list[PaperlessInvoice]:
        clauses: list[str] = []
        params: list[object] = []
        if sevdesk_status:
            clauses.append("sevdesk_status = ?")
            params.append(sevdesk_status.value)
        if search:
            clauses.append("(title LIKE ? OR correspondent LIKE ?)")
            params.extend([f"%{search}%", f"%{search}%"])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        column = self.INVOICE_SORT_COLUMNS.get(sort or "", "document_date")
        order_dir = "DESC" if descending else "ASC"
        # Eindeutige Sekundärsortierung über id, damit die Reihenfolge stabil bleibt.
        order_by = f"ORDER BY {column} {order_dir}, id DESC"
        params.extend([limit, offset])
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {_INVOICE_COLUMNS} FROM paperless_invoices {where} "
                f"{order_by} LIMIT ? OFFSET ?",
                params,
            ).fetchall()
        return [_parse_invoice(r) for r in rows]

    def update_invoice(self, invoice_id: int, **fields: object) -> None:
        if not fields:
            return
        clean = {k: (v.value if hasattr(v, "value") else v) for k, v in fields.items()}
        assignments = ", ".join(f"{k} = ?" for k in clean)
        with self._lock:
            self._conn.execute(
                f"UPDATE paperless_invoices SET {assignments} WHERE id = ?",
                [*clean.values(), invoice_id],
            )
            self._conn.commit()
        self._notify_invoice(invoice_id)

    def set_giro_data(
        self,
        invoice_id: int,
        *,
        creditor_name: str | None,
        iban: str | None,
        bic: str | None,
        amount: float | None,
        currency: str,
        purpose: str | None,
        source: str,
        giro_status: GiroStatus,
    ) -> None:
        self.update_invoice(
            invoice_id,
            creditor_name=creditor_name,
            iban=iban,
            bic=bic,
            amount=amount,
            currency=currency,
            purpose=purpose,
            source=source,
            giro_status=giro_status,
        )

    def claim_for_export(self, invoice_id: int) -> bool:
        """Beansprucht eine Rechnung atomar für den SevDesk-Export.

        Setzt den Status nur dann auf ``exporting``, wenn er nicht bereits ``exported``,
        ``exporting`` oder ``uncertain`` ist. Liefert ``True``, wenn der Claim gewonnen wurde —
        verhindert Doppel-Belege bei gleichzeitigen Export-Aufrufen (Race zwischen UI-Klick und
        Sync) sowie automatische Wiederholung mehrdeutig fehlgeschlagener Exporte.
        """
        with self._lock:
            cur = self._conn.execute(
                "UPDATE paperless_invoices SET sevdesk_status = ? "
                "WHERE id = ? AND sevdesk_status NOT IN (?, ?, ?)",
                (
                    SevdeskStatus.EXPORTING.value,
                    invoice_id,
                    SevdeskStatus.EXPORTED.value,
                    SevdeskStatus.EXPORTING.value,
                    SevdeskStatus.UNCERTAIN.value,
                ),
            )
            self._conn.commit()
            claimed = cur.rowcount == 1
        if claimed:
            self._notify_invoice(invoice_id)
        return claimed

    def reset_stale_exports(self) -> int:
        """Bereinigt beim Start verwaiste ``exporting``-Claims.

        Stirbt der Prozess mitten im Export, bliebe der Status auf ``exporting`` —
        ``claim_for_export`` schließt diesen Wert dauerhaft aus, die Rechnung wäre also
        nie wieder exportierbar. ``uncertain`` ist hier korrekt, weil unklar ist, ob bereits
        ein Beleg angelegt wurde: kein Auto-Retry, sondern manuelle Prüfung in SevDesk.
        Liefert die Anzahl der zurückgesetzten Rechnungen.
        """
        with self._lock:
            cur = self._conn.execute(
                "UPDATE paperless_invoices SET sevdesk_status = ?, error_message = ? "
                "WHERE sevdesk_status = ?",
                (
                    SevdeskStatus.UNCERTAIN.value,
                    "Export wurde durch einen Neustart unterbrochen — in SevDesk prüfen, "
                    "ob der Beleg existiert, bevor erneut exportiert wird.",
                    SevdeskStatus.EXPORTING.value,
                ),
            )
            self._conn.commit()
            return cur.rowcount

    def set_sevdesk_status(
        self,
        invoice_id: int,
        status: SevdeskStatus,
        *,
        voucher_id: str | None = None,
        error_message: str | None = None,
    ) -> None:
        fields: dict[str, object] = {"sevdesk_status": status, "error_message": error_message}
        if status != SevdeskStatus.REVIEW:
            # Der Prüfgrund gehört nur zum Status `review`.
            fields["review_reason"] = None
        if voucher_id is not None:
            fields["sevdesk_voucher_id"] = voucher_id
        if status == SevdeskStatus.EXPORTED:
            fields["exported_at"] = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        self.update_invoice(invoice_id, **fields)

    def set_paid(self, invoice_id: int, paid: bool) -> None:
        self.update_invoice(invoice_id, paid=1 if paid else 0)

    def mark_written_back(self, invoice_id: int) -> None:
        self.update_invoice(
            invoice_id,
            written_back_at=datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"),
        )

    def add_invoice_event(
        self, invoice_id: int, event_type: InvoiceEventType, message: str | None = None
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO invoice_events (invoice_id, event_type, message) VALUES (?, ?, ?)",
                (invoice_id, event_type.value, message),
            )
            self._conn.commit()
        self._notify_invoice(invoice_id)

    def list_invoice_events(self, invoice_id: int) -> list[dict[str, object]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, invoice_id, timestamp, event_type, message "
                "FROM invoice_events WHERE invoice_id = ? ORDER BY id ASC",
                (invoice_id,),
            ).fetchall()
        # Wie bei list_events: SQLite liefert den Zeitstempel als Text (UTC, ohne
        # tz-Info). Ungeparst waere er nicht formatierbar und stuende in UTC da.
        return [dict(r) | {"timestamp": _parse_dt(r["timestamp"])} for r in rows]

    # ---- document_recipients (KI-Empfänger-Vorschlag-Cache) --------------

    @staticmethod
    def _parse_recipient_cache(row: sqlite3.Row) -> RecipientCache:
        return RecipientCache(
            paperless_id=row["paperless_id"],
            suggested_label=row["suggested_label"],
            confidence=row["confidence"],
            reasoning=row["reasoning"],
            status=RecipientStatus(row["status"]),
            updated_at=_parse_dt(row["updated_at"]),
            it_probability=row["it_probability"],
        )

    def get_recipient_cache(self, paperless_id: int) -> RecipientCache | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT paperless_id, suggested_label, confidence, reasoning, status, updated_at, "
                "it_probability "
                "FROM document_recipients WHERE paperless_id = ?",
                (paperless_id,),
            ).fetchone()
        return self._parse_recipient_cache(row) if row else None

    def get_recipient_caches(self, paperless_ids: list[int]) -> dict[int, RecipientCache]:
        """Lädt mehrere Cache-Einträge auf einmal (für die Übersicht)."""
        if not paperless_ids:
            return {}
        placeholders = ",".join("?" for _ in paperless_ids)
        with self._lock:
            rows = self._conn.execute(
                "SELECT paperless_id, suggested_label, confidence, reasoning, status, updated_at, "
                "it_probability "
                f"FROM document_recipients WHERE paperless_id IN ({placeholders})",
                paperless_ids,
            ).fetchall()
        return {row["paperless_id"]: self._parse_recipient_cache(row) for row in rows}

    def set_recipient_cache(
        self,
        paperless_id: int,
        *,
        suggested_label: str | None,
        confidence: float | None,
        reasoning: str | None,
        status: RecipientStatus,
        it_probability: float | None | _Unset = _UNSET,
        notify: bool = True,
    ) -> None:
        """``notify=False`` unterdrückt das einzelne ``rec:<id>``-SSE-Ereignis.

        Genutzt vom KI-Batch-Lauf: Dort meldet das gedrosselte ``notify_batch()``
        ohnehin den Fortschritt — ein zusätzliches ungedrosseltes Ereignis pro Dokument
        würde die Drossel wirkungslos machen.

        ``it_probability``: ``None`` setzt „nicht eingeschätzt“ (NULL); wird das Argument
        weggelassen, bleibt ein vorhandener Wert erhalten (z. B. bei
        ``mark_recipient_applied``, das nur den Review-Status ändert).
        """
        now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        columns = ["paperless_id", "suggested_label", "confidence", "reasoning", "status",
                   "updated_at"]
        values: list[object] = [paperless_id, suggested_label, confidence, reasoning,
                                status.value, now]
        updates = [
            "suggested_label=excluded.suggested_label",
            "confidence=excluded.confidence",
            "reasoning=excluded.reasoning",
            "status=excluded.status",
            "updated_at=excluded.updated_at",
        ]
        if not isinstance(it_probability, _Unset):
            columns.append("it_probability")
            values.append(it_probability)
            updates.append("it_probability=excluded.it_probability")
        placeholders = ", ".join("?" for _ in columns)
        with self._lock:
            self._conn.execute(
                f"INSERT INTO document_recipients ({', '.join(columns)}) "
                f"VALUES ({placeholders}) "
                f"ON CONFLICT(paperless_id) DO UPDATE SET {', '.join(updates)}",
                values,
            )
            self._conn.commit()
        if notify:
            self.notify_recipient(paperless_id)

    def mark_recipient_applied(self, paperless_id: int, *, notify: bool = True) -> None:
        self.set_recipient_cache(
            paperless_id,
            suggested_label=None,
            confidence=None,
            reasoning=None,
            status=RecipientStatus.APPLIED,
            notify=notify,
        )

    # ---- SevDesk-Belege (lokaler Abzug) ----------------------------------

    _VOUCHER_UPSERT = (
        "INSERT INTO sevdesk_vouchers (voucher_id, voucher_date, supplier_name, sum_gross, "
        "currency, description, status, last_seen_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(voucher_id) DO UPDATE SET voucher_date=excluded.voucher_date, "
        "supplier_name=excluded.supplier_name, sum_gross=excluded.sum_gross, "
        "currency=excluded.currency, description=excluded.description, "
        "status=excluded.status, last_seen_at=excluded.last_seen_at"
    )

    @staticmethod
    def _voucher_params(voucher: SevdeskVoucher, now: str) -> tuple[object, ...]:
        return (
            voucher.voucher_id,
            voucher.voucher_date,
            voucher.supplier_name,
            voucher.sum_gross,
            voucher.currency,
            voucher.description,
            voucher.status,
            now,
        )

    def replace_vouchers(self, vouchers: list[SevdeskVoucher], now: datetime | None = None) -> int:
        """Ersetzt den Belegabzug in EINER Transaktion: Upsert aller gelieferten Belege und
        Löschen aller nicht gelieferten IDs. Eine leere Liste leert den Abzug.

        Nur mit einem vollständig durchgelaufenen Abruf aufrufen — bei einem Abbruch darf der
        Abzug nicht angefasst werden (der Aufrufer ruft dann gar nicht auf). Scheitert hier
        etwas, wird zurückgerollt und der alte Stand bleibt. Liefert die Zahl gelöschter Belege.
        """
        stamp = _ts(now)
        delivered = {v.voucher_id for v in vouchers}
        with self._lock:
            try:
                existing = {
                    r["voucher_id"]
                    for r in self._conn.execute("SELECT voucher_id FROM sevdesk_vouchers")
                }
                self._conn.executemany(
                    self._VOUCHER_UPSERT, [self._voucher_params(v, stamp) for v in vouchers]
                )
                stale = sorted(existing - delivered)
                self._conn.executemany(
                    "DELETE FROM sevdesk_vouchers WHERE voucher_id = ?", [(i,) for i in stale]
                )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
        return len(stale)

    def upsert_voucher(self, voucher: SevdeskVoucher, now: datetime | None = None) -> None:
        """Übernimmt einen einzelnen Beleg (z. B. direkt nach einem Export) in den Abzug."""
        with self._lock:
            self._conn.execute(self._VOUCHER_UPSERT, self._voucher_params(voucher, _ts(now)))
            self._conn.commit()

    def list_vouchers(self) -> list[SevdeskVoucher]:
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {_VOUCHER_COLUMNS} FROM sevdesk_vouchers "
                "ORDER BY voucher_date DESC, voucher_id ASC"
            ).fetchall()
        return [_parse_voucher(r) for r in rows]

    def get_voucher(self, voucher_id: str) -> SevdeskVoucher | None:
        with self._lock:
            row = self._conn.execute(
                f"SELECT {_VOUCHER_COLUMNS} FROM sevdesk_vouchers WHERE voucher_id = ?",
                (voucher_id,),
            ).fetchone()
        return _parse_voucher(row) if row else None

    # ---- Zustand des Belegabrufs ------------------------------------------

    def get_sevdesk_sync_state(self) -> SevdeskSyncState:
        """Stand des letzten Belegabrufs; ohne bisherigen Abruf alles ``None``."""
        with self._lock:
            row = self._conn.execute(
                "SELECT last_success_at, last_error, last_error_at FROM sevdesk_sync_state "
                "WHERE id = 1"
            ).fetchone()
        if row is None:
            return SevdeskSyncState()
        return SevdeskSyncState(
            last_success_at=_parse_dt(row["last_success_at"]),
            last_error=row["last_error"],
            last_error_at=_parse_dt(row["last_error_at"]),
        )

    def set_sevdesk_sync_success(self, now: datetime | None = None) -> None:
        """Vermerkt einen erfolgreichen Abruf: setzt ``last_success_at`` und LEERT den
        Fehler (``last_error``/``last_error_at``) — ein älterer Fehler wäre nach einem
        Erfolg nur irreführend; die Übersicht zeigt einen Fehlerhinweis nur, solange der
        letzte Abruf scheiterte."""
        with self._lock:
            self._conn.execute(
                "INSERT INTO sevdesk_sync_state (id, last_success_at, last_error, last_error_at) "
                "VALUES (1, ?, NULL, NULL) ON CONFLICT(id) DO UPDATE SET "
                "last_success_at=excluded.last_success_at, last_error=NULL, last_error_at=NULL",
                (_ts(now),),
            )
            self._conn.commit()

    def set_sevdesk_sync_error(self, message: str, now: datetime | None = None) -> None:
        """Vermerkt einen gescheiterten Abruf; ``last_success_at`` bleibt stehen."""
        with self._lock:
            self._conn.execute(
                "INSERT INTO sevdesk_sync_state (id, last_error, last_error_at) "
                "VALUES (1, ?, ?) ON CONFLICT(id) DO UPDATE SET "
                "last_error=excluded.last_error, last_error_at=excluded.last_error_at",
                (message, _ts(now)),
            )
            self._conn.commit()

    # ---- Treffer Rechnung <-> Beleg ---------------------------------------

    def list_matches(self, invoice_ids: list[int] | None = None) -> list[InvoiceVoucherMatch]:
        """Alle Treffer (``None``) oder nur die der genannten Rechnungen."""
        if invoice_ids is not None and not invoice_ids:
            return []
        sql = (
            "SELECT invoice_id, voucher_id, kind, score, decided_at, created_at "
            "FROM invoice_voucher_matches"
        )
        params: list[object] = []
        if invoice_ids is not None:
            sql += f" WHERE invoice_id IN ({','.join('?' for _ in invoice_ids)})"
            params.extend(invoice_ids)
        sql += " ORDER BY invoice_id ASC, score DESC, voucher_id ASC"
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [_parse_match(r) for r in rows]

    def replace_auto_matches(self, matches: list[InvoiceVoucherMatch]) -> None:
        """Ersetzt alle automatischen Treffer (``id``, ``similar``) in einer Transaktion.

        ``confirmed``/``rejected`` bleiben unangetastet; ein automatischer Treffer für ein
        Paar, für das bereits eine Entscheidung vorliegt, wird übersprungen (die Entscheidung
        gewinnt). Ausnahme: ein ``id``-Treffer verdrängt ein früheres ``rejected`` desselben
        Paars — die Beleg-ID ist sicher, eine frühere „anderer Beleg“-Entscheidung über ein
        bloß ähnliches Paar darf sie nicht unterdrücken. Bei doppelten Paaren in ``matches``
        gilt der erste — ``id`` also vor ``similar`` übergeben.
        """
        for m in matches:
            if m.kind not in (MatchKind.ID, MatchKind.SIMILAR):
                raise ValueError(f"replace_auto_matches nimmt nur id/similar, nicht {m.kind!r}")
        with self._lock:
            try:
                self._conn.execute(
                    "DELETE FROM invoice_voucher_matches WHERE kind IN (?, ?)",
                    (MatchKind.ID.value, MatchKind.SIMILAR.value),
                )
                self._conn.executemany(
                    "DELETE FROM invoice_voucher_matches "
                    "WHERE invoice_id = ? AND voucher_id = ? AND kind = ?",
                    [
                        (m.invoice_id, m.voucher_id, MatchKind.REJECTED.value)
                        for m in matches
                        if m.kind == MatchKind.ID
                    ],
                )
                self._conn.executemany(
                    "INSERT OR IGNORE INTO invoice_voucher_matches "
                    "(invoice_id, voucher_id, kind, score) VALUES (?, ?, ?, ?)",
                    [(m.invoice_id, m.voucher_id, m.kind.value, m.score) for m in matches],
                )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def decide_match(self, invoice_id: int, voucher_id: str, confirmed: bool) -> bool:
        """Hält die Entscheidung des Anwenders fest (``confirmed``/``rejected``).

        Der Score eines vorhandenen Treffers bleibt erhalten. Ein sicherer ``id``-Treffer
        ist nicht entscheidbar: dann geschieht nichts und die Rückgabe ist ``False``.
        """
        kind = MatchKind.CONFIRMED if confirmed else MatchKind.REJECTED
        with self._lock:
            existing = self._conn.execute(
                "SELECT kind FROM invoice_voucher_matches WHERE invoice_id = ? AND voucher_id = ?",
                (invoice_id, voucher_id),
            ).fetchone()
            if existing is not None and existing["kind"] == MatchKind.ID.value:
                return False
            self._conn.execute(
                "INSERT INTO invoice_voucher_matches (invoice_id, voucher_id, kind, decided_at) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(invoice_id, voucher_id) DO UPDATE SET "
                "kind=excluded.kind, decided_at=excluded.decided_at",
                (invoice_id, voucher_id, kind.value, _ts()),
            )
            self._conn.commit()
        self._notify_invoice(invoice_id)
        return True

    def vouchers_without_invoice(self) -> list[SevdeskVoucher]:
        """Belege ohne ``id``-/``similar``-/``confirmed``-Treffer (Vorbereitung für den späteren
        Abgleich „SevDesk-Belege ohne Paperless-Dokument“). ``rejected`` zählt nicht als Treffer."""
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {_VOUCHER_COLUMNS} FROM sevdesk_vouchers v WHERE NOT EXISTS ("
                "SELECT 1 FROM invoice_voucher_matches m WHERE m.voucher_id = v.voucher_id "
                "AND m.kind IN (?, ?, ?)) ORDER BY voucher_date DESC, voucher_id ASC",
                (MatchKind.ID.value, MatchKind.SIMILAR.value, MatchKind.CONFIRMED.value),
            ).fetchall()
        return [_parse_voucher(r) for r in rows]

    # ---- Einstufung: Historie je Korrespondent ----------------------------

    def correspondent_context_history(
        self, context_label: str
    ) -> dict[str, CorrespondentHistory]:
        """Entschiedene Rechnungen je Korrespondent, mit einer Abfrage für alle.

        Entschieden ist eine Rechnung, wenn ``recipient_label`` gesetzt ist (IT-Consulting,
        wenn gleich ``context_label``, sonst anderer Empfänger) oder — ohne Empfänger — wenn
        ihr Status ``exported`` ist bzw. ein ``confirmed``-Treffer besteht (zählt als
        IT-Consulting). Rechnungen ohne Korrespondent bleiben außen vor. Der Aufrufer
        schließt die gerade bewertete Rechnung über die ID-Mengen aus.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT p.id, p.correspondent, p.recipient_label, "
                "(p.sevdesk_status = ? OR EXISTS (SELECT 1 FROM invoice_voucher_matches m "
                "WHERE m.invoice_id = p.id AND m.kind = ?)) AS exported_or_confirmed "
                "FROM paperless_invoices p "
                "WHERE p.correspondent IS NOT NULL AND p.correspondent != ''",
                (SevdeskStatus.EXPORTED.value, MatchKind.CONFIRMED.value),
            ).fetchall()
        it_ids: dict[str, set[int]] = {}
        other_ids: dict[str, set[int]] = {}
        for r in rows:
            label = r["recipient_label"]
            if label:
                is_it = same_label(label, context_label)
            elif r["exported_or_confirmed"]:
                is_it = True
            else:
                continue
            (it_ids if is_it else other_ids).setdefault(r["correspondent"], set()).add(r["id"])
        return {
            name: CorrespondentHistory(
                it_ids=frozenset(it_ids.get(name, ())),
                other_ids=frozenset(other_ids.get(name, ())),
            )
            for name in it_ids.keys() | other_ids.keys()
        }

    # ---- Prüffall ---------------------------------------------------------

    def set_review(self, invoice_id: int, reason: str) -> bool:
        """Setzt die Rechnung auf ``review`` mit Grund. Laufende oder abgeschlossene Exporte
        (``exported``/``exporting``/``uncertain``) werden nicht überschrieben; Rückgabe
        ``False``, wenn nichts geändert wurde."""
        return self._set_status_guarded(invoice_id, SevdeskStatus.REVIEW, reason)

    def dismiss(self, invoice_id: int) -> bool:
        """Verwirft einen Prüffall (``dismissed``, Grund geleert). Gleiche Schutzliste wie
        ``set_review``; ``dismissed`` wird vom Tag-Weg nicht erneut vorgemerkt."""
        return self._set_status_guarded(invoice_id, SevdeskStatus.DISMISSED, None)

    def _set_status_guarded(
        self, invoice_id: int, status: SevdeskStatus, reason: str | None
    ) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE paperless_invoices SET sevdesk_status = ?, review_reason = ? "
                "WHERE id = ? AND sevdesk_status NOT IN (?, ?, ?)",
                (status.value, reason, invoice_id, *_EXPORT_LOCKED_STATUSES),
            )
            self._conn.commit()
            changed = cur.rowcount == 1
        if changed:
            self._notify_invoice(invoice_id)
        return changed
