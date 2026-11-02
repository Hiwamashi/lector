"""Tests für Belegabruf, Abgleich-Neuberechnung, Spiegelung der Paperless-Felder (6.1) und
das sofortige Übernehmen des exportierten Belegs (5.3)."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import httpx
import pytest

from app.config import Settings
from app.events import EventBus
from app.models import MatchKind, SevdeskStatus, SevdeskVoucher
from app.paperless import PaperlessClient, PaperlessDocument, SelectField
from app.paperless_sync import PaperlessSync
from app.repository import Repository
from app.sevdesk import SevdeskClient, VoucherResult


def _settings(**extra) -> Settings:
    values = {
        "FEATURE_SEVDESK_EXPORT": "true",
        "SEVDESK_API_TOKEN": "t",
        "FEATURE_PAPERLESS_SYNC": "false",
        **extra,
    }
    return Settings(_env_file=None, **values)


def _sync(tmp_path, **extra) -> tuple[PaperlessSync, Repository, list[str]]:
    tokens: list[str] = []
    repo = Repository(tmp_path / "v.db", notifier=tokens.append)
    return PaperlessSync(_settings(**extra), repo), repo, tokens


def _voucher_obj(i: int, **extra) -> dict:
    return {
        "id": str(i),
        "voucherDate": "2026-10-03T00:00:00+02:00",
        "supplierName": f"Lieferant {i}",
        "sumGross": "10.5",
        "currency": "EUR",
        "description": "d",
        "status": "50",
        **extra,
    }


def _use_vouchers(sync: PaperlessSync, handler) -> None:
    sync._sevdesk = lambda: SevdeskClient(  # type: ignore[method-assign]
        "https://my.sevdesk.de/api/v1", "token", transport=httpx.MockTransport(handler)
    )


def _list_handler(objects: list[dict]):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"objects": objects})

    return handler


# ---- 5.2 sync_vouchers -----------------------------------------------------


async def test_sync_vouchers_erfolg_schreibt_abzug_zustand_und_treffer(tmp_path):
    sync, repo, tokens = _sync(tmp_path)
    inv_id = repo.upsert_invoice(
        paperless_id=1, title="R", correspondent="X", paperless_voucher_ref="1001"
    )
    _use_vouchers(sync, _list_handler([_voucher_obj(1001), _voucher_obj(1002)]))

    assert await sync.sync_vouchers() is True

    assert {v.voucher_id for v in repo.list_vouchers()} == {"1001", "1002"}
    state = repo.get_sevdesk_sync_state()
    assert state.last_success_at is not None and state.last_error is None
    matches = repo.list_matches([inv_id])
    assert [(m.voucher_id, m.kind) for m in matches] == [("1001", MatchKind.ID)]
    assert "vouchers:sync" in tokens


async def test_sync_vouchers_abbruch_mitten_im_blaettern_laesst_abzug_unveraendert(tmp_path):
    sync, repo, tokens = _sync(tmp_path)
    repo.replace_vouchers([SevdeskVoucher(voucher_id="ALT", sum_gross=1.0)])
    repo.set_sevdesk_sync_success()
    erfolg = repo.get_sevdesk_sync_state().last_success_at

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params["offset"] == "0":
            return httpx.Response(200, json={"objects": [_voucher_obj(i) for i in range(1000)]})
        return httpx.Response(500, json={"error": {"message": "kaputt"}})

    _use_vouchers(sync, handler)
    tokens.clear()

    assert await sync.sync_vouchers() is False  # keine Ausnahme nach außen

    assert [v.voucher_id for v in repo.list_vouchers()] == ["ALT"]
    state = repo.get_sevdesk_sync_state()
    assert state.last_error and "kaputt" in state.last_error
    assert state.last_success_at == erfolg
    assert "vouchers:sync" in tokens


@pytest.mark.parametrize(
    "antwort", [{}, {"objects": None}, {"objects": {"a": 1}}, {"error": "x"}], ids=str
)
async def test_sync_vouchers_antwort_ohne_objektliste_ist_fehler_abzug_bleibt(tmp_path, antwort):
    sync, repo, _ = _sync(tmp_path)
    repo.replace_vouchers([SevdeskVoucher(voucher_id="ALT", sum_gross=1.0)])
    repo.set_sevdesk_sync_success()
    erfolg = repo.get_sevdesk_sync_state().last_success_at

    _use_vouchers(sync, lambda request: httpx.Response(200, json=antwort))

    assert await sync.sync_vouchers() is False

    assert [v.voucher_id for v in repo.list_vouchers()] == ["ALT"]
    state = repo.get_sevdesk_sync_state()
    assert state.last_error and state.last_success_at == erfolg


async def test_sync_vouchers_folgeseite_ohne_objektliste_ist_fehler(tmp_path):
    sync, repo, _ = _sync(tmp_path)
    repo.replace_vouchers([SevdeskVoucher(voucher_id="ALT", sum_gross=1.0)])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params["offset"] == "0":
            return httpx.Response(200, json={"objects": [_voucher_obj(i) for i in range(1000)]})
        return httpx.Response(200, json={})

    _use_vouchers(sync, handler)
    assert await sync.sync_vouchers() is False
    assert [v.voucher_id for v in repo.list_vouchers()] == ["ALT"]


async def test_sync_vouchers_leere_liste_ist_legitim_null_belege(tmp_path):
    sync, repo, _ = _sync(tmp_path)
    repo.replace_vouchers([SevdeskVoucher(voucher_id="ALT", sum_gross=1.0)])
    _use_vouchers(sync, _list_handler([]))
    assert await sync.sync_vouchers() is True
    assert repo.list_vouchers() == []


async def test_sync_vouchers_geloeschter_beleg_verschwindet(tmp_path):
    sync, repo, _ = _sync(tmp_path)
    _use_vouchers(sync, _list_handler([_voucher_obj(1), _voucher_obj(2)]))
    await sync.sync_vouchers()
    _use_vouchers(sync, _list_handler([_voucher_obj(2)]))
    await sync.sync_vouchers()
    assert [v.voucher_id for v in repo.list_vouchers()] == ["2"]


async def test_sync_vouchers_nur_bei_aktivem_export(tmp_path):
    repo = Repository(tmp_path / "off.db")
    sync = PaperlessSync(Settings(_env_file=None), repo)
    sync._sevdesk = lambda: pytest.fail("darf nicht abrufen")  # type: ignore[method-assign]
    assert await sync.sync_vouchers() is False
    assert repo.get_sevdesk_sync_state().last_success_at is None


async def test_sync_vouchers_ueberlappt_nicht(tmp_path):
    sync, _, _ = _sync(tmp_path)
    aktiv = {"jetzt": 0, "max": 0}

    class _Slow:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def list_vouchers(self):
            aktiv["jetzt"] += 1
            aktiv["max"] = max(aktiv["max"], aktiv["jetzt"])
            await asyncio.sleep(0.02)
            aktiv["jetzt"] -= 1
            return []

    sync._sevdesk = lambda: _Slow()  # type: ignore[method-assign]
    await asyncio.gather(sync.sync_vouchers(), sync.sync_vouchers())
    assert aktiv["max"] == 1


async def test_recompute_matches_ohne_abruf_passiert_nichts(tmp_path):
    sync, repo, _ = _sync(tmp_path)
    repo.upsert_invoice(paperless_id=1, title="R", correspondent="X", paperless_voucher_ref="9")
    assert sync.recompute_matches() == 0
    assert repo.list_matches() == []


async def test_recompute_matches_meldet_geaenderte_rechnungen_als_ereignis(tmp_path):
    sync, repo, _ = _sync(tmp_path)
    inv_id = repo.upsert_invoice(paperless_id=1, title="R", correspondent="X")
    repo.replace_vouchers([SevdeskVoucher(voucher_id="55")])
    repo.set_sevdesk_sync_success()
    assert sync.recompute_matches() == 0  # nichts zu verknüpfen
    repo.upsert_invoice(
        paperless_id=1, title="R", correspondent="X", paperless_voucher_ref="55"
    )
    assert sync.recompute_matches() == 1
    assert sync.recompute_matches() == 0  # unverändert -> kein weiteres Ereignis
    events = [e["event_type"] for e in repo.list_invoice_events(inv_id)]
    assert events.count("vouchers_synced") == 1


# ---- Worker-Loop ----------------------------------------------------------


async def test_worker_loop_ruft_belegabruf_beim_start_und_dann_nach_eigenem_intervall(tmp_path):
    from app.worker import Worker

    settings = Settings(
        _env_file=None,
        FEATURE_PAPERLESS_SYNC="true",
        PAPERLESS_URL="http://paperless.invalid",
        PAPERLESS_TOKEN="t",
        FEATURE_SEVDESK_EXPORT="true",
        SEVDESK_API_TOKEN="t",
        PAPERLESS_SYNC_INTERVAL_SECONDS="0.01",
    )
    repo = Repository(tmp_path / "w.db")
    sync = PaperlessSync(settings, repo)
    calls = {"once": 0, "vouchers": 0}

    async def once():
        calls["once"] += 1

    async def vouchers():
        calls["vouchers"] += 1
        return True

    sync.sync_once = once  # type: ignore[method-assign]
    sync.sync_vouchers = vouchers  # type: ignore[method-assign]

    class _Adapter:
        name = "fake"
        page_limit = 15

    worker = Worker(settings, repo, _Adapter(), EventBus(), paperless_sync=sync)  # type: ignore[arg-type]
    task = asyncio.create_task(worker._paperless_loop())
    await asyncio.sleep(0.15)
    worker._stop.set()
    await task
    assert calls["once"] >= 3
    assert calls["vouchers"] == 1  # Intervall (60 min) noch nicht abgelaufen


async def test_worker_ruft_belegabruf_vor_dem_ersten_paperless_sync_auf(tmp_path):
    from app.worker import Worker

    settings = Settings(
        _env_file=None,
        FEATURE_PAPERLESS_SYNC="true",
        PAPERLESS_URL="http://p",
        PAPERLESS_TOKEN="t",
        FEATURE_SEVDESK_EXPORT="true",
        SEVDESK_API_TOKEN="t",
        PAPERLESS_SYNC_INTERVAL_SECONDS="0.01",
    )
    repo = Repository(tmp_path / "wo.db")
    sync = PaperlessSync(settings, repo)
    order: list[str] = []

    async def once():
        order.append("once")

    async def vouchers():
        order.append("vouchers")
        return True

    sync.sync_once = once  # type: ignore[method-assign]
    sync.sync_vouchers = vouchers  # type: ignore[method-assign]

    class _Adapter:
        name = "fake"
        page_limit = 15

    worker = Worker(settings, repo, _Adapter(), EventBus(), paperless_sync=sync)  # type: ignore[arg-type]
    task = asyncio.create_task(worker._paperless_loop())
    await asyncio.sleep(0.05)
    worker._stop.set()
    await task
    assert order[:2] == ["vouchers", "once"]


# ---- 5.3 Export übernimmt den Beleg sofort ----------------------------------


async def test_export_uebernimmt_beleg_sofort_als_id_treffer(tmp_path):
    sync, repo, tokens = _sync(tmp_path)
    inv_id = repo.upsert_invoice(
        paperless_id=8, title="Rechnung Acme", correspondent="Acme", document_date="2026-10-03"
    )
    repo.set_sevdesk_status(inv_id, SevdeskStatus.QUEUED)
    # Es gab bereits einen erfolgreichen Abruf (leer) — sonst bliebe der Abgleich „nicht verfügbar“.
    repo.replace_vouchers([])
    repo.set_sevdesk_sync_success()

    class FakePaper:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def download_original(self, pid):
            return (b"%PDF-1.4", "x.pdf")

    class FakeSev:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def upload_temp_file(self, *a, **k):
            return "temp.pdf"

        async def save_voucher_from_temp(self, *a, **k):
            return VoucherResult(voucher_id="V-77")

        async def list_vouchers(self):  # pragma: no cover - darf nicht gebraucht werden
            raise AssertionError("kein Abruf erwartet")

    sync._paperless = lambda: FakePaper()  # type: ignore[method-assign]
    sync._sevdesk = lambda: FakeSev()  # type: ignore[method-assign]

    await sync.export_invoice(inv_id)

    voucher = repo.get_voucher("V-77")
    assert voucher is not None
    assert voucher.voucher_date == "2026-10-03"
    assert voucher.supplier_name == "Acme"
    assert voucher.sum_gross is None
    assert voucher.currency == "EUR"
    assert voucher.description == "Rechnung Acme"
    assert voucher.status == "50"
    matches = repo.list_matches([inv_id])
    assert [(m.voucher_id, m.kind) for m in matches] == [("V-77", MatchKind.ID)]
    assert "vouchers:sync" in tokens


# ---- 6.1 Spiegelung von Empfänger und Beleg-Vermerk -------------------------

FIELD = SelectField(
    field_id=5,
    label_to_id={"IT-Consulting": "opt-it", "Familie": "opt-fam"},
    id_to_label={"opt-it": "IT-Consulting", "opt-fam": "Familie"},
)
IDS = {"doctype": 1, "cf_sevdesk_id": 7, "sevdesk_tag": 3}


def _doc(doc_id: int, custom_fields: list[dict]) -> PaperlessDocument:
    return PaperlessDocument(
        id=doc_id, title=f"R{doc_id}", content="", correspondent_id=None,
        document_type_id=1, tag_ids=[3], custom_fields=custom_fields, original_file_name=None,
    )


class _MirrorClient:
    def __init__(self, docs):
        self.docs = docs

    async def list_documents(self, *, document_type_id=None, tag_ids=None):
        return self.docs

    @staticmethod
    def select_value(doc, field_id):
        return PaperlessClient.select_value(doc, field_id)


async def _noop(*_a, **_k):
    return None


async def test_sync_spiegelt_empfaenger_und_beleg_vermerk(tmp_path, monkeypatch):
    sync, repo, _ = _sync(tmp_path)
    monkeypatch.setattr(sync, "_extract_and_store", _noop)
    client = _MirrorClient(
        [
            _doc(1, [{"field": 5, "value": "opt-it"}, {"field": 7, "value": " 1234 "}]),
            _doc(2, []),
        ]
    )
    await sync._sync_invoices(client, IDS, {}, FIELD)

    mit = repo.get_invoice_by_paperless(1)
    assert mit.recipient_label == "IT-Consulting"
    assert mit.paperless_voucher_ref == "1234"
    ohne = repo.get_invoice_by_paperless(2)
    assert ohne.recipient_label is None
    assert ohne.paperless_voucher_ref is None


async def test_sync_entfernter_empfaenger_wird_lokal_null(tmp_path, monkeypatch):
    sync, repo, _ = _sync(tmp_path)
    monkeypatch.setattr(sync, "_extract_and_store", _noop)
    client = _MirrorClient(
        [_doc(1, [{"field": 5, "value": "opt-fam"}, {"field": 7, "value": "9"}])]
    )
    await sync._sync_invoices(client, IDS, {}, FIELD)
    assert repo.get_invoice_by_paperless(1).recipient_label == "Familie"

    # In Paperless sind Empfänger (Wert null) und Beleg-Vermerk (Feld entfernt) weg.
    client.docs = [_doc(1, [{"field": 5, "value": None}])]
    await sync._sync_invoices(client, IDS, {}, FIELD)
    inv = repo.get_invoice_by_paperless(1)
    assert inv.recipient_label is None
    assert inv.paperless_voucher_ref is None


async def test_sync_ohne_aufloesbares_feld_laesst_lokalen_wert_stehen(tmp_path, monkeypatch):
    sync, repo, _ = _sync(tmp_path)
    monkeypatch.setattr(sync, "_extract_and_store", _noop)
    repo.upsert_invoice(
        paperless_id=1, title="R1", correspondent=None,
        recipient_label="Familie", paperless_voucher_ref="42",
    )
    client = _MirrorClient([_doc(1, [])])
    # Weder Empfänger-Feld (None) noch Beleg-Feld (ids ohne cf_sevdesk_id) bekannt.
    await sync._sync_invoices(client, {"doctype": 1}, {}, None)
    inv = repo.get_invoice_by_paperless(1)
    assert inv.recipient_label == "Familie"
    assert inv.paperless_voucher_ref == "42"


async def test_sync_sevdesk_tag_spiegelt_ebenfalls(tmp_path):
    sync, repo, _ = _sync(tmp_path)
    client = _MirrorClient(
        [_doc(1, [{"field": 5, "value": "opt-it"}, {"field": 7, "value": "77"}])]
    )
    await sync._sync_sevdesk_tag(client, IDS, {}, FIELD)
    inv = repo.get_invoice_by_paperless(1)
    assert inv.recipient_label == "IT-Consulting"
    assert inv.paperless_voucher_ref == "77"
    # Ein vermerkter Beleg ist ein sicherer Treffer: nicht vormerken (Aufgabe 7.4).
    assert inv.sevdesk_status == SevdeskStatus.NONE


async def test_sync_once_loest_empfaengerfeld_einmal_je_lauf_auf(tmp_path, monkeypatch):
    sync, repo, _ = _sync(tmp_path, FEATURE_PAPERLESS_SYNC="true", PAPERLESS_URL="http://x",
                          PAPERLESS_TOKEN="t")
    monkeypatch.setattr(sync, "_extract_and_store", _noop)
    aufrufe = {"n": 0}

    class _Full(_MirrorClient):
        async def resolve_document_type_id(self, name):
            return 1

        async def list_tags(self):
            return [{"name": "sevdesk", "id": 3}, {"name": "sevdesk-exportiert", "id": 4},
                    {"name": "überwiesen", "id": 6}]

        async def ensure_custom_field(self, name, data_type):
            return 7

        async def correspondent_map(self):
            return {}

        async def resolve_select_field(self, name):
            aufrufe["n"] += 1
            return FIELD

    client = _Full([_doc(i, [{"field": 5, "value": "opt-it"}]) for i in range(1, 4)])

    @asynccontextmanager
    async def fake_paperless():
        yield client

    monkeypatch.setattr(sync, "_paperless", fake_paperless)
    await sync.sync_once()
    assert aufrufe["n"] == 1
    assert repo.get_invoice_by_paperless(3).recipient_label == "IT-Consulting"

