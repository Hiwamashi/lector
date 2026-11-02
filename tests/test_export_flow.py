"""Tests für Export mit Sperre/Rückfrage/Betrag (7.2), Rückschrieb mit Empfänger und
Nachholen (7.3), Tag-Weg (7.4) und Mehrfachexport (7.5)."""

from __future__ import annotations

import httpx
import pytest

from app.config import Settings
from app.models import (
    GiroStatus,
    InvoiceEventType,
    InvoiceVoucherMatch,
    MatchKind,
    SevdeskStatus,
    SevdeskVoucher,
)
from app.paperless import PaperlessClient, PaperlessDocument, SelectField
from app.paperless_sync import PaperlessSync
from app.repository import Repository
from app.sevdesk import VoucherResult
from app.sevdesk_export_checks import ExportStatus

FIELD = SelectField(
    field_id=5,
    label_to_id={"IT-Consulting": "opt-it", "Familie": "opt-fam"},
    id_to_label={"opt-it": "IT-Consulting", "opt-fam": "Familie"},
)
IDS = {
    "doctype": 1, "sevdesk_tag": 3, "tag_sevdesk_done": 4, "cf_sevdesk_id": 7, "cf_exported_at": 8,
}  # fmt: skip


class Fake:
    """Gemeinsamer Fake für Paperless- und SevDesk-Client (Kontextmanager auf sich selbst)."""

    def __init__(self, docs=None):
        self.docs = docs or []
        self.saved: list[dict] = []
        self.field_writes: list[dict] = []
        self.tags: list[list[int]] = []
        self.notes: list[str] = []
        self.fail_note_once = False
        self.fail_fields = False
        self.voucher_seq = 0
        self.live_fields: dict[int, list[dict]] = {}  # Paperless-ID -> Custom Fields live
        self.gone: set[int] = set()  # gelöschte Dokumente (404)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    # Paperless
    async def list_documents(self, *, document_type_id=None, tag_ids=None):
        return self.docs

    async def get_document(self, pid):
        if pid in self.gone:
            request = httpx.Request("GET", f"http://p/api/documents/{pid}/")
            raise httpx.HTTPStatusError(
                "404", request=request, response=httpx.Response(404, request=request)
            )
        return _doc(pid, self.live_fields.get(pid))

    @staticmethod
    def select_value(doc, field_id):
        return PaperlessClient.select_value(doc, field_id)

    async def download_original(self, pid):
        return (b"%PDF-1.4", "x.pdf")

    async def set_custom_fields(self, pid, values):
        if self.fail_fields:
            raise httpx.ConnectError("weg")
        self.field_writes.append(dict(values))

    async def add_tags(self, pid, tag_ids):
        self.tags.append(list(tag_ids))

    async def get_notes(self, pid):
        return list(self.notes)

    async def add_note(self, pid, note):
        self.notes.append(note)
        if self.fail_note_once:
            self.fail_note_once = False
            raise httpx.ReadTimeout("nach dem Anlegen abgebrochen")

    # SevDesk
    async def upload_temp_file(self, *a, **k):
        return "temp.pdf"

    async def save_voucher_from_temp(self, *a, **k):
        self.voucher_seq += 1
        self.saved.append(k)
        return VoucherResult(voucher_id=f"V-{self.voucher_seq}", link="http://sev/x")


def _make(tmp_path, *, paperless=False, field=FIELD, **extra):
    values = {
        "FEATURE_SEVDESK_EXPORT": "true",
        "SEVDESK_API_TOKEN": "t",
        "FEATURE_PAPERLESS_SYNC": "true" if paperless else "false",
        **({"PAPERLESS_URL": "http://p", "PAPERLESS_TOKEN": "t"} if paperless else {}),
        **extra,
    }
    repo = Repository(tmp_path / "e.db")
    sync = PaperlessSync(Settings(_env_file=None, **values), repo)
    fake = Fake()
    sync._paperless = lambda: fake  # type: ignore[method-assign]
    sync._sevdesk = lambda: fake  # type: ignore[method-assign]
    sync._ids = dict(IDS)
    sync._recipient_field = field
    sync._recipient_field_resolved = True
    return sync, repo, fake


