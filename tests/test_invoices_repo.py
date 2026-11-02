import asyncio
import sqlite3

import pytest

from app.config import Settings
from app.models import (
    GiroStatus,
    InvoiceEventType,
    InvoiceVoucherMatch,
    MatchKind,
    RecipientStatus,
    SevdeskStatus,
    SevdeskVoucher,
)
from app.paperless import PaperlessClient
from app.paperless_sync import PaperlessSync
from app.repository import InvoiceUpsert, Repository, UpsertResult


def make_repo(tmp_path):
    return Repository(tmp_path / "lector.db")


def test_upsert_is_idempotent_and_preserves_state(tmp_path):
    repo = make_repo(tmp_path)
    inv_id = repo.upsert_invoice(paperless_id=42, title="Rechnung A", correspondent="Acme")
    repo.set_giro_data(
        inv_id, creditor_name="Acme", iban="DE89370400440532013000", bic=None,
        amount=99.0, currency="EUR", purpose="R-1", source="einvoice",
        giro_status=GiroStatus.READY,
    )
    # Erneuter Sync darf vorhandene Zahldaten nicht überschreiben.
    same_id = repo.upsert_invoice(paperless_id=42, title="Rechnung A (neu)", correspondent="Acme")
    assert same_id == inv_id
    inv = repo.get_invoice(inv_id)
    assert inv.title == "Rechnung A (neu)"
    assert inv.iban == "DE89370400440532013000"
    assert inv.giro_status == GiroStatus.READY


def test_sevdesk_and_paid_status(tmp_path):
    repo = make_repo(tmp_path)
    inv_id = repo.upsert_invoice(paperless_id=7, title="B", correspondent=None)
    repo.set_sevdesk_status(inv_id, SevdeskStatus.EXPORTED, voucher_id="V-100")
    inv = repo.get_invoice(inv_id)
    assert inv.sevdesk_status == SevdeskStatus.EXPORTED
    assert inv.sevdesk_voucher_id == "V-100"
    assert inv.exported_at is not None

    repo.set_paid(inv_id, True)
    assert repo.get_invoice(inv_id).paid is True


def test_list_and_filter_invoices(tmp_path):
    repo = make_repo(tmp_path)
    a = repo.upsert_invoice(paperless_id=1, title="Strom", correspondent="Stadtwerke")
    repo.upsert_invoice(paperless_id=2, title="Wasser", correspondent="Stadtwerke")
    repo.set_sevdesk_status(a, SevdeskStatus.QUEUED)

    assert len(repo.list_invoices()) == 2
    assert len(repo.list_invoices(sevdesk_status=SevdeskStatus.QUEUED)) == 1
    assert len(repo.list_invoices(search="Strom")) == 1


def test_document_date_is_stored_and_updated(tmp_path):
    repo = make_repo(tmp_path)
    inv_id = repo.upsert_invoice(
        paperless_id=3, title="Miete", correspondent=None, document_date="2026-01-15T00:00:00+01:00"
    )
    inv = repo.get_invoice(inv_id)
    assert inv.document_date is not None
    assert (inv.document_date.year, inv.document_date.month, inv.document_date.day) == (2026, 1, 15)

    # Erneuter Sync mit geändertem Datum aktualisiert das Feld.
    repo.upsert_invoice(
        paperless_id=3, title="Miete", correspondent=None, document_date="2026-02-01T00:00:00+01:00"
    )
    assert repo.get_invoice(inv_id).document_date.month == 2


def test_list_invoices_sorting(tmp_path):
    repo = make_repo(tmp_path)
    repo.upsert_invoice(
        paperless_id=1, title="Beta", correspondent=None, document_date="2026-03-01"
    )
    repo.upsert_invoice(
        paperless_id=2, title="Alpha", correspondent=None, document_date="2026-01-01"
    )
    repo.upsert_invoice(
        paperless_id=3, title="Gamma", correspondent=None, document_date="2026-02-01"
    )

    by_title_asc = [i.title for i in repo.list_invoices(sort="title", descending=False)]
    assert by_title_asc == ["Alpha", "Beta", "Gamma"]

    by_date_desc = [i.paperless_id for i in repo.list_invoices(sort="date", descending=True)]
    assert by_date_desc == [1, 3, 2]

    # Unbekannte Sortierspalte fällt sicher auf das Datum zurück (keine SQL-Injection).
    fallback = repo.list_invoices(sort="title); DROP TABLE paperless_invoices;--")
    assert len(fallback) == 3


def test_invoice_events(tmp_path):
    repo = make_repo(tmp_path)
    inv_id = repo.upsert_invoice(paperless_id=9, title="C", correspondent=None)
    repo.add_invoice_event(inv_id, InvoiceEventType.SYNCED, "ok")
    events = repo.list_invoice_events(inv_id)
    assert events[-1]["event_type"] == "synced"
    assert events[-1]["message"] == "ok"
    # Wie bei den Dokument-Ereignissen: SQLite liefert Text. Ungeparst laesst er sich
    # nicht formatieren und wuerde in UTC angezeigt statt in Ortszeit.
    from datetime import datetime

    assert isinstance(events[-1]["timestamp"], datetime)
    assert events[-1]["timestamp"].tzinfo is not None


