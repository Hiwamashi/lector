"""Einstufung einer Rechnung gegen den Geschäftskontext (z. B. „IT-Consulting“).

Die Einstufung wird beim Lesen berechnet und nicht gespeichert (siehe OpenSpec-Change
``sevdesk-export-uebersicht``, Design 3). Feste Rangfolge der Quellen:

1. Empfänger-Feld am Dokument (maßgeblich),
2. Historie des Korrespondenten (mindestens zwei andere, eindeutig entschiedene Rechnungen),
3. KI-Einschätzung aus dem Empfänger-Cache.
"""

from __future__ import annotations

from typing import Literal

from .models import (
    ContextAssessment,
    ContextSource,
    CorrespondentHistory,
    PaperlessInvoice,
    RecipientCache,
)

ContextBucket = Literal["it", "unsure", "not_it", "unknown"]

# Mindestzahl anderer entschiedener Rechnungen, damit die Historie zählt.
_MIN_HISTORY = 2
# Unterhalb dieser Konfidenz zeigt eine deterministische Quelle (Empfänger/Korrespondent)
# in Richtung „anderer Empfänger“.
_OTHER_DIRECTION_MAX = 0.5


def same_label(a: str | None, b: str | None) -> bool:
    """Vergleicht zwei Empfänger-Labels ohne Groß-/Kleinschreibung und Randleerraum.

    Leere Labels sind nie gleich — „kein Empfänger“ entspricht keinem Kontext.
    """
    na, nb = (a or "").strip().casefold(), (b or "").strip().casefold()
    return bool(na) and na == nb


def _from_recipient(invoice: PaperlessInvoice, context_label: str) -> ContextAssessment | None:
    label = invoice.recipient_label
    if not label:
        return None
    return ContextAssessment(
        confidence=1.0 if same_label(label, context_label) else 0.0,
        source=ContextSource.RECIPIENT,
        detail=label,
    )


def _from_correspondent(
    invoice: PaperlessInvoice,
    history: dict[str, CorrespondentHistory],
    context_label: str,
) -> ContextAssessment | None:
    if not invoice.correspondent:
        return None
    entry = history.get(invoice.correspondent)
    if entry is None:
        return None
    # Die bewertete Rechnung darf sich nicht selbst bestätigen.
    it = entry.it_ids - {invoice.id}
    other = entry.other_ids - {invoice.id}
    total = len(it) + len(other)
    if total < _MIN_HISTORY or (it and other):
        return None
    if it:
        return ContextAssessment(
            confidence=0.95 if total >= 3 else 0.9,
            source=ContextSource.CORRESPONDENT,
            detail=f"{total}/{total} {context_label}",
        )
    return ContextAssessment(
        confidence=0.05 if total >= 3 else 0.1,
        source=ContextSource.CORRESPONDENT,
        detail=f"{total}/{total} anderer Empfänger",
    )


def _from_llm(cache: RecipientCache | None) -> ContextAssessment | None:
    if cache is None:
        return None
    value = cache.it_probability
    if value is None or not (0.0 <= value <= 1.0):  # NaN fällt ebenfalls durch
        return None
    return ContextAssessment(
        confidence=float(value), source=ContextSource.LLM, detail=cache.reasoning or None
    )


def classify(
    invoice: PaperlessInvoice,
    history: dict[str, CorrespondentHistory],
    cache: RecipientCache | None,
    *,
    context_label: str,
    option_available: bool,
) -> ContextAssessment:
    """Stuft die Rechnung ein; die erste zutreffende Quelle der Rangfolge gewinnt."""
    if not option_available:
        return ContextAssessment(confidence=None, source=ContextSource.UNAVAILABLE)
    for result in (
        _from_recipient(invoice, context_label),
        _from_correspondent(invoice, history, context_label),
        _from_llm(cache),
    ):
        if result is not None:
            return result
    return ContextAssessment(confidence=None, source=ContextSource.NONE)


def context_bucket(assessment: ContextAssessment, threshold: float) -> ContextBucket:
    """Ordnet eine Einstufung einem Filter-Bereich der Übersicht zu.

    - ``unknown``: keine Konfidenz (Quelle ``none`` oder ``unavailable``).
    - ``it``: Konfidenz >= ``threshold``.
    - ``not_it``: Konfidenz 0, sowie bei den deterministischen Quellen Empfänger und
      Korrespondent jede Konfidenz unter 0,5. Deren „anderer“-Richtung liefert 0,0 / 0,1 /
      0,05 und ist eine Entscheidung, keine Unsicherheit.
    - ``unsure``: übrige Werte zwischen 0 und der Schwelle, in der Praxis nur KI-Werte.
    """
    conf = assessment.confidence
    if conf is None:
        return "unknown"
    if conf >= threshold:
        return "it"
    if conf == 0:
        return "not_it"
    if (
        assessment.source in (ContextSource.RECIPIENT, ContextSource.CORRESPONDENT)
        and conf < _OTHER_DIRECTION_MAX
    ):
        return "not_it"
    return "unsure"