def _doc(doc_id: int, custom_fields: list[dict] | None = None) -> PaperlessDocument:
    return PaperlessDocument(
        id=doc_id, title=f"R{doc_id}", content="", correspondent_id=None, document_type_id=1,
        tag_ids=[3], custom_fields=custom_fields or [], original_file_name=None,
    )  # fmt: skip


def _events(repo, invoice_id, event_type):
    return [e for e in repo.list_invoice_events(invoice_id) if e["event_type"] == event_type.value]


# ---- 7.2 Sperre, Rückfrage, Bestätigung --------------------------------------


async def test_harte_sperre_exportiert_nicht_und_aendert_status_nicht(tmp_path):
    sync, repo, fake = _make(tmp_path)
    inv = repo.upsert_invoice(paperless_id=1, title="R", correspondent="X",
                              paperless_voucher_ref="99")  # fmt: skip
    repo.set_sevdesk_status(inv, SevdeskStatus.QUEUED)

    outcome = await sync.export_invoice(inv, confirmed=True)  # Bestätigung hilft nicht

    assert outcome.status == ExportStatus.BLOCKED and "99" in outcome.message
    assert fake.saved == []
    assert repo.get_invoice(inv).sevdesk_status == SevdeskStatus.QUEUED


async def test_rueckfrage_ohne_bestaetigung_exportiert_nicht(tmp_path):
    sync, repo, fake = _make(tmp_path)
    inv = repo.upsert_invoice(paperless_id=1, title="R", correspondent="X",
                              recipient_label="Familie")  # fmt: skip

    outcome = await sync.export_invoice(inv)

    assert outcome.status == ExportStatus.NEEDS_CONFIRMATION
    assert outcome.reasons and "Familie" in outcome.reasons[0]
    assert fake.saved == []
    assert repo.get_invoice(inv).sevdesk_status == SevdeskStatus.NONE


async def test_mit_bestaetigung_wird_exportiert(tmp_path):
    sync, repo, fake = _make(tmp_path)
    inv = repo.upsert_invoice(paperless_id=1, title="R", correspondent="X",
                              recipient_label="Familie")  # fmt: skip

    outcome = await sync.export_invoice(inv, confirmed=True)

    assert outcome.status == ExportStatus.EXPORTED and outcome.voucher_id == "V-1"
    assert repo.get_invoice(inv).sevdesk_status == SevdeskStatus.EXPORTED


async def test_unbekannte_rechnung_und_erneuter_export_sind_gemeldet(tmp_path):
    sync, repo, fake = _make(tmp_path)
    assert (await sync.export_invoice(999)).status == ExportStatus.SKIPPED
    inv = repo.upsert_invoice(paperless_id=1, title="R", correspondent="X")
    assert (await sync.export_invoice(inv)).status == ExportStatus.EXPORTED
    assert (await sync.export_invoice(inv)).status == ExportStatus.BLOCKED
    assert len(fake.saved) == 1


# ---- 7.2 Betrag ----------------------------------------------------------------


def _with_amount(repo, giro: GiroStatus) -> int:
    inv = repo.upsert_invoice(paperless_id=1, title="R", correspondent="X")
    repo.set_giro_data(
        inv, creditor_name="X", iban=None, bic=None, amount=39.27, currency="EUR",
        purpose=None, source="test", giro_status=giro,
    )  # fmt: skip
    return inv


async def test_betrag_mit_konto_wird_gesendet_und_im_abzug_uebernommen(tmp_path):
    sync, repo, fake = _make(tmp_path, SEVDESK_ACCOUNT_DATEV_ID="4279")
    inv = _with_amount(repo, GiroStatus.READY)

    await sync.export_invoice(inv)

    assert fake.saved[0]["amount"] == 39.27 and fake.saved[0]["account_datev_id"] == "4279"
    assert repo.get_voucher("V-1").sum_gross == 39.27