def test_export_invoice_is_idempotent(tmp_path):
    """Ein bereits exportierter Beleg darf nicht erneut nach SevDesk hochgeladen werden."""
    repo = make_repo(tmp_path)
    settings = Settings(
        FEATURE_SEVDESK_EXPORT="true", SEVDESK_API_TOKEN="t", FEATURE_PAPERLESS_SYNC="false"
    )
    sync = PaperlessSync(settings, repo)

    inv_id = repo.upsert_invoice(paperless_id=5, title="Bereits exportiert", correspondent=None)
    repo.set_sevdesk_status(inv_id, SevdeskStatus.EXPORTED, voucher_id="V-1")

    calls = {"n": 0}

    class _Boom:
        async def __aenter__(self):
            calls["n"] += 1
            raise AssertionError("Bereits exportierter Beleg darf keinen Client öffnen")

        async def __aexit__(self, *exc):
            return False

    sync._sevdesk = lambda: _Boom()  # type: ignore[method-assign]
    sync._paperless = lambda: _Boom()  # type: ignore[method-assign]

    asyncio.run(sync.export_invoice(inv_id))
    assert calls["n"] == 0
    inv = repo.get_invoice(inv_id)
    assert inv.sevdesk_voucher_id == "V-1"


def test_export_invoice_no_double_voucher_under_concurrency(tmp_path):
    """Zwei gleichzeitige Exporte derselben Rechnung dürfen nur EINEN Beleg erzeugen."""
    from app.sevdesk import VoucherResult

    repo = make_repo(tmp_path)
    settings = Settings(
        FEATURE_SEVDESK_EXPORT="true", SEVDESK_API_TOKEN="t", FEATURE_PAPERLESS_SYNC="false"
    )
    sync = PaperlessSync(settings, repo)
    inv_id = repo.upsert_invoice(paperless_id=8, title="X", correspondent=None)
    repo.set_sevdesk_status(inv_id, SevdeskStatus.QUEUED)

    counter = {"n": 0}

    class FakePaper:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def download_original(self, pid):
            await asyncio.sleep(0.01)  # erzwingt Interleaving der Coroutinen
            return (b"%PDF-1.4", "x.pdf")

    class FakeSev:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def upload_temp_file(self, *a, **k):
            await asyncio.sleep(0.01)
            return "temp.pdf"

        async def save_voucher_from_temp(self, *a, **k):
            counter["n"] += 1  # nur der beleg-erzeugende Schritt zählt
            await asyncio.sleep(0.01)
            return VoucherResult(voucher_id="V-9")

    sync._paperless = lambda: FakePaper()  # type: ignore[method-assign]
    sync._sevdesk = lambda: FakeSev()  # type: ignore[method-assign]

    async def run():
        await asyncio.gather(sync.export_invoice(inv_id), sync.export_invoice(inv_id))

    asyncio.run(run())
    assert counter["n"] == 1
    assert repo.get_invoice(inv_id).sevdesk_status == SevdeskStatus.EXPORTED
    assert repo.get_invoice(inv_id).sevdesk_voucher_id == "V-9"


def test_ambiguous_savevoucher_failure_is_not_retryable(tmp_path):
    """Ein mehrdeutiger saveVoucher-Fehler (Transportfehler) darf NICHT auto-retrybar sein."""
    import httpx

    repo = make_repo(tmp_path)
    settings = Settings(
        FEATURE_SEVDESK_EXPORT="true", SEVDESK_API_TOKEN="t", FEATURE_PAPERLESS_SYNC="false"
    )
    sync = PaperlessSync(settings, repo)
    inv_id = repo.upsert_invoice(paperless_id=11, title="Y", correspondent=None)
    repo.set_sevdesk_status(inv_id, SevdeskStatus.QUEUED)

    saves = {"n": 0}

    class FakePaper:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def download_original(self, pid):
            return (b"%PDF-1.4", "y.pdf")

    class FakeSev:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def upload_temp_file(self, *a, **k):
            return "temp.pdf"

        async def save_voucher_from_temp(self, *a, **k):
            saves["n"] += 1
            # Verbindung bricht ab, NACHDEM der Beleg evtl. schon angelegt wurde.
            raise httpx.ReadTimeout("timeout")

    sync._paperless = lambda: FakePaper()  # type: ignore[method-assign]
    sync._sevdesk = lambda: FakeSev()  # type: ignore[method-assign]

    asyncio.run(sync.export_invoice(inv_id))
    assert repo.get_invoice(inv_id).sevdesk_status == SevdeskStatus.UNCERTAIN

    # Erneuter Aufruf darf saveVoucher NICHT erneut auslösen (kein Doppel-Beleg-Risiko).
    asyncio.run(sync.export_invoice(inv_id))
    assert saves["n"] == 1
    assert repo.get_invoice(inv_id).sevdesk_status == SevdeskStatus.UNCERTAIN


def test_rejected_savevoucher_failure_is_retryable(tmp_path):
    """Eine eindeutige Server-Ablehnung (HTTP-Fehler) bleibt retrybar (Status failed)."""
    import httpx

    repo = make_repo(tmp_path)
    settings = Settings(
        FEATURE_SEVDESK_EXPORT="true", SEVDESK_API_TOKEN="t", FEATURE_PAPERLESS_SYNC="false"
    )
    sync = PaperlessSync(settings, repo)
    inv_id = repo.upsert_invoice(paperless_id=12, title="Z", correspondent=None)
    repo.set_sevdesk_status(inv_id, SevdeskStatus.QUEUED)

    class FakePaper:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def download_original(self, pid):
            return (b"%PDF-1.4", "z.pdf")

    class FakeSev:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def upload_temp_file(self, *a, **k):
            return "temp.pdf"

        async def save_voucher_from_temp(self, *a, **k):
            request = httpx.Request("POST", "http://x/saveVoucher")
            response = httpx.Response(400, request=request)
            raise httpx.HTTPStatusError("bad request", request=request, response=response)

    sync._paperless = lambda: FakePaper()  # type: ignore[method-assign]
    sync._sevdesk = lambda: FakeSev()  # type: ignore[method-assign]

    asyncio.run(sync.export_invoice(inv_id))
    inv = repo.get_invoice(inv_id)
    assert inv.sevdesk_status == SevdeskStatus.FAILED
    # failed ist claim-bar → ein Retry ist möglich.
    assert repo.claim_for_export(inv_id) is True


