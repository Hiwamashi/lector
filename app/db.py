"""SQLite-Anbindung im WAL-Modus inkl. Schema-Initialisierung (siehe PRD §4.3)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    original_filename TEXT    NOT NULL,
    source_path       TEXT    NOT NULL,
    file_hash         TEXT,
    status            TEXT    NOT NULL,
    doc_type          TEXT,
    ocr_engine        TEXT,
    total_pages       INTEGER,
    processed_pages   INTEGER NOT NULL DEFAULT 0,
    attempt_count     INTEGER NOT NULL DEFAULT 0,
    next_retry_at     TEXT,
    error_message     TEXT,
    output_path       TEXT,
    created_at        TEXT    NOT NULL DEFAULT (datetime('now')),
    started_at        TEXT,
    finished_at       TEXT
);

CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);
CREATE INDEX IF NOT EXISTS idx_documents_next_retry ON documents(next_retry_at);

CREATE TABLE IF NOT EXISTS document_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    timestamp   TEXT    NOT NULL DEFAULT (datetime('now')),
    event_type  TEXT    NOT NULL,
    message     TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_document ON document_events(document_id);

-- ----------------------------------------------------------------------------
-- Entkoppeltes Zusatz-Feature: aus Paperless gelesene Rechnungen (Dokumententyp),
-- daraus erzeugte GiroCode-Zahldaten und SevDesk-Export-Status.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS paperless_invoices (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    paperless_id      INTEGER NOT NULL UNIQUE,
    title             TEXT,
    correspondent     TEXT,
    creditor_name     TEXT,
    iban              TEXT,
    bic               TEXT,
    amount            REAL,
    currency          TEXT    NOT NULL DEFAULT 'EUR',
    purpose           TEXT,
    source            TEXT,
    giro_status       TEXT    NOT NULL DEFAULT 'none',
    sevdesk_status    TEXT    NOT NULL DEFAULT 'none',
    sevdesk_voucher_id TEXT,
    paid              INTEGER NOT NULL DEFAULT 0,
    exported_at       TEXT,
    written_back_at   TEXT,
    last_synced_at    TEXT,
    error_message     TEXT,
    created_at        TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_invoices_paperless ON paperless_invoices(paperless_id);
CREATE INDEX IF NOT EXISTS idx_invoices_sevdesk ON paperless_invoices(sevdesk_status);

CREATE TABLE IF NOT EXISTS invoice_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id  INTEGER NOT NULL REFERENCES paperless_invoices(id) ON DELETE CASCADE,
    timestamp   TEXT    NOT NULL DEFAULT (datetime('now')),
    event_type  TEXT    NOT NULL,
    message     TEXT
);

CREATE INDEX IF NOT EXISTS idx_invoice_events_invoice ON invoice_events(invoice_id);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    """Öffnet eine Verbindung mit aktiviertem WAL-Modus und Foreign-Keys."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()