async def test_betrag_edited_wird_ebenfalls_gesendet(tmp_path):
    sync, repo, fake = _make(tmp_path, SEVDESK_ACCOUNT_DATEV_ID="4279")
    inv = _with_amount(repo, GiroStatus.EDITED)
    await sync.export_invoice(inv)
    assert fake.saved[0]["amount"] == 39.27


async def test_betrag_ohne_konto_keine_position_und_abzug_ohne_summe(tmp_path):
    sync, repo, fake = _make(tmp_path)
    inv = _with_amount(repo, GiroStatus.READY)

    await sync.export_invoice(inv)

    assert fake.saved[0]["account_datev_id"] is None  # save_voucher sendet dann keine Position
    assert repo.get_voucher("V-1").sum_gross is None


@pytest.mark.parametrize("giro", [GiroStatus.FAILED, GiroStatus.NONE])
async def test_betrag_bei_giro_failed_oder_none_wird_nicht_gesendet(tmp_path, giro):
    sync, repo, fake = _make(tmp_path, SEVDESK_ACCOUNT_DATEV_ID="4279")
    inv = _with_amount(repo, giro)

    await sync.export_invoice(inv)

    assert fake.saved[0]["amount"] is None
    assert repo.get_voucher("V-1").sum_gross is None


# ---- 7.3 Rückschrieb mit Empfänger und Nachholen -------------------------------


async def test_export_setzt_empfaenger_lokal_und_in_paperless(tmp_path):
    sync, repo, fake = _make(tmp_path, paperless=True)
    inv = repo.upsert_invoice(paperless_id=1, title="R", correspondent="X")

    await sync.export_invoice(inv)

    assert {5: "opt-it", 7: "V-1"}.items() <= fake.field_writes[0].items()
    i = repo.get_invoice(inv)
    assert i.recipient_label == "IT-Consulting" and i.written_back_at is not None
    assert fake.notes == ["Nach SevDesk exportiert — Beleg V-1 (http://sev/x)"]


async def test_fehlende_kontext_option_schreibt_rest_zurueck_und_vermerkt_hinweis(tmp_path):
    kein_it = SelectField(field_id=5, label_to_id={"Familie": "opt-fam"},
                          id_to_label={"opt-fam": "Familie"})  # fmt: skip
    sync, repo, fake = _make(tmp_path, paperless=True, field=kein_it)
    inv = repo.upsert_invoice(paperless_id=1, title="R", correspondent="X")

    await sync.export_invoice(inv)

    assert 5 not in fake.field_writes[0] and fake.field_writes[0][7] == "V-1"
    assert repo.get_invoice(inv).recipient_label is None
    hinweise = _events(repo, inv, InvoiceEventType.WRITTEN_BACK)
    assert any("Option" in (e["message"] or "") for e in hinweise)
    assert repo.get_invoice(inv).written_back_at is not None


async def test_rueckschrieb_scheitert_sync_holt_nach_notiz_genau_einmal(tmp_path):
    sync, repo, fake = _make(tmp_path, paperless=True)
    inv = repo.upsert_invoice(paperless_id=1, title="R", correspondent="X")
    fake.fail_note_once = True  # Notiz kommt an, die Antwort geht verloren

    outcome = await sync.export_invoice(inv)

    assert outcome.status == ExportStatus.EXPORTED
    i = repo.get_invoice(inv)
    assert i.sevdesk_status == SevdeskStatus.EXPORTED and i.written_back_at is None
    assert len(fake.notes) == 1

    await sync._retry_write_backs(fake, sync._ids)

    i = repo.get_invoice(inv)
    assert i.written_back_at is not None and i.recipient_label == "IT-Consulting"
    assert len(fake.notes) == 1  # nicht doppelt
    assert fake.field_writes[-1][5] == "opt-it"

    await sync._retry_write_backs(fake, sync._ids)  # nichts mehr offen
    assert len(fake.field_writes) == 2