def test_server_error_savevoucher_is_not_retryable(tmp_path):
    """Ein 5xx-Serverfehler ist mehrdeutig (Beleg evtl. angelegt) → uncertain, kein Auto-Retry."""
    import httpx

    repo = make_repo(tmp_path)
    settings = Settings(
        FEATURE_SEVDESK_EXPORT="true", SEVDESK_API_TOKEN="t", FEATURE_PAPERLESS_SYNC="false"
    )
    sync = PaperlessSync(settings, repo)
    inv_id = repo.upsert_invoice(paperless_id=13, title="S", correspondent=None)
    repo.set_sevdesk_status(inv_id, SevdeskStatus.QUEUED)

    saves = {"n": 0}

    class FakePaper:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def download_original(self, pid):
            return (b"%PDF-1.4", "s.pdf")

    class FakeSev:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def upload_temp_file(self, *a, **k):
            return "temp.pdf"

        async def save_voucher_from_temp(self, *a, **k):
            saves["n"] += 1
            request = httpx.Request("POST", "http://x/saveVoucher")
            response = httpx.Response(503, request=request)
            raise httpx.HTTPStatusError("service unavailable", request=request, response=response)

    sync._paperless = lambda: FakePaper()  # type: ignore[method-assign]
    sync._sevdesk = lambda: FakeSev()  # type: ignore[method-assign]

    asyncio.run(sync.export_invoice(inv_id))
    assert repo.get_invoice(inv_id).sevdesk_status == SevdeskStatus.UNCERTAIN
    assert repo.claim_for_export(inv_id) is False  # nicht auto-retrybar

    asyncio.run(sync.export_invoice(inv_id))
    assert saves["n"] == 1  # saveVoucher wurde NICHT erneut aufgerufen


# ---- Korrespondenten-Karte je Lauf statt Einzelabruf je Dokument --------
#
# Produktiv rief `_correspondent_name` für jedes Rechnungsdokument einzeln
# `/api/correspondents/<id>/` auf — bei geteilten Korrespondenten mehrere hundert
# Anfragen je Sync-Lauf. Die folgenden Tests belegen die Anfragenzahl direkt (nicht
# nur das Ergebnis), damit ein späterer Umbau die Einzelabrufe nicht ungesehen
# zurückbringt.


def _corr_doc(doc_id, correspondent_id=173):
    from app.paperless import PaperlessDocument

    return PaperlessDocument(
        id=doc_id, title=f"Rechnung {doc_id}", content="", correspondent_id=correspondent_id,
        document_type_id=1, tag_ids=[], custom_fields=[], original_file_name=None,
    )


class _CorrCountingClient:
    """Stub, der Aufrufe an correspondent_map() und den Einzelabruf mitzählt."""

    def __init__(self, docs, corr_map):
        self._docs = docs
        self._corr_map = corr_map
        self.correspondent_map_calls = 0
        self.single_lookup_calls: list[int] = []

    async def list_documents(self, *, document_type_id=None, tag_ids=None):
        return self._docs

    async def correspondent_map(self):
        self.correspondent_map_calls += 1
        return dict(self._corr_map)

    async def get_correspondent_name(self, correspondent_id):
        self.single_lookup_calls.append(correspondent_id)
        return self._corr_map.get(correspondent_id)

    async def resolve_select_field(self, name):
        return None  # kein Empfänger-Feld: Spiegelung bleibt aus

    @staticmethod
    def select_value(doc, field_id):
        return PaperlessClient.select_value(doc, field_id)


async def test_sync_invoices_resolves_shared_correspondent_from_one_map(tmp_path, monkeypatch):
    """Mehrere Rechnungen mit DEMSELBEN Korrespondenten lösen den Namen ausschließlich
    über die einmal je Lauf gebaute Karte auf — kein Einzelabruf je Dokument."""
    repo = make_repo(tmp_path)
    sync = PaperlessSync(Settings(PAPERLESS_URL="http://x", PAPERLESS_TOKEN="t"), repo)
    # GiroCode-Extraktion ist hier nicht Testgegenstand — isoliert stubben.
    monkeypatch.setattr(sync, "_extract_and_store", lambda *_a, **_k: _noop())

    docs = [_corr_doc(i) for i in range(1, 6)]  # 5 Rechnungen, ein Korrespondent
    client = _CorrCountingClient(docs, {173: "Stadtwerke"})
    corr_map = await client.correspondent_map()
    client.correspondent_map_calls = 0  # nur der eigentliche Lauf soll gezählt werden

    await sync._sync_invoices(client, {"doctype": 1}, corr_map)

    assert client.correspondent_map_calls == 0  # _sync_invoices baut selbst keine Karte
    assert client.single_lookup_calls == []  # alle 5 Treffer kamen aus der Karte
    for doc_id in range(1, 6):
        assert repo.get_invoice_by_paperless(doc_id).correspondent == "Stadtwerke"


async def _noop(*_a, **_k):
    return None


