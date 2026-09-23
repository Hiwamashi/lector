import asyncio

from app.config import Settings
from app.models import GiroStatus, InvoiceEventType, SevdeskStatus
from app.paperless_sync import PaperlessSync
from app.repository import Repository


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