async def test_nachholen_scheitert_erneut_bleibt_offen(tmp_path):
    sync, repo, fake = _make(tmp_path, paperless=True)
    inv = repo.upsert_invoice(paperless_id=1, title="R", correspondent="X")
    fake.fail_fields = True
    await sync.export_invoice(inv)
    assert repo.get_invoice(inv).written_back_at is None
    await sync._retry_write_backs(fake, sync._ids)
    assert repo.get_invoice(inv).written_back_at is None
    assert repo.get_invoice(inv).recipient_label is None


async def _nach_fehlgeschlagenem_export(tmp_path, **extra):
    """Rechnung exportiert, Rückschrieb scheiterte (Feldschreiben), Fake wieder heil."""
    sync, repo, fake = _make(tmp_path, paperless=True, **extra)
    inv = repo.upsert_invoice(paperless_id=1, title="R", correspondent="X")
    fake.fail_fields = True
    await sync.export_invoice(inv)
    fake.fail_fields = False
    assert repo.get_invoice(inv).written_back_at is None
    return sync, repo, fake, inv


async def test_nachholen_leeres_empfaengerfeld_wird_gesetzt(tmp_path):
    sync, repo, fake, inv = await _nach_fehlgeschlagenem_export(tmp_path)

    await sync._retry_write_backs(fake, sync._ids)

    assert fake.field_writes[-1][5] == "opt-it"
    assert repo.get_invoice(inv).recipient_label == "IT-Consulting"
    assert repo.get_invoice(inv).written_back_at is not None


async def test_nachholen_ueberschreibt_anderen_empfaenger_nicht(tmp_path):
    sync, repo, fake, inv = await _nach_fehlgeschlagenem_export(tmp_path)
    fake.live_fields[1] = [{"field": 5, "value": "opt-fam"}]  # inzwischen „Familie“

    await sync._retry_write_backs(fake, sync._ids)
    i = repo.get_invoice(inv)

    assert 5 not in fake.field_writes[-1]
    assert fake.field_writes[-1][7].startswith("V-")  # übrige Felder wie gehabt
    assert fake.tags and fake.notes
    assert i.recipient_label != "IT-Consulting"
    assert i.written_back_at is not None  # kein erneuter Versuch jeden Lauf
    hinweise = [
        e for e in _events(repo, inv, InvoiceEventType.WRITTEN_BACK)
        if "nicht überschrieben" in (e["message"] or "")
    ]  # fmt: skip
    assert len(hinweise) == 1 and "Familie" in hinweise[0]["message"]


async def test_nachholen_gleicher_empfaenger_am_dokument_ist_unkritisch(tmp_path):
    sync, repo, fake, inv = await _nach_fehlgeschlagenem_export(tmp_path)
    fake.live_fields[1] = [{"field": 5, "value": "opt-it"}]

    await sync._retry_write_backs(fake, sync._ids)

    assert fake.field_writes[-1][5] == "opt-it"
    assert repo.get_invoice(inv).written_back_at is not None
    assert not [
        e for e in _events(repo, inv, InvoiceEventType.WRITTEN_BACK)
        if "nicht überschrieben" in (e["message"] or "")
    ]  # fmt: skip


async def test_nachholen_geloeschtes_dokument_404_wird_einmal_vermerkt(tmp_path):
    sync, repo, fake, inv = await _nach_fehlgeschlagenem_export(tmp_path)
    fake.gone.add(1)

    await sync._retry_write_backs(fake, sync._ids)
    await sync._retry_write_backs(fake, sync._ids)  # nicht erneut versucht

    assert repo.get_invoice(inv).written_back_at is not None
    hinweise = [
        e for e in _events(repo, inv, InvoiceEventType.WRITTEN_BACK)
        if "nicht mehr vorhanden" in (e["message"] or "")
    ]  # fmt: skip
    assert len(hinweise) == 1