async def test_sync_once_fetches_correspondents_map_exactly_once(tmp_path, monkeypatch):
    """Der entscheidende Test: Ein voller Sync-Lauf (`sync_once`) über mehrere
    Rechnungen mit geteiltem Korrespondenten fragt /api/correspondents/ genau EINMAL
    ab — vormals einmal je Dokument (bei 5 Dokumenten also 5 statt 1 Anfragen)."""
    from contextlib import asynccontextmanager

    class _FullFakeClient(_CorrCountingClient):
        async def resolve_document_type_id(self, name):
            return 1

        async def list_tags(self):
            return []

        async def ensure_tag(self, name):
            return 99

        async def ensure_custom_field(self, name, data_type):
            return 1

    docs = [_corr_doc(i) for i in range(1, 6)]
    client = _FullFakeClient(docs, {173: "Stadtwerke"})

    repo = make_repo(tmp_path)
    settings = Settings(
        PAPERLESS_URL="http://x", PAPERLESS_TOKEN="t", FEATURE_PAPERLESS_SYNC="true"
    )
    sync = PaperlessSync(settings, repo)

    @asynccontextmanager
    async def fake_paperless():
        yield client

    monkeypatch.setattr(sync, "_paperless", fake_paperless)
    monkeypatch.setattr(sync, "_extract_and_store", lambda *_a, **_k: _noop())

    await sync.sync_once()

    assert client.correspondent_map_calls == 1
    assert client.single_lookup_calls == []
    for doc_id in range(1, 6):
        assert repo.get_invoice_by_paperless(doc_id).correspondent == "Stadtwerke"


async def test_sync_once_rebuilds_map_fresh_each_run(tmp_path, monkeypatch):
    """Bindende Bedingung 1: Die Karte ist je Lauf frisch, nicht prozessweit gecacht —
    ein zwischenzeitlich in Paperless umbenannter Korrespondent muss im nächsten Lauf
    sofort ankommen, nicht erst nach einem Neustart."""
    from contextlib import asynccontextmanager

    class _RenamingClient(_CorrCountingClient):
        async def resolve_document_type_id(self, name):
            return 1

        async def list_tags(self):
            return []

        async def ensure_tag(self, name):
            return 99

        async def ensure_custom_field(self, name, data_type):
            return 1

    docs = [_corr_doc(1)]
    client = _RenamingClient(docs, {173: "Alter Name"})

    repo = make_repo(tmp_path)
    settings = Settings(
        PAPERLESS_URL="http://x", PAPERLESS_TOKEN="t", FEATURE_PAPERLESS_SYNC="true"
    )
    sync = PaperlessSync(settings, repo)

    @asynccontextmanager
    async def fake_paperless():
        yield client

    monkeypatch.setattr(sync, "_paperless", fake_paperless)
    monkeypatch.setattr(sync, "_extract_and_store", lambda *_a, **_k: _noop())

    await sync.sync_once()
    assert repo.get_invoice_by_paperless(1).correspondent == "Alter Name"

    # Korrespondent wurde in Paperless zwischen den Läufen umbenannt.
    client._corr_map = {173: "Neuer Name"}
    await sync.sync_once()
    assert repo.get_invoice_by_paperless(1).correspondent == "Neuer Name"
    assert client.correspondent_map_calls == 2  # je Lauf eine frische Karte


async def test_correspondent_name_falls_back_to_single_lookup_for_unmapped_id(tmp_path):
    """Bindende Bedingung 3: Ein Korrespondent, der nach dem Bau der Karte angelegt
    wurde (also nicht in der Karte steht), darf nicht als 'kein Korrespondent'
    verloren gehen — der Einzelabruf greift als Rückfall."""
    repo = make_repo(tmp_path)
    sync = PaperlessSync(Settings(PAPERLESS_URL="http://x", PAPERLESS_TOKEN="t"), repo)
    doc = _corr_doc(1, correspondent_id=999)
    client = _CorrCountingClient([doc], {173: "Stadtwerke"})  # 999 fehlt in der Karte
    corr_map = {173: "Stadtwerke"}

    name = await sync._correspondent_name(client, doc, corr_map)

    assert name is None  # get_correspondent_name liefert hier nichts für 999 zurück
    assert client.single_lookup_calls == [999]  # Rückfall wurde tatsächlich ausgelöst


async def test_correspondent_name_fallback_resolves_name_for_unmapped_id(tmp_path):
    """Gegenprobe: Liefert der Rückfall einen Namen, kommt er auch tatsächlich an."""
    repo = make_repo(tmp_path)
    sync = PaperlessSync(Settings(PAPERLESS_URL="http://x", PAPERLESS_TOKEN="t"), repo)
    doc = _corr_doc(1, correspondent_id=999)
    client = _CorrCountingClient([doc], {173: "Stadtwerke", 999: "Ganz neu"})
    corr_map = {173: "Stadtwerke"}  # 999 absichtlich NICHT in der übergebenen Karte

    name = await sync._correspondent_name(client, doc, corr_map)

    assert name == "Ganz neu"
    assert client.single_lookup_calls == [999]


async def test_single_document_suggestion_path_does_not_fetch_full_map(tmp_path):
    """Bindende Bedingung 2: Der Einzelvorschlagspfad für EIN Dokument darf nicht die
    vollständige Korrespondenten-Karte holen, um einen Namen aufzulösen."""
    repo = make_repo(tmp_path)
    sync = PaperlessSync(Settings(PAPERLESS_URL="http://x", PAPERLESS_TOKEN="t"), repo)
    doc = _corr_doc(1)
    client = _CorrCountingClient([doc], {173: "Stadtwerke"})

    # _correspondent_name ohne übergebene Karte — wie beim Einzelvorschlag (suggest_recipient).
    name = await sync._correspondent_name(client, doc)

    assert name == "Stadtwerke"
    assert client.correspondent_map_calls == 0  # keine vollständige Karte geholt
    assert client.single_lookup_calls == [173]  # stattdessen der gezielte Einzelabruf


