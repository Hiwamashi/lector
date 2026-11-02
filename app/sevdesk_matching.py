"""Reine Matching-Logik zwischen Paperless-Rechnungen und SevDesk-Belegen (ohne I/O).

``compute_matches`` liefert die automatischen Treffer (``id`` und ``similar``); die
Entscheidungen des Nutzers (``confirmed``/``rejected``) kommen als ``existing_matches``
herein und werden nie neu ausgegeben. Siehe Design, Entscheidung 6.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from difflib import SequenceMatcher
from enum import StrEnum

from app.models import (
    InvoiceVoucherMatch,
    MatchKind,
    PaperlessInvoice,
    SevdeskStatus,
    SevdeskVoucher,
)

_AMOUNT_TOLERANCE = 0.005
_LEGAL_FORMS = frozenset(
    {
        "gmbh", "ag", "ug", "kg", "se", "sarl", "sàrl", "sa", "ltd", "limited",
        "inc", "llc", "bv", "co",
    }
)  # fmt: skip


def normalize_name(name: str | None) -> str:
    """Kleinschreibung, ohne Satzzeichen, `&` und Rechtsformen, Leerzeichen zusammengezogen."""
    if not name:
        return ""
    text = name.lower().replace("&", " ")
    text = re.sub(r"[^\w\s]|_", " ", text)
    return " ".join(t for t in text.split() if t not in _LEGAL_FORMS)


def name_similarity(a: str | None, b: str | None) -> float:
    """Maximum aus Token-Überdeckung und SequenceMatcher-Ratio (0..1)."""
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return 0.0
    ta, tb = set(na.split()), set(nb.split())
    overlap = len(ta & tb) / min(len(ta), len(tb))
    return max(overlap, SequenceMatcher(None, na, nb).ratio())


def _invoice_voucher_ref(invoice: PaperlessInvoice) -> str | None:
    for value in (invoice.sevdesk_voucher_id, invoice.paperless_voucher_ref):
        if value and value.strip():
            return value.strip()
    return None


def _invoice_day(invoice: PaperlessInvoice) -> date | None:
    d = invoice.document_date
    return d.date() if d is not None and hasattr(d, "hour") else d


def _voucher_day(voucher: SevdeskVoucher) -> date | None:
    if not voucher.voucher_date:
        return None
    try:
        return date.fromisoformat(voucher.voucher_date[:10])
    except ValueError:
        return None


def _invoice_similarity(invoice: PaperlessInvoice, voucher: SevdeskVoucher) -> float:
    return max(
        name_similarity(invoice.creditor_name, voucher.supplier_name),
        name_similarity(invoice.correspondent, voucher.supplier_name),
    )


def _description_similarity(invoice: PaperlessInvoice, voucher: SevdeskVoucher) -> float:
    """Beschreibung des Belegs gegen den Rechnungstitel (der Export schickt den Titel mit)."""
    return name_similarity(invoice.title, voucher.description)


def _has_sum(voucher: SevdeskVoucher) -> bool:
    return voucher.sum_gross is not None and abs(voucher.sum_gross) >= _AMOUNT_TOLERANCE


def compute_matches(
    invoices: Iterable[PaperlessInvoice],
    vouchers: Iterable[SevdeskVoucher],
    existing_matches: Iterable[InvoiceVoucherMatch],
    *,
    window_days: int,
    min_score: float,
) -> list[InvoiceVoucherMatch]:
    """Automatische Treffer: zuerst alle ``id``-Treffer, danach die ``similar``-Treffer.

    Belege ohne Summe (0/``None``) bleiben für gewöhnliche Rechnungen ausgeschlossen. Nur für
    Rechnungen im Status ``uncertain`` kommen sie in Frage: Ein Export mit unklarem Ausgang
    hat den Beleg womöglich ohne Betrag angelegt. Dann zählen Datum im Fenster plus
    Namens- oder Beschreibungsähnlichkeit statt des Betrags.
    """
    invoices = list(invoices)
    vouchers = list(vouchers)
    existing = list(existing_matches)

    id_matches: list[InvoiceVoucherMatch] = []
    id_invoices: set[int] = set()
    taken: set[str] = set()  # per id oder bestätigt vergebene Belege
    for inv in invoices:
        ref = _invoice_voucher_ref(inv)
        if ref is not None:
            id_matches.append(
                InvoiceVoucherMatch(invoice_id=inv.id, voucher_id=ref, kind=MatchKind.ID, score=1.0)
            )
            id_invoices.add(inv.id)
            taken.add(ref)

    confirmed_invoices: set[int] = set()
    rejected: set[tuple[int, str]] = set()
    for m in existing:
        if m.kind == MatchKind.CONFIRMED:
            confirmed_invoices.add(m.invoice_id)
            taken.add(m.voucher_id)
        elif m.kind == MatchKind.REJECTED:
            rejected.add((m.invoice_id, m.voucher_id))

    candidates = []
    for v in vouchers:
        vday = _voucher_day(v)
        if v.voucher_id in taken or vday is None:
            continue
        candidates.append((v, vday))

    similar: list[InvoiceVoucherMatch] = []
    for inv in invoices:
        if inv.id in id_invoices or inv.id in confirmed_invoices:
            continue
        uncertain = inv.sevdesk_status == SevdeskStatus.UNCERTAIN
        if inv.amount is None and not uncertain:
            continue
        iday = _invoice_day(inv)
        if iday is None:
            continue
        currency = (inv.currency or "").casefold()
        for v, vday in candidates:
            if (inv.id, v.voucher_id) in rejected:
                continue
            if _has_sum(v):
                if inv.amount is None or abs(v.sum_gross - inv.amount) >= _AMOUNT_TOLERANCE:
                    continue
                if (v.currency or "").casefold() != currency:
                    continue
                similarity = _invoice_similarity(inv, v)
            elif uncertain:
                similarity = max(_invoice_similarity(inv, v), _description_similarity(inv, v))
            else:
                continue
            delta = abs((vday - iday).days)
            if delta > window_days:
                continue
            day_part = 1.0 - delta / window_days if window_days > 0 else 1.0
            score = round(0.6 * day_part + 0.4 * similarity, 3)
            if score >= min_score:
                similar.append(
                    InvoiceVoucherMatch(
                        invoice_id=inv.id, voucher_id=v.voucher_id,
                        kind=MatchKind.SIMILAR, score=score,
                    )
                )  # fmt: skip
    return id_matches + similar


class MatchState(StrEnum):
    UNAVAILABLE = "unavailable"  # Abzug noch nie abgerufen
    IN_SEVDESK = "in_sevdesk"  # sicher oder bestätigt, Beleg im Abzug
    MISSING_IN_SEVDESK = "missing_in_sevdesk"  # ID vermerkt, Beleg nicht im Abzug
    POSSIBLE_DUPLICATE = "possible_duplicate"  # offener ähnlicher Treffer
    NO_AMOUNT = "no_amount"  # ohne Betrag nicht prüfbar
    NO_MATCH = "no_match"


@dataclass(frozen=True)
class MatchStatus:
    state: MatchState
    voucher_id: str | None = None
    score: float | None = None


def match_status_for(
    invoice: PaperlessInvoice,
    matches_of_invoice: Iterable[InvoiceVoucherMatch],
    voucher_ids_in_cache: Iterable[str] | set[str],
    sync_available: bool,
) -> MatchStatus:
    """Anzeigezustand einer Rechnung für die Übersicht."""
    if not sync_available:
        return MatchStatus(MatchState.UNAVAILABLE)
    matches = list(matches_of_invoice)
    cache = (
        voucher_ids_in_cache if isinstance(voucher_ids_in_cache, set) else set(voucher_ids_in_cache)
    )

    for m in matches:
        if m.kind == MatchKind.CONFIRMED:
            return MatchStatus(MatchState.IN_SEVDESK, m.voucher_id, m.score)

    ref = next((m.voucher_id for m in matches if m.kind == MatchKind.ID), None)
    ref = ref or _invoice_voucher_ref(invoice)
    if ref is not None:
        state = MatchState.IN_SEVDESK if ref in cache else MatchState.MISSING_IN_SEVDESK
        return MatchStatus(state, ref, 1.0)

    similar = [m for m in matches if m.kind == MatchKind.SIMILAR]
    if similar:
        best = max(similar, key=lambda m: m.score or 0.0)
        return MatchStatus(MatchState.POSSIBLE_DUPLICATE, best.voucher_id, best.score)

    if invoice.amount is None:
        return MatchStatus(MatchState.NO_AMOUNT)
    return MatchStatus(MatchState.NO_MATCH)