async def test_erstexport_setzt_empfaenger_auch_wenn_dokument_anderen_traegt(tmp_path):
    sync, repo, fake = _make(tmp_path, paperless=True)
    fake.live_fields[1] = [{"field": 5, "value": "opt-fam"}]
    inv = repo.upsert_invoice(paperless_id=1, title="R", correspondent="X")

    await sync.export_invoice(inv)

    assert fake.field_writes[0][5] == "opt-it"  # bestätigt beim Export -> setzen


async def test_rueckschrieb_findet_kontext_option_ohne_gross_klein_und_rand(tmp_path):
    feld = SelectField(
        field_id=5,
        label_to_id={"it-consulting ": "opt-it"},
        id_to_label={"opt-it": "it-consulting "},
    )  # fmt: skip
    sync, repo, fake = _make(tmp_path, paperless=True, field=feld)
    assert sync.recipient_option_available("IT-Consulting") is True
    inv = repo.upsert_invoice(paperless_id=1, title="R", correspondent="X")

    await sync.export_invoice(inv)

    assert fake.field_writes[0][5] == "opt-it"


async def test_erstexport_rueckschrieb_fehler_erzeugt_ereignis(tmp_path):
    sync, repo, fake, inv = await _nach_fehlgeschlagenem_export(tmp_path)

    ereignisse = _events(repo, inv, InvoiceEventType.WRITE_BACK_FAILED)
    assert len(ereignisse) == 1 and "ConnectError" in ereignisse[0]["message"]
    assert repo.get_invoice(inv).written_back_at is None


async def test_nachholen_fehler_ereignis_nur_einmal_je_fehlertext(tmp_path):
    sync, repo, fake, inv = await _nach_fehlgeschlagenem_export(tmp_path)
    fake.fail_fields = True

    await sync._retry_write_backs(fake, sync._ids)
    await sync._retry_write_backs(fake, sync._ids)

    assert len(_events(repo, inv, InvoiceEventType.WRITE_BACK_FAILED)) == 1  # gleicher Text

    fake.fail_fields = False
    await sync._retry_write_backs(fake, sync._ids)
    assert repo.get_invoice(inv).written_back_at is not None


# ---- Auto-Export nur mit Abgleich -----------------------------------------------


async def test_auto_export_ohne_abruf_bleibt_queued_ohne_ereignis_spam(tmp_path):
    sync, repo, fake = _make(tmp_path, paperless=True, SEVDESK_AUTO_EXPORT="true")
    fake.docs = [_doc(1)]

    await sync._sync_sevdesk_tag(fake, IDS, {}, FIELD)
    await sync._sync_sevdesk_tag(fake, IDS, {}, FIELD)

    inv = repo.get_invoice_by_paperless(1)
    assert inv.sevdesk_status == SevdeskStatus.QUEUED
    assert fake.saved == []
    assert len(_events(repo, inv.id, InvoiceEventType.SEVDESK_QUEUED)) == 1


async def test_auto_export_nach_erfolgreichem_abruf_exportiert_queued_rechnung(tmp_path):
    sync, repo, fake = _make(tmp_path, paperless=True, SEVDESK_AUTO_EXPORT="true")
    fake.docs = [_doc(1)]
    await sync._sync_sevdesk_tag(fake, IDS, {}, FIELD)
    assert fake.saved == []

    repo.replace_vouchers([])
    repo.set_sevdesk_sync_success()
    await sync._sync_sevdesk_tag(fake, IDS, {}, FIELD)

    inv = repo.get_invoice_by_paperless(1)
    assert inv.sevdesk_status == SevdeskStatus.EXPORTED and len(fake.saved) == 1
    assert len(_events(repo, inv.id, InvoiceEventType.SEVDESK_QUEUED)) == 1