def test_reset_stale_exports_recovers_interrupted_claim(tmp_path):
    """Ein durch Neustart verwaister 'exporting'-Claim wäre sonst dauerhaft blockiert."""
    repo = make_repo(tmp_path)
    inv_id = repo.upsert_invoice(paperless_id=99, title="Hängengeblieben", correspondent=None)
    # Claim gewinnen, dann „Absturz" simulieren: Status bleibt auf exporting.
    assert repo.claim_for_export(inv_id) is True
    assert repo.get_invoice(inv_id).sevdesk_status == SevdeskStatus.EXPORTING
    assert repo.claim_for_export(inv_id) is False  # exporting ist sonst nicht claim-bar

    assert repo.reset_stale_exports() == 1
    inv = repo.get_invoice(inv_id)
    assert inv.sevdesk_status == SevdeskStatus.UNCERTAIN
    assert inv.error_message  # erklärender Hinweis gesetzt
    # uncertain bleibt bewusst nicht auto-retrybar (manuelle Prüfung in SevDesk).
    assert repo.claim_for_export(inv_id) is False
    # Idempotent: ein zweiter Lauf findet nichts mehr.
    assert repo.reset_stale_exports() == 0


# --- SevDesk-Übersicht: Migration, Belegabzug, Treffer, Historie ----------------------

_OLD_SCHEMA = """
CREATE TABLE paperless_invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT, paperless_id INTEGER NOT NULL UNIQUE,
    title TEXT, correspondent TEXT, creditor_name TEXT, iban TEXT, bic TEXT, amount REAL,
    currency TEXT NOT NULL DEFAULT 'EUR', purpose TEXT, source TEXT,
    giro_status TEXT NOT NULL DEFAULT 'none', sevdesk_status TEXT NOT NULL DEFAULT 'none',
    sevdesk_voucher_id TEXT, paid INTEGER NOT NULL DEFAULT 0, exported_at TEXT,
    written_back_at TEXT, last_synced_at TEXT, error_message TEXT, document_date TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE document_recipients (
    paperless_id INTEGER PRIMARY KEY, suggested_label TEXT, confidence REAL, reasoning TEXT,
    status TEXT NOT NULL DEFAULT 'none', updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
INSERT INTO paperless_invoices (paperless_id, title, sevdesk_status)
    VALUES (7, 'Alt', 'exported');
INSERT INTO document_recipients (paperless_id, status) VALUES (7, 'applied');
"""


def _columns(conn, table):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def test_migration_adds_new_columns_and_tables_to_old_db(tmp_path):
    db = tmp_path / "alt.db"
    conn = sqlite3.connect(db)
    conn.executescript(_OLD_SCHEMA)
    conn.commit()
    conn.close()

    repo = Repository(db)  # init_db() zieht die DB nach
    conn = sqlite3.connect(db)
    assert {"recipient_label", "paperless_voucher_ref", "review_reason"} <= _columns(
        conn, "paperless_invoices"
    )
    assert "it_probability" in _columns(conn, "document_recipients")
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"sevdesk_vouchers", "invoice_voucher_matches", "sevdesk_sync_state"} <= tables
    indexes = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert "idx_invoices_recipient" in indexes
    conn.close()
    # Bestehende Daten bleiben lesbar, neue Felder sind leer.
    inv = repo.get_invoice_by_paperless(7)
    assert inv.sevdesk_status == SevdeskStatus.EXPORTED
    assert inv.recipient_label is None and inv.review_reason is None
    assert repo.get_recipient_cache(7).it_probability is None
    # Zweiter Start ist idempotent.
    Repository(db)


def test_upsert_invoice_mirrors_paperless_fields_with_sentinel(tmp_path):
    repo = make_repo(tmp_path)
    inv_id = repo.upsert_invoice(
        paperless_id=1, title="A", correspondent="Acme",
        recipient_label="IT-Consulting", paperless_voucher_ref="V1",
    )
    inv = repo.get_invoice(inv_id)
    assert inv.recipient_label == "IT-Consulting" and inv.paperless_voucher_ref == "V1"
    # Ohne Kwarg bleiben die Werte stehen.
    repo.upsert_invoice(paperless_id=1, title="A2", correspondent="Acme")
    inv = repo.get_invoice(inv_id)
    assert inv.recipient_label == "IT-Consulting" and inv.paperless_voucher_ref == "V1"
    # None = in Paperless entfernt -> lokal NULL.
    repo.upsert_invoice(
        paperless_id=1, title="A2", correspondent="Acme",
        recipient_label=None, paperless_voucher_ref=None,
    )
    inv = repo.get_invoice(inv_id)
    assert inv.recipient_label is None and inv.paperless_voucher_ref is None


def test_recipient_cache_it_probability_roundtrip_and_keep(tmp_path):
    repo = make_repo(tmp_path)
    repo.set_recipient_cache(
        5, suggested_label="Sascha", confidence=0.9, reasoning="x",
        status=RecipientStatus.SUGGESTED, it_probability=0.8,
    )
    assert repo.get_recipient_cache(5).it_probability == 0.8
    # mark_recipient_applied kennt den Wert nicht und darf ihn nicht löschen.
    repo.mark_recipient_applied(5)
    assert repo.get_recipient_cache(5).it_probability == 0.8
    # Explizit None = nicht eingeschätzt.
    repo.set_recipient_cache(
        5, suggested_label=None, confidence=None, reasoning=None,
        status=RecipientStatus.UNKNOWN, it_probability=None,
    )
    assert repo.get_recipient_caches([5])[5].it_probability is None


