"""Tests der reinen Matching-Logik (ohne I/O)."""

from datetime import datetime

from app.models import (
    InvoiceVoucherMatch,
    MatchKind,
    PaperlessInvoice,
    SevdeskStatus,
    SevdeskVoucher,
)
from app.sevdesk_matching import (
    MatchState,
    compute_matches,
    match_status_for,
    name_similarity,
    normalize_name,
)

W, M = 14, 0.4


def inv(i=1, **kw) -> PaperlessInvoice:
    kw.setdefault("paperless_id", i)
    kw.setdefault("amount", 112.0)
    kw.setdefault("document_date", datetime(2026, 10, 3))
    kw.setdefault("creditor_name", "Amazon Web Services")
    return PaperlessInvoice(id=i, **kw)


def vou(vid="V1", **kw) -> SevdeskVoucher:
    kw.setdefault("sum_gross", 112.0)
    kw.setdefault("voucher_date", "2026-10-04")
    kw.setdefault("supplier_name", "AWS EMEA SARL")
    kw.setdefault("currency", "EUR")
    return SevdeskVoucher(voucher_id=vid, **kw)


def run(invoices, vouchers, existing=()):
    return compute_matches(invoices, vouchers, existing, window_days=W, min_score=M)


def test_normalisierung():
    assert normalize_name("  Müller & Söhne GmbH. ") == "müller söhne"
    assert normalize_name("AWS EMEA SARL") == "aws emea"
    assert normalize_name(None) == ""


def test_namensaehnlichkeit():
    assert name_similarity("Hetzner Online GmbH", "hetzner online") == 1.0
    assert name_similarity("Hetzner", "Hetzner Online GmbH") == 1.0
    assert name_similarity(None, "x") == 0.0
    assert name_similarity("Amazon", "Telekom") < 0.4


def test_id_treffer_ueber_voucher_id_und_ref_mit_trim():
    a = inv(1, sevdesk_voucher_id="1234")
    b = inv(2, paperless_voucher_ref="  987 ")
    res = run([a, b], [vou("1234"), vou("987")])
    assert [(m.invoice_id, m.voucher_id, m.kind, m.score) for m in res] == [
        (1, "1234", MatchKind.ID, 1.0),
        (2, "987", MatchKind.ID, 1.0),
    ]


def test_id_treffer_auch_wenn_beleg_nicht_im_abzug():
    res = run([inv(1, sevdesk_voucher_id="1234")], [])
    assert [(m.voucher_id, m.kind) for m in res] == [("1234", MatchKind.ID)]


def test_id_treffer_stehen_vor_similar():
    res = run([inv(1), inv(2, sevdesk_voucher_id="X", amount=5.0)], [vou("V1")])
    assert [m.kind for m in res] == [MatchKind.ID, MatchKind.SIMILAR]


def test_aws_beispiel_ist_treffer():
    (m,) = run([inv(1)], [vou("V1")])
    assert (m.invoice_id, m.voucher_id, m.kind) == (1, "V1", MatchKind.SIMILAR)
    assert M <= m.score <= 1.0
    assert m.score == round(m.score, 3)


def test_ein_cent_abweichung_kein_treffer():
    assert run([inv(1)], [vou("V1", sum_gross=112.01)]) == []


def test_betrag_unbekannt_kein_similar():
    assert run([inv(1, amount=None)], [vou("V1")]) == []


def test_fremde_waehrung_kein_treffer_gross_klein_egal():
    assert run([inv(1)], [vou("V1", currency="USD")]) == []
    assert len(run([inv(1, currency="eur")], [vou("V1")])) == 1


def test_fenster_und_fehlende_daten():
    assert run([inv(1)], [vou("V1", voucher_date="2026-10-18")]) == []  # 15 Tage
    assert (
        len(
            run(
                [inv(1)],
                [vou("V1", voucher_date="2026-10-17", supplier_name="Amazon Web Services")],
            )
        )
        == 1
    )  # 14 Tage
    assert run([inv(1, document_date=None)], [vou("V1")]) == []
    assert run([inv(1)], [vou("V1", voucher_date=None)]) == []


def test_beleg_bereits_per_id_vergeben():
    a = inv(1, sevdesk_voucher_id="V1")
    b = inv(2)
    res = run([a, b], [vou("V1")])
    assert [(m.invoice_id, m.kind) for m in res] == [(1, MatchKind.ID)]


def test_beleg_bereits_bestaetigt_vergeben():
    conf = InvoiceVoucherMatch(invoice_id=1, voucher_id="V1", kind=MatchKind.CONFIRMED)
    res = run([inv(1), inv(2)], [vou("V1")], [conf])
    assert res == []  # Rechnung 1 hat confirmed, Beleg für Rechnung 2 vergeben


def test_rechnung_mit_confirmed_bekommt_kein_similar():
    conf = InvoiceVoucherMatch(invoice_id=1, voucher_id="V9", kind=MatchKind.CONFIRMED)
    assert run([inv(1)], [vou("V1")], [conf]) == []


def test_rejected_wird_nicht_wieder_vorgeschlagen_nur_fuer_diese_rechnung():
    rej = InvoiceVoucherMatch(invoice_id=1, voucher_id="V1", kind=MatchKind.REJECTED)
    res = run([inv(1), inv(2)], [vou("V1")], [rej])
    assert [(m.invoice_id, m.voucher_id) for m in res] == [(2, "V1")]