async def test_auto_export_nach_abruf_mit_dublette_wird_review(tmp_path):
    sync, repo, fake = _make(tmp_path, paperless=True, SEVDESK_AUTO_EXPORT="true")
    fake.docs = [_doc(1)]
    await sync._sync_sevdesk_tag(fake, IDS, {}, FIELD)
    inv = repo.get_invoice_by_paperless(1)

    repo.replace_vouchers([SevdeskVoucher(voucher_id="V9", sum_gross=5.0)])
    repo.set_sevdesk_sync_success()
    repo.replace_auto_matches(
        [InvoiceVoucherMatch(invoice_id=inv.id, voucher_id="V9", kind=MatchKind.SIMILAR, score=0.8)]
    )
    await sync._sync_sevdesk_tag(fake, IDS, {}, FIELD)

    i = repo.get_invoice(inv.id)
    assert i.sevdesk_status == SevdeskStatus.REVIEW and "V9" in i.review_reason
    assert fake.saved == []


async def test_queued_ohne_auto_export_wird_nicht_erneut_bewertet(tmp_path):
    sync, repo, fake = _make(tmp_path, paperless=True)  # kein Auto-Export
    fake.docs = [_doc(1)]
    repo.set_sevdesk_sync_success()
    await sync._sync_sevdesk_tag(fake, IDS, {}, FIELD)
    await sync._sync_sevdesk_tag(fake, IDS, {}, FIELD)

    assert repo.get_invoice_by_paperless(1).sevdesk_status == SevdeskStatus.QUEUED
    assert fake.saved == []


# ---- 7.4 Tag-Weg ---------------------------------------------------------------


async def test_tag_familie_mit_auto_export_wird_review_ohne_export(tmp_path):
    sync, repo, fake = _make(tmp_path, paperless=True, SEVDESK_AUTO_EXPORT="true")
    fake.docs = [_doc(1, [{"field": 5, "value": "opt-fam"}])]

    await sync._sync_sevdesk_tag(fake, IDS, {}, FIELD)
    await sync._sync_sevdesk_tag(fake, IDS, {}, FIELD)  # zweiter Lauf: kein Event-Spam

    inv = repo.get_invoice_by_paperless(1)
    assert inv.sevdesk_status == SevdeskStatus.REVIEW
    assert "Familie" in inv.review_reason
    assert fake.saved == []
    assert len(_events(repo, inv.id, InvoiceEventType.SEVDESK_REVIEW)) == 1


async def test_tag_unauffaellig_mit_auto_export_exportiert_und_setzt_empfaenger(tmp_path):
    sync, repo, fake = _make(tmp_path, paperless=True, SEVDESK_AUTO_EXPORT="true")
    repo.set_sevdesk_sync_success()
    fake.docs = [_doc(1)]

    await sync._sync_sevdesk_tag(fake, IDS, {}, FIELD)

    inv = repo.get_invoice_by_paperless(1)
    assert inv.sevdesk_status == SevdeskStatus.EXPORTED
    assert inv.recipient_label == "IT-Consulting"
    assert fake.field_writes[0][5] == "opt-it"


async def test_tag_sicherer_treffer_kein_export_und_ereignis_nur_einmal(tmp_path):
    sync, repo, fake = _make(tmp_path, paperless=True, SEVDESK_AUTO_EXPORT="true")
    fake.docs = [_doc(1, [{"field": 7, "value": "55"}])]

    await sync._sync_sevdesk_tag(fake, IDS, {}, FIELD)
    await sync._sync_sevdesk_tag(fake, IDS, {}, FIELD)

    inv = repo.get_invoice_by_paperless(1)
    assert inv.sevdesk_status == SevdeskStatus.NONE
    assert fake.saved == []
    ereignisse = _events(repo, inv.id, InvoiceEventType.SEVDESK_REVIEW)
    assert len(ereignisse) == 1 and "55" in ereignisse[0]["message"]
    assert _events(repo, inv.id, InvoiceEventType.SEVDESK_QUEUED) == []