def _v(vid, **kw):
    return SevdeskVoucher(voucher_id=vid, voucher_date="2026-01-05", supplier_name="AWS",
                          sum_gross=10.0, currency="EUR", **kw)


def test_replace_vouchers_upserts_and_deletes_undelivered(tmp_path):
    repo = make_repo(tmp_path)
    assert repo.replace_vouchers([_v("1"), _v("2"), _v("3")]) == 0
    deleted = repo.replace_vouchers([_v("2", description="neu"), _v("4")])
    assert deleted == 2
    by_id = {v.voucher_id: v for v in repo.list_vouchers()}
    assert set(by_id) == {"2", "4"}
    assert by_id["2"].description == "neu"
    assert by_id["2"].last_seen_at is not None
    assert repo.replace_vouchers([]) == 2
    assert repo.list_vouchers() == []


def test_upsert_voucher_adds_single_voucher(tmp_path):
    repo = make_repo(tmp_path)
    repo.replace_vouchers([_v("1")])
    repo.upsert_voucher(_v("9"))
    assert {v.voucher_id for v in repo.list_vouchers()} == {"1", "9"}
    assert repo.get_voucher("9").supplier_name == "AWS"
    assert repo.get_voucher("nope") is None


def test_sync_state_success_and_error(tmp_path):
    repo = make_repo(tmp_path)
    st = repo.get_sevdesk_sync_state()
    assert st.last_success_at is None and st.last_error is None
    repo.set_sevdesk_sync_error("Netz weg")
    st = repo.get_sevdesk_sync_state()
    assert st.last_error == "Netz weg" and st.last_error_at and st.last_success_at is None
    repo.set_sevdesk_sync_success()
    st = repo.get_sevdesk_sync_state()
    assert st.last_success_at and st.last_error is None and st.last_error_at is None
    repo.set_sevdesk_sync_error("wieder")
    st = repo.get_sevdesk_sync_state()
    assert st.last_error == "wieder" and st.last_success_at is not None  # bleibt stehen


def _m(inv, vid, kind, score=None):
    return InvoiceVoucherMatch(invoice_id=inv, voucher_id=vid, kind=kind, score=score)


def _inv(repo, pid, corr="Acme", **kw):
    return repo.upsert_invoice(paperless_id=pid, title=f"R{pid}", correspondent=corr, **kw)


def test_replace_auto_matches_keeps_decisions(tmp_path):
    repo = make_repo(tmp_path)
    a, b = _inv(repo, 1), _inv(repo, 2)
    repo.replace_auto_matches([_m(a, "V1", MatchKind.SIMILAR, 0.7), _m(b, "V2", MatchKind.ID)])
    repo.decide_match(a, "V1", True)
    repo.decide_match(a, "V3", False)
    # Neuberechnung: alte similar/id verschwinden, Entscheidungen bleiben, ein erneuter
    # automatischer Treffer auf ein entschiedenes Paar wird übersprungen.
    repo.replace_auto_matches(
        [_m(a, "V1", MatchKind.SIMILAR, 0.9), _m(a, "V3", MatchKind.SIMILAR, 0.5)]
    )
    got = {(m.invoice_id, m.voucher_id): m.kind for m in repo.list_matches()}
    assert got == {(a, "V1"): MatchKind.CONFIRMED, (a, "V3"): MatchKind.REJECTED}
    assert [m.voucher_id for m in repo.list_matches([a])] == ["V1", "V3"]
    assert repo.list_matches([]) == []
    with pytest.raises(ValueError):
        repo.replace_auto_matches([_m(a, "V1", MatchKind.CONFIRMED)])


def test_id_treffer_verdraengt_fruehere_rejected_entscheidung_desselben_paars(tmp_path):
    repo = make_repo(tmp_path)
    a = _inv(repo, 1)
    repo.replace_auto_matches([_m(a, "V1", MatchKind.SIMILAR, 0.7)])
    repo.decide_match(a, "V1", False)  # „anderer Beleg“
    repo.decide_match(a, "V2", False)  # bleibt: kein id-Treffer dazu

    repo.replace_auto_matches([_m(a, "V1", MatchKind.ID, 1.0)])

    got = {m.voucher_id: m.kind for m in repo.list_matches([a])}
    assert got == {"V1": MatchKind.ID, "V2": MatchKind.REJECTED}


def test_decide_match_sets_kind_keeps_score_and_protects_id(tmp_path):
    repo = make_repo(tmp_path)
    a = _inv(repo, 1)
    repo.replace_auto_matches([_m(a, "V1", MatchKind.SIMILAR, 0.7), _m(a, "V2", MatchKind.ID)])
    assert repo.decide_match(a, "V1", True) is True
    m = {x.voucher_id: x for x in repo.list_matches([a])}
    assert m["V1"].kind == MatchKind.CONFIRMED and m["V1"].score == 0.7 and m["V1"].decided_at
    assert repo.decide_match(a, "V1", False) is True
    assert {x.voucher_id: x for x in repo.list_matches([a])}["V1"].kind == MatchKind.REJECTED
    # Sicherer Treffer lässt sich nicht verwerfen.
    assert repo.decide_match(a, "V2", False) is False
    assert {x.voucher_id: x for x in repo.list_matches([a])}["V2"].kind == MatchKind.ID


def test_matches_are_removed_with_invoice(tmp_path):
    repo = make_repo(tmp_path)
    a = _inv(repo, 1)
    repo.replace_auto_matches([_m(a, "GONE", MatchKind.ID)])  # Beleg nicht im Abzug: erlaubt
    repo._conn.execute("DELETE FROM paperless_invoices WHERE id = ?", (a,))
    assert repo.list_matches() == []