def test_summe_null_nie_kandidat():
    assert run([inv(1, amount=0.0)], [vou("V1", sum_gross=0.0)]) == []
    assert run([inv(1)], [vou("V1", sum_gross=None)]) == []


def test_uncertain_beleg_ohne_summe_ist_kandidat_per_namen():
    u = inv(1, sevdesk_status=SevdeskStatus.UNCERTAIN, creditor_name="AWS EMEA SARL")
    for summe in (None, 0.0):
        (m,) = run([u], [vou("V1", sum_gross=summe, voucher_date="2026-10-03")])
        assert (m.invoice_id, m.voucher_id, m.kind) == (1, "V1", MatchKind.SIMILAR)
        assert m.score == 1.0  # 0,6·1 + 0,4·1


def test_uncertain_beleg_ohne_summe_ist_kandidat_per_beschreibung():
    u = inv(1, sevdesk_status=SevdeskStatus.UNCERTAIN, title="Rechnung Oktober 4711")
    v = vou(
        "V1", sum_gross=None, voucher_date="2026-10-03", supplier_name="Völlig Anders",
        description="rechnung oktober 4711",
    )  # fmt: skip
    (m,) = run([u], [v])
    assert m.score == 1.0


def test_uncertain_ohne_summe_braucht_datum_im_fenster_und_aehnlichkeit():
    u = inv(1, sevdesk_status=SevdeskStatus.UNCERTAIN, title="Rechnung 4711")
    weit = vou("V1", sum_gross=None, voucher_date="2026-12-24")
    fremd = vou(
        "V2", sum_gross=None, voucher_date="2026-10-17", supplier_name="Völlig Anders",
        description="etwas ganz anderes",
    )  # fmt: skip
    assert run([u], [weit, fremd]) == []


def test_beleg_ohne_summe_bleibt_fuer_andere_status_ausgeschlossen():
    for status in (SevdeskStatus.NONE, SevdeskStatus.QUEUED, SevdeskStatus.FAILED):
        a = inv(1, sevdesk_status=status)
        assert run([a], [vou("V1", sum_gross=None, voucher_date="2026-10-03")]) == []


def test_uncertain_ohne_betrag_findet_beleg_ohne_summe():
    u = inv(1, sevdesk_status=SevdeskStatus.UNCERTAIN, amount=None)
    (m,) = run([u], [vou("V1", sum_gross=None, voucher_date="2026-10-03")])
    assert m.kind == MatchKind.SIMILAR


def test_mindestscore_filtert():
    v = vou("V1", supplier_name="Völlig Anders", voucher_date="2026-10-17")
    assert run([inv(1)], [v]) == []
    low = compute_matches([inv(1)], [v], [], window_days=W, min_score=0.0)
    assert len(low) == 1


def test_name_aus_korrespondent_zaehlt():
    a = inv(1, creditor_name=None, correspondent="AWS EMEA")
    (m,) = run([a], [vou("V1", voucher_date="2026-10-03")])
    assert m.score == 1.0


# match_status_for -----------------------------------------------------------------


def _m(kind, vid="V1", score=None, invoice_id=1):
    return InvoiceVoucherMatch(invoice_id=invoice_id, voucher_id=vid, kind=kind, score=score)


def test_status_unavailable():
    s = match_status_for(inv(1, sevdesk_voucher_id="1"), [], set(), False)
    assert s.state == MatchState.UNAVAILABLE


def test_status_in_sevdesk_per_id():
    s = match_status_for(inv(1), [_m(MatchKind.ID, "1", 1.0)], {"1"}, True)
    assert (s.state, s.voucher_id) == (MatchState.IN_SEVDESK, "1")


def test_status_in_sevdesk_per_confirmed_auch_ohne_cache():
    s = match_status_for(inv(1), [_m(MatchKind.CONFIRMED, "9")], set(), True)
    assert (s.state, s.voucher_id) == (MatchState.IN_SEVDESK, "9")


def test_status_missing_in_sevdesk():
    s = match_status_for(inv(1), [_m(MatchKind.ID, "1", 1.0)], {"2"}, True)
    assert (s.state, s.voucher_id) == (MatchState.MISSING_IN_SEVDESK, "1")


def test_status_possible_duplicate_bester_score():
    ms = [_m(MatchKind.SIMILAR, "A", 0.5), _m(MatchKind.SIMILAR, "B", 0.9)]
    s = match_status_for(inv(1), ms, {"A", "B"}, True)
    assert (s.state, s.voucher_id, s.score) == (MatchState.POSSIBLE_DUPLICATE, "B", 0.9)


def test_status_rejected_zaehlt_nicht_als_duplikat():
    s = match_status_for(inv(1), [_m(MatchKind.REJECTED)], {"V1"}, True)
    assert s.state == MatchState.NO_MATCH


def test_status_no_amount_und_no_match():
    assert match_status_for(inv(1, amount=None), [], set(), True).state == MatchState.NO_AMOUNT
    assert match_status_for(inv(1), [], set(), True).state == MatchState.NO_MATCH