async def test_tag_mit_aehnlichem_treffer_wird_review(tmp_path):
    sync, repo, fake = _make(tmp_path, paperless=True, SEVDESK_AUTO_EXPORT="true")
    inv = repo.upsert_invoice(paperless_id=1, title="R1", correspondent=None)
    repo.replace_vouchers([SevdeskVoucher(voucher_id="V9", sum_gross=5.0)])
    repo.replace_auto_matches(
        [InvoiceVoucherMatch(invoice_id=inv, voucher_id="V9", kind=MatchKind.SIMILAR, score=0.8)]
    )
    fake.docs = [_doc(1)]

    await sync._sync_sevdesk_tag(fake, IDS, {}, FIELD)

    i = repo.get_invoice(inv)
    assert i.sevdesk_status == SevdeskStatus.REVIEW and "V9" in i.review_reason
    assert fake.saved == []


async def test_dismissed_wird_nicht_erneut_vorgemerkt(tmp_path):
    sync, repo, fake = _make(tmp_path, paperless=True, SEVDESK_AUTO_EXPORT="true")
    fake.docs = [_doc(1, [{"field": 5, "value": "opt-fam"}])]
    await sync._sync_sevdesk_tag(fake, IDS, {}, FIELD)
    inv = repo.get_invoice_by_paperless(1)

    assert sync.dismiss_invoice(inv.id) is True
    await sync._sync_sevdesk_tag(fake, IDS, {}, FIELD)

    assert repo.get_invoice(inv.id).sevdesk_status == SevdeskStatus.DISMISSED
    assert fake.saved == []
    assert len(_events(repo, inv.id, InvoiceEventType.SEVDESK_DISMISSED)) == 1


async def test_review_bleibt_review_wenn_gruende_wegfallen(tmp_path):
    sync, repo, fake = _make(tmp_path, paperless=True, SEVDESK_AUTO_EXPORT="true")
    fake.docs = [_doc(1, [{"field": 5, "value": "opt-fam"}])]
    await sync._sync_sevdesk_tag(fake, IDS, {}, FIELD)

    fake.docs = [_doc(1, [{"field": 5, "value": "opt-it"}])]  # Empfänger inzwischen korrigiert
    await sync._sync_sevdesk_tag(fake, IDS, {}, FIELD)

    inv = repo.get_invoice_by_paperless(1)
    assert inv.sevdesk_status == SevdeskStatus.REVIEW  # der Nutzer entscheidet
    assert fake.saved == []


async def test_dismiss_bei_exportierter_rechnung_wirkungslos(tmp_path):
    sync, repo, _ = _make(tmp_path)
    inv = repo.upsert_invoice(paperless_id=1, title="R", correspondent=None)
    repo.set_sevdesk_status(inv, SevdeskStatus.EXPORTED, voucher_id="V")
    assert sync.dismiss_invoice(inv) is False
    assert _events(repo, inv, InvoiceEventType.SEVDESK_DISMISSED) == []


# ---- 7.5 Mehrfachexport --------------------------------------------------------


async def test_mehrfachexport_fuenf_rechnungen_eine_dublette(tmp_path):
    sync, repo, fake = _make(tmp_path)
    ids = [
        repo.upsert_invoice(paperless_id=n, title=f"R{n}", correspondent=None) for n in range(1, 6)
    ]
    repo.replace_vouchers([SevdeskVoucher(voucher_id="V9", sum_gross=5.0)])
    repo.replace_auto_matches(
        [InvoiceVoucherMatch(invoice_id=ids[2], voucher_id="V9", kind=MatchKind.SIMILAR, score=0.8)]
    )

    results = await sync.export_invoices(ids)

    assert [i for i, _ in results] == ids
    status = {i: o.status for i, o in results}
    assert [status[i] for i in ids] == [
        ExportStatus.EXPORTED, ExportStatus.EXPORTED, ExportStatus.SKIPPED,
        ExportStatus.EXPORTED, ExportStatus.EXPORTED,
    ]  # fmt: skip
    skipped = dict(results)[ids[2]]
    assert "V9" in skipped.message and skipped.reasons
    assert len(fake.saved) == 4
    assert repo.get_invoice(ids[2]).sevdesk_status == SevdeskStatus.NONE