def test_vouchers_without_invoice(tmp_path):
    repo = make_repo(tmp_path)
    a = _inv(repo, 1)
    repo.replace_vouchers([_v("ID"), _v("SIM"), _v("CONF"), _v("REJ"), _v("FREI")])
    repo.replace_auto_matches([_m(a, "ID", MatchKind.ID), _m(a, "SIM", MatchKind.SIMILAR, 0.6)])
    repo.decide_match(a, "CONF", True)
    repo.decide_match(a, "REJ", False)
    assert {v.voucher_id for v in repo.vouchers_without_invoice()} == {"REJ", "FREI"}


def test_correspondent_context_history(tmp_path):
    repo = make_repo(tmp_path)
    it1 = _inv(repo, 1, "Acme", recipient_label="IT-Consulting")
    other = _inv(repo, 2, "Acme", recipient_label="Familie")
    exported = _inv(repo, 3, "Acme")
    repo.set_sevdesk_status(exported, SevdeskStatus.EXPORTED, voucher_id="V")
    confirmed = _inv(repo, 4, "Beta")
    repo.decide_match(confirmed, "VX", True)
    _inv(repo, 5, "Acme")  # unentschieden
    _inv(repo, 6, None, recipient_label="IT-Consulting")  # ohne Korrespondent
    # Empfänger gewinnt gegen "exported": gesetzt auf anderen Empfänger -> nicht IT.
    both = _inv(repo, 7, "Gamma", recipient_label="Familie")
    repo.set_sevdesk_status(both, SevdeskStatus.EXPORTED, voucher_id="W")

    hist = repo.correspondent_context_history("IT-Consulting")
    assert set(hist) == {"Acme", "Beta", "Gamma"}
    assert hist["Acme"].it_ids == {it1, exported}
    assert hist["Acme"].other_ids == {other}
    assert hist["Beta"].it_ids == {confirmed} and not hist["Beta"].other_ids
    assert hist["Gamma"].other_ids == {both} and not hist["Gamma"].it_ids


def test_correspondent_context_history_vergleicht_label_ohne_gross_klein_und_rand(tmp_path):
    repo = make_repo(tmp_path)
    a = _inv(repo, 1, "Acme", recipient_label="it-consulting ")
    b = _inv(repo, 2, "Acme", recipient_label="Familie")

    hist = repo.correspondent_context_history(" IT-Consulting")

    assert hist["Acme"].it_ids == {a} and hist["Acme"].other_ids == {b}


def test_set_review_and_dismiss(tmp_path):
    repo = make_repo(tmp_path)
    a = _inv(repo, 1)
    assert repo.set_review(a, "Mögliche Dublette") is True
    inv = repo.get_invoice(a)
    assert inv.sevdesk_status == SevdeskStatus.REVIEW
    assert inv.review_reason == "Mögliche Dublette"
    # Ein Statuswechsel weg von review leert den Grund.
    repo.set_sevdesk_status(a, SevdeskStatus.QUEUED)
    assert repo.get_invoice(a).review_reason is None
    repo.set_review(a, "Grund")
    assert repo.dismiss(a) is True
    inv = repo.get_invoice(a)
    assert inv.sevdesk_status == SevdeskStatus.DISMISSED and inv.review_reason is None
    # claim_for_export bleibt für review nutzbar, für exportierte nicht.
    repo.set_review(a, "Grund")
    assert repo.claim_for_export(a) is True


@pytest.mark.parametrize(
    "status", [SevdeskStatus.EXPORTED, SevdeskStatus.EXPORTING, SevdeskStatus.UNCERTAIN]
)
def test_set_review_and_dismiss_do_not_override_export_states(tmp_path, status):
    repo = make_repo(tmp_path)
    a = _inv(repo, 1)
    repo.set_sevdesk_status(a, status)
    assert repo.set_review(a, "x") is False
    assert repo.dismiss(a) is False
    assert repo.get_invoice(a).sevdesk_status == status


# ---- Änderungserkennung (Change paperless-sync-ohne-stillstand) -------------------------


def _repo_mit_tokens(tmp_path):
    tokens: list[str] = []
    return Repository(tmp_path / "lector.db", notifier=tokens.append), tokens


def _stamp(repo, inv_id, value="2020-01-01 00:00:00"):
    """Setzt last_synced_at auf einen alten Wert, damit eine Verschiebung sichtbar wird."""
    repo._conn.execute("UPDATE paperless_invoices SET last_synced_at = ? WHERE id = ?",
                       (value, inv_id))
    repo._conn.commit()


def _synced_at(repo, inv_id):
    return repo._conn.execute(
        "SELECT last_synced_at FROM paperless_invoices WHERE id = ?", (inv_id,)
    ).fetchone()[0]


def test_upsert_unveraendert_schreibt_nichts_und_sendet_kein_signal(tmp_path):
    repo, tokens = _repo_mit_tokens(tmp_path)
    kwargs = dict(
        paperless_id=1, title="Strom", correspondent="Acme",
        document_date="2026-06-06T00:00:00+02:00", recipient_label="Familie",
        paperless_voucher_ref="77",
    )
    inv_id = repo.upsert_invoice(**kwargs)
    _stamp(repo, inv_id)
    tokens.clear()
    before = repo._conn.total_changes

    assert repo.upsert_invoice(**kwargs) == inv_id

    assert repo._conn.total_changes == before
    assert tokens == []
    assert _synced_at(repo, inv_id) == "2020-01-01 00:00:00"


