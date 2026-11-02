"""Unit-Tests für ``export_blockers`` (Aufgabe 7.1): je Grund und ohne Grund."""

from __future__ import annotations

from app.models import InvoiceVoucherMatch, MatchKind, PaperlessInvoice, SevdeskStatus
from app.sevdesk_export_checks import export_blockers

LABEL = "IT-Consulting"


def _inv(**kw) -> PaperlessInvoice:
    return PaperlessInvoice(id=1, paperless_id=10, **kw)


def _m(kind: MatchKind, voucher_id: str = "V1", score: float | None = None):
    return InvoiceVoucherMatch(invoice_id=1, voucher_id=voucher_id, kind=kind, score=score)


def test_ohne_grund():
    b = export_blockers(_inv(), [], set(), context_label=LABEL)
    assert b.hard is None
    assert b.reasons == []


def test_empfaenger_gleich_kontext_ist_kein_grund_auch_andere_schreibweise():
    b = export_blockers(_inv(recipient_label="it-consulting"), [], set(), context_label=LABEL)
    assert b.hard is None and b.reasons == []


def test_id_treffer_im_abzug_ist_hart():
    b = export_blockers(_inv(), [_m(MatchKind.ID, "77")], {"77"}, context_label=LABEL)
    assert b.hard == "bereits in SevDesk (Beleg 77)"
    assert b.reasons == []


def test_id_treffer_ohne_beleg_im_abzug_ist_ebenfalls_hart():
    b = export_blockers(_inv(), [_m(MatchKind.ID, "77")], set(), context_label=LABEL)
    assert b.hard is not None and "77" in b.hard and "bereits exportiert" in b.hard


def test_vermerk_am_dokument_ohne_gespeicherten_treffer_ist_hart():
    b = export_blockers(_inv(paperless_voucher_ref=" 55 "), [], {"55"}, context_label=LABEL)
    assert b.hard == "bereits in SevDesk (Beleg 55)"


def test_bestaetigter_treffer_ist_hart():
    b = export_blockers(_inv(), [_m(MatchKind.CONFIRMED, "88", 0.7)], set(), context_label=LABEL)
    assert b.hard == "bereits in SevDesk (Beleg 88)"


def test_status_exported_exporting_uncertain_sind_hart():
    for status in (SevdeskStatus.EXPORTED, SevdeskStatus.EXPORTING, SevdeskStatus.UNCERTAIN):
        b = export_blockers(_inv(sevdesk_status=status), [], set(), context_label=LABEL)
        assert b.hard, status


def test_status_failed_review_queued_none_sind_nicht_hart():
    for status in (
        SevdeskStatus.NONE, SevdeskStatus.QUEUED, SevdeskStatus.FAILED,
        SevdeskStatus.REVIEW, SevdeskStatus.DISMISSED,
    ):  # fmt: skip
        b = export_blockers(_inv(sevdesk_status=status), [], set(), context_label=LABEL)
        assert b.hard is None, status


def test_similar_treffer_ist_rueckfragegrund_mit_id_und_score_hoechster_zuerst():
    matches = [_m(MatchKind.SIMILAR, "A", 0.5), _m(MatchKind.SIMILAR, "B", 0.875)]
    b = export_blockers(_inv(), matches, set(), context_label=LABEL)
    assert b.hard is None
    assert b.reasons == [
        "mögliche Dublette: Beleg B (Score 0,88)",
        "mögliche Dublette: Beleg A (Score 0,50)",
    ]


def test_verworfener_treffer_ist_kein_grund():
    b = export_blockers(_inv(), [_m(MatchKind.REJECTED, "R", 0.9)], set(), context_label=LABEL)
    assert b.hard is None and b.reasons == []


def test_abweichender_empfaenger_nennt_labelnamen():
    b = export_blockers(_inv(recipient_label="Familie"), [], set(), context_label=LABEL)
    assert b.hard is None
    assert len(b.reasons) == 1 and "Familie" in b.reasons[0] and LABEL in b.reasons[0]


def test_mehrere_gruende_werden_gesammelt():
    b = export_blockers(
        _inv(recipient_label="Familie"), [_m(MatchKind.SIMILAR, "A", 0.6)], set(),
        context_label=LABEL,
    )  # fmt: skip
    assert len(b.reasons) == 2


def test_harte_sperre_hat_vorrang_vor_rueckfragegruenden():
    b = export_blockers(
        _inv(recipient_label="Familie"),
        [_m(MatchKind.CONFIRMED, "88"), _m(MatchKind.SIMILAR, "A", 0.6)],
        set(),
        context_label=LABEL,
    )
    assert b.hard and b.reasons == []


def test_kontext_label_mit_rand_und_anderer_schreibweise_ist_kein_grund():
    b = export_blockers(
        _inv(recipient_label=" IT-CONSULTING "), [], set(), context_label="  it-consulting"
    )
    assert b.reasons == []
