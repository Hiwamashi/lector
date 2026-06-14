"""Repository-Schicht: CRUD für documents/document_events, Event-Logging, Fortschritt.

Threadsicher (eine geteilte Verbindung + Lock), da der Worker in einem Thread-Pool läuft,
während FastAPI-Handler asynchron auf dieselbe DB zugreifen. Bei jeder Statusänderung wird
optional ein Notifier aufgerufen, damit die SSE-Schicht Live-Updates verteilen kann.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .db import connect, init_db
from .models import DocStatus, DocType, Document, EventType

_DOC_COLUMNS = (
    "id, original_filename, source_path, file_hash, status, doc_type, ocr_engine, "
    "total_pages, processed_pages, attempt_count, next_retry_at, error_message, "
    "output_path, created_at, started_at, finished_at"
)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    # SQLite datetime('now') liefert "YYYY-MM-DD HH:MM:SS" (UTC, ohne tz-Info)
    try:
        return datetime.fromisoformat(value).replace(tzinfo=UTC)
    except ValueError:
        return None


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
        created_at=_parse_dt(row["created_at"]),
        started_at=_parse_dt(row["started_at"]),
        finished_at=_parse_dt(row["finished_at"]),
    )


class Repository:
    def __init__(self, db_path: Path, notifier: Callable[[int], None] | None = None) -> None:
        self._conn = connect(db_path)
        init_db(self._conn)
        self._lock = threading.Lock()
        self._notifier = notifier

    def set_notifier(self, notifier: Callable[[int], None]) -> None:
        self._notifier = notifier

    def _notify(self, document_id: int) -> None:
        if self._notifier:
            try:
                self._notifier(document_id)
            except Exception:
                pass

    def close(self) -> None:
        with self._lock:
            self._conn.close()

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
        limit: int = 200,
        offset: int = 0,
    ) -> list[Document]:
        clauses: list[str] = []
        params: list[object] = []
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
            self._notify(document_id)
            return
        self.update_document(document_id, **fields)

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
        return [dict(r) for r in rows]