@pytest.mark.parametrize(
    "aenderung",
    [
        {"title": "Strom neu"},
        {"correspondent": "Andere"},
        {"recipient_label": "IT-Consulting"},
        {"paperless_voucher_ref": "99"},
        {"document_date": "2026-07-01T00:00:00+02:00"},
    ],
)
def test_upsert_geaenderte_angabe_wird_geschrieben(tmp_path, aenderung):
    repo, tokens = _repo_mit_tokens(tmp_path)
    kwargs = dict(
        paperless_id=1, title="Strom", correspondent="Acme",
        document_date="2026-06-06T00:00:00+02:00", recipient_label="Familie",
        paperless_voucher_ref="77",
    )
    inv_id = repo.upsert_invoice(**kwargs)
    _stamp(repo, inv_id)
    tokens.clear()

    repo.upsert_invoice(**{**kwargs, **aenderung})

    assert tokens == [f"inv:{inv_id}"]
    assert _synced_at(repo, inv_id) != "2020-01-01 00:00:00"
    inv = repo.get_invoice(inv_id)
    for name, value in aenderung.items():
        if name != "document_date":
            assert getattr(inv, name) == value
    if "document_date" in aenderung:
        assert inv.document_date.month == 7


def test_upsert_leerer_text_ist_gleich_none(tmp_path):
    repo, tokens = _repo_mit_tokens(tmp_path)
    inv_id = repo.upsert_invoice(
        paperless_id=1, title="A", correspondent=None, recipient_label=None,
        paperless_voucher_ref=None,
    )
    tokens.clear()
    before = repo._conn.total_changes

    repo.upsert_invoice(
        paperless_id=1, title="A", correspondent=None, recipient_label="",
        paperless_voucher_ref="",
    )

    assert repo._conn.total_changes == before
    assert tokens == []
    assert repo.get_invoice(inv_id).recipient_label is None


def test_upsert_nicht_uebergebenes_spiegelfeld_bleibt_unberuehrt(tmp_path):
    repo, tokens = _repo_mit_tokens(tmp_path)
    inv_id = repo.upsert_invoice(
        paperless_id=1, title="A", correspondent=None, recipient_label="Familie",
        paperless_voucher_ref="5",
    )
    tokens.clear()
    before = repo._conn.total_changes

    # Ohne Spiegelfelder und ohne Änderung: nichts zu tun, Felder zählen nicht.
    repo.upsert_invoice(paperless_id=1, title="A", correspondent=None)
    assert repo._conn.total_changes == before
    assert tokens == []

    # Titel ändert sich: geschrieben, Spiegelfelder bleiben stehen.
    repo.upsert_invoice(paperless_id=1, title="B", correspondent=None)
    inv = repo.get_invoice(inv_id)
    assert inv.title == "B"
    assert inv.recipient_label == "Familie"
    assert inv.paperless_voucher_ref == "5"


def test_upsert_invoices_ein_commit_tokens_nur_fuer_neu_und_geaendert(tmp_path):
    repo, tokens = _repo_mit_tokens(tmp_path)
    unveraendert = repo.upsert_invoice(paperless_id=2, title="Gleich", correspondent=None)
    geaendert = repo.upsert_invoice(paperless_id=3, title="Alt", correspondent=None)
    tokens.clear()

    commits: list[int] = []

    class _Spy:
        """Zählt Commits der echten Verbindung, ohne deren Verhalten zu ändern."""

        def __init__(self, conn):
            self._conn = conn

        def commit(self):
            commits.append(1)
            return self._conn.commit()

        def __getattr__(self, name):
            return getattr(self._conn, name)

    repo._conn = _Spy(repo._conn)

    result = repo.upsert_invoices(
        [
            InvoiceUpsert(paperless_id=1, title="Neu", correspondent=None),
            InvoiceUpsert(paperless_id=2, title="Gleich", correspondent=None),
            InvoiceUpsert(paperless_id=3, title="Neu betitelt", correspondent=None),
        ]
    )

    assert len(commits) == 1
    assert result[1].result == UpsertResult.NEW
    assert result[1].before is None
    assert result[2].result == UpsertResult.UNCHANGED
    assert result[2].invoice_id == unveraendert
    assert result[3].result == UpsertResult.CHANGED
    assert result[3].invoice_id == geaendert
    assert result[3].before.title == "Alt"
    assert sorted(tokens) == sorted([f"inv:{result[1].invoice_id}", f"inv:{geaendert}"])
    assert repo.get_invoice(geaendert).title == "Neu betitelt"


def test_upsert_invoices_ohne_aenderung_kein_commit_und_leere_liste(tmp_path):
    repo, tokens = _repo_mit_tokens(tmp_path)
    repo.upsert_invoice(paperless_id=1, title="A", correspondent=None)
    tokens.clear()
    before = repo._conn.total_changes

    assert repo.upsert_invoices([]) == {}
    result = repo.upsert_invoices([InvoiceUpsert(paperless_id=1, title="A", correspondent=None)])

    assert result[1].result == UpsertResult.UNCHANGED
    assert repo._conn.total_changes == before
    assert tokens == []


def test_upsert_invoices_doppelte_paperless_id_erstes_ergebnis_gilt(tmp_path):
    repo, tokens = _repo_mit_tokens(tmp_path)

    result = repo.upsert_invoices(
        [
            InvoiceUpsert(paperless_id=1, title="Neu", correspondent=None),
            InvoiceUpsert(paperless_id=1, title="Neu", correspondent=None),
        ]
    )

    assert result[1].result == UpsertResult.NEW
    assert result[1].before is None
    assert tokens == [f"inv:{result[1].invoice_id}"]
