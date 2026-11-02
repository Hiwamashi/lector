"""Prüfungen vor dem SevDesk-Export (rein, ohne I/O) und das Ergebnisobjekt des Exports.

``export_blockers`` wird von der Übersicht, vom Mehrfachexport und vom Tag-Weg gleich
verwendet (Design 7). Es trennt zwei Arten von Gründen:

- ``hard``: Der Export ist gesperrt, eine Bestätigung ändert daran nichts.
- ``reasons``: Rückfragegründe; exportiert wird erst nach ausdrücklicher Bestätigung.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum

from app.context_classification import same_label
from app.models import InvoiceVoucherMatch, MatchKind, PaperlessInvoice, SevdeskStatus


@dataclass(frozen=True)
class ExportBlockers:
    hard: str | None = None
    reasons: list[str] = field(default_factory=list)


class ExportStatus(StrEnum):
    EXPORTED = "exported"  # Beleg angelegt
    BLOCKED = "blocked"  # harte Sperre, nichts geändert
    NEEDS_CONFIRMATION = "needs_confirmation"  # Rückfragegründe, ohne ``confirmed`` nichts getan
    FAILED = "failed"  # eindeutig fehlgeschlagen (kein Beleg), erneut exportierbar
    UNCERTAIN = "uncertain"  # Ausgang unklar, nicht automatisch erneut exportieren
    SKIPPED = "skipped"  # nichts getan (unbekannte Rechnung, Claim verloren, Mehrfachexport)


@dataclass(frozen=True)
class ExportOutcome:
    status: ExportStatus
    message: str = ""
    reasons: list[str] = field(default_factory=list)
    voucher_id: str | None = None


def _score_text(score: float | None) -> str:
    return "" if score is None else f"{score:.2f}".replace(".", ",")


def export_blockers(
    invoice: PaperlessInvoice,
    matches_of_invoice: Iterable[InvoiceVoucherMatch],
    voucher_ids_in_cache: Iterable[str] | set[str],
    *,
    context_label: str,
) -> ExportBlockers:
    """Harte Sperre und Rückfragegründe für den Export einer Rechnung.

    Hart gesperrt ist die Rechnung bei Status ``exported``/``exporting``/``uncertain``, bei
    einem bestätigten Treffer und bei einem ``id``-Treffer (Beleg-ID aus Export oder
    Paperless-Vermerk). Ein ``id``-Treffer, dessen Beleg im Abzug FEHLT, sperrt ebenfalls:
    Die Rechnung wurde dann schon einmal exportiert, der Beleg ist in SevDesk vermutlich nur
    gelöscht oder noch nicht abgerufen — ein erneuter Export würde bei Letzterem einen
    Doppel-Beleg erzeugen und bei Ersterem eine bewusste Löschung übergehen. Wer neu
    exportieren will, entfernt den Vermerk bewusst in Paperless.

    Rückfragegründe sind offene ``similar``-Treffer (mit Beleg-ID und Score) und ein
    gesetzter Empfänger, der nicht dem Kontext-Label entspricht.
    """
    matches = list(matches_of_invoice)
    cache = (
        voucher_ids_in_cache if isinstance(voucher_ids_in_cache, set) else set(voucher_ids_in_cache)
    )

    status = invoice.sevdesk_status
    if status == SevdeskStatus.EXPORTED:
        suffix = f" (Beleg {invoice.sevdesk_voucher_id})" if invoice.sevdesk_voucher_id else ""
        return ExportBlockers(hard=f"bereits exportiert{suffix}")
    if status == SevdeskStatus.EXPORTING:
        return ExportBlockers(hard="Export läuft bereits")
    if status == SevdeskStatus.UNCERTAIN:
        return ExportBlockers(
            hard="Ausgang des letzten Exports unklar — in SevDesk prüfen, ob der Beleg existiert"
        )

    for m in matches:
        if m.kind == MatchKind.CONFIRMED:
            return ExportBlockers(hard=f"bereits in SevDesk (Beleg {m.voucher_id})")

    ref = next((m.voucher_id for m in matches if m.kind == MatchKind.ID), None)
    for value in (ref, invoice.sevdesk_voucher_id, invoice.paperless_voucher_ref):
        if value and value.strip():
            ref = value.strip()
            break
    if ref:
        if ref in cache:
            return ExportBlockers(hard=f"bereits in SevDesk (Beleg {ref})")
        return ExportBlockers(
            hard=(
                f"Beleg {ref} ist vermerkt, im SevDesk-Abzug aber nicht zu finden — "
                "die Rechnung wurde bereits exportiert"
            )
        )

    reasons: list[str] = []
    similar = sorted(
        (m for m in matches if m.kind == MatchKind.SIMILAR),
        key=lambda m: (-(m.score or 0.0), m.voucher_id),
    )
    for m in similar:
        reasons.append(f"mögliche Dublette: Beleg {m.voucher_id} (Score {_score_text(m.score)})")

    label = (invoice.recipient_label or "").strip()
    if label and not same_label(label, context_label):
        reasons.append(f"anderer Empfänger: {label} (nicht {context_label})")

    return ExportBlockers(reasons=reasons)
