"""Zeilen der Export-Übersicht (`/invoices`): Einstufung, Abgleich und Export-Sperren.

Eine Hilfsfunktion baut die View-Models für Liste **und** Detailseite. Alles stammt aus
SQLite: Historie, Empfänger-Caches, Treffer und Belegabzug werden je Aufruf **einmal** für die
ganze geladene Menge abgefragt (nicht je Zeile). Es gibt keinen Paperless-, SevDesk- oder
KI-Aufruf beim Seitenaufruf (Design 2/3).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from .context_classification import ContextBucket, classify, context_bucket
from .models import (
    ContextAssessment,
    InvoiceVoucherMatch,
    MatchKind,
    PaperlessInvoice,
    SevdeskStatus,
    SevdeskSyncState,
    SevdeskVoucher,
)
from .repository import Repository
from .sevdesk_export_checks import ExportBlockers, export_blockers
from .sevdesk_matching import MatchState, MatchStatus, match_status_for

# Link auf einen Beleg in SevDesk (Bearbeiten-Ansicht).
SEVDESK_VOUCHER_URL = "https://my.sevdesk.de/fi/edit/type/VOU/id/{id}"

# Filter-Obergrenze: Einstufung und Abgleich laufen in Python über die geladene Menge
# (Design 3); bei aktivem Filter wird deshalb mehr geladen als die ungefilterte Liste zeigt.
UNFILTERED_LIMIT = 200
FILTERED_LIMIT = 5000


@dataclass
class OverviewFilters:
    """Wirksame, kombinierbare Filter der Export-Übersicht."""

    ctx_it: bool = False  # Kontext-Bucket „it“ (ab Schwelle)
    open_only: bool = False  # nicht exportiert und kein Treffer in SevDesk
    duplicate: bool = False  # mögliche Dublette
    review: bool = False  # Status „zu prüfen“

    @property
    def needs_python(self) -> bool:
        """Filter, die nur über die berechneten Zeilen auszuwerten sind."""
        return self.ctx_it or self.open_only or self.duplicate

    @property
    def active(self) -> bool:
        return self.ctx_it or self.open_only or self.duplicate or self.review


@dataclass
class InvoiceRow:
    """Eine Rechnung mit allem, was die Übersicht und die Detailseite zusätzlich zeigen."""

    inv: PaperlessInvoice
    assessment: ContextAssessment
    bucket: ContextBucket
    match: MatchStatus
    blockers: ExportBlockers
    matches: list[InvoiceVoucherMatch] = field(default_factory=list)

    @property
    def exportable(self) -> bool:
        """Nicht hart gesperrt (Rückfragegründe sperren nicht, sie verlangen Bestätigung)."""
        return self.blockers.hard is None


@dataclass
class SevdeskCandidate:
    """Offener ähnlicher Treffer samt Beleg für die Detailseite."""

    match: InvoiceVoucherMatch
    voucher: SevdeskVoucher | None
    url: str


@dataclass
class Overview:
    rows: list[InvoiceRow]
    sync_state: SevdeskSyncState
    sync_available: bool


def build_rows(
    repo: Repository,
    invoices: list[PaperlessInvoice],
    *,
    context_label: str,
    threshold: float,
    option_available: bool | None,
) -> Overview:
    """Berechnet Einstufung, Abgleich und Sperren für ``invoices`` mit je einer Abfrage.

    ``option_available``: ``None`` = unbekannt → die Option gilt als vorhanden (die
    Einstufung wird angezeigt); nur ein sicheres ``False`` führt zu „nicht einstufbar“.
    """
    history = repo.correspondent_context_history(context_label)
    caches = repo.get_recipient_caches([i.paperless_id for i in invoices])
    by_invoice: dict[int, list[InvoiceVoucherMatch]] = defaultdict(list)
    for m in repo.list_matches([i.id for i in invoices]):
        by_invoice[m.invoice_id].append(m)
    voucher_ids = {v.voucher_id for v in repo.list_vouchers()}
    state = repo.get_sevdesk_sync_state()
    sync_available = state.last_success_at is not None

    rows: list[InvoiceRow] = []
    for inv in invoices:
        matches = by_invoice.get(inv.id, [])
        assessment = classify(
            inv,
            history,
            caches.get(inv.paperless_id),
            context_label=context_label,
            option_available=option_available is not False,
        )
        rows.append(
            InvoiceRow(
                inv=inv,
                assessment=assessment,
                bucket=context_bucket(assessment, threshold),
                match=match_status_for(inv, matches, voucher_ids, sync_available),
                blockers=export_blockers(inv, matches, voucher_ids, context_label=context_label),
                matches=matches,
            )
        )
    return Overview(rows=rows, sync_state=state, sync_available=sync_available)


def apply_filters(rows: list[InvoiceRow], filters: OverviewFilters) -> list[InvoiceRow]:
    """Wendet die Python-seitigen Filter an (kombiniert mit UND)."""
    result = rows
    if filters.ctx_it:
        result = [r for r in result if r.bucket == "it"]
    if filters.open_only:
        result = [
            r
            for r in result
            if r.exportable
            and r.inv.sevdesk_status != SevdeskStatus.EXPORTED
            and r.match.state != MatchState.IN_SEVDESK
        ]
    if filters.duplicate:
        result = [r for r in result if r.match.state == MatchState.POSSIBLE_DUPLICATE]
    return result


def candidates_of(repo: Repository, row: InvoiceRow) -> list[SevdeskCandidate]:
    """Alle offenen ähnlichen Treffer einer Rechnung (Detailseite), beste zuerst."""
    similar = sorted(
        (m for m in row.matches if m.kind == MatchKind.SIMILAR),
        key=lambda m: (-(m.score or 0.0), m.voucher_id),
    )
    return [
        SevdeskCandidate(
            match=m,
            voucher=repo.get_voucher(m.voucher_id),
            url=SEVDESK_VOUCHER_URL.format(id=m.voucher_id),
        )
        for m in similar
    ]
