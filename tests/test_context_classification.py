"""Tests der Kontext-Einstufung (Rangfolge, Historie, Schwelle)."""

from __future__ import annotations

import pytest

from app.context_classification import classify, context_bucket, same_label
from app.models import (
    ContextAssessment,
    ContextSource,
    CorrespondentHistory,
    PaperlessInvoice,
    RecipientCache,
)

LABEL = "IT-Consulting"


def _inv(id_=1, *, recipient=None, correspondent="Hetzner"):
    return PaperlessInvoice(
        id=id_, paperless_id=id_ * 10, correspondent=correspondent, recipient_label=recipient
    )


def _cl(inv, history=None, cache=None, available=True):
    return classify(
        inv, history or {}, cache, context_label=LABEL, option_available=available
    )


def _hist(it=(), other=()):
    return {"Hetzner": CorrespondentHistory(frozenset(it), frozenset(other))}


def test_option_fehlt_ist_nicht_einstufbar():
    a = _cl(_inv(recipient=LABEL), available=False)
    assert a.source == ContextSource.UNAVAILABLE
    assert a.confidence is None


def test_empfaenger_schlaegt_ki():
    cache = RecipientCache(paperless_id=10, it_probability=0.9)
    a = _cl(_inv(recipient="Familie"), cache=cache)
    assert (a.confidence, a.source, a.detail) == (0.0, ContextSource.RECIPIENT, "Familie")


def test_empfaenger_kontext_ist_eins():
    a = _cl(_inv(recipient=LABEL))
    assert a.confidence == 1.0
    assert a.source == ContextSource.RECIPIENT


def test_historie_drei_von_drei():
    a = _cl(_inv(), _hist(it={2, 3, 4}))
    assert a.confidence == 0.95
    assert a.source == ContextSource.CORRESPONDENT
    assert a.detail == "3/3 IT-Consulting"


def test_historie_zwei_von_zwei():
    assert _cl(_inv(), _hist(it={2, 3})).confidence == 0.9


def test_historie_andere_richtung():
    a = _cl(_inv(), _hist(other={2, 3}))
    assert a.confidence == 0.1
    assert a.detail == "2/2 anderer Empfänger"
    assert _cl(_inv(), _hist(other={2, 3, 4})).confidence == 0.05


def test_widerspruechliche_historie_faellt_auf_ki():
    cache = RecipientCache(paperless_id=10, it_probability=0.6, reasoning="Hosting")
    a = _cl(_inv(), _hist(it={2}, other={3}), cache=cache)
    assert (a.confidence, a.source, a.detail) == (0.6, ContextSource.LLM, "Hosting")


def test_zu_kleine_historie_wird_nicht_verwendet():
    assert _cl(_inv(), _hist(it={2})).source == ContextSource.NONE


def test_aktuelle_rechnung_wird_aus_eigener_historie_ausgeschlossen():
    # Mit der eigenen Rechnung wären es 2 Einträge; ohne sie nur einer -> keine Quelle.
    a = _cl(_inv(id_=1), _hist(it={1, 2}))
    assert a.source == ContextSource.NONE
    # Eigene Rechnung in der Gegenrichtung stört den Befund nicht.
    b = _cl(_inv(id_=1), _hist(it={2, 3}, other={1}))
    assert b.source == ContextSource.CORRESPONDENT
    assert b.confidence == 0.9


def test_ohne_korrespondent_keine_historie():
    a = _cl(_inv(correspondent=None), _hist(it={2, 3, 4}))
    assert a.source == ContextSource.NONE


@pytest.mark.parametrize("value", [None, 1.4, -0.1, float("nan")])
def test_ungueltige_ki_wert_zaehlt_nicht(value):
    cache = RecipientCache(paperless_id=10, it_probability=value)
    assert _cl(_inv(), cache=cache).source == ContextSource.NONE


def test_keine_quelle():
    a = _cl(_inv())
    assert (a.confidence, a.source) == (None, ContextSource.NONE)


def test_schwelle_ki():
    hoch = ContextAssessment(0.91, ContextSource.LLM)
    mittel = ContextAssessment(0.6, ContextSource.LLM)
    assert context_bucket(hoch, 0.75) == "it"
    assert context_bucket(mittel, 0.75) == "unsure"
    assert context_bucket(ContextAssessment(0.0, ContextSource.LLM), 0.75) == "not_it"


def test_bucket_deterministische_quellen():
    assert context_bucket(ContextAssessment(1.0, ContextSource.RECIPIENT), 0.75) == "it"
    assert context_bucket(ContextAssessment(0.0, ContextSource.RECIPIENT), 0.75) == "not_it"
    assert context_bucket(ContextAssessment(0.95, ContextSource.CORRESPONDENT), 0.75) == "it"
    assert context_bucket(ContextAssessment(0.1, ContextSource.CORRESPONDENT), 0.75) == "not_it"
    assert context_bucket(ContextAssessment(0.05, ContextSource.CORRESPONDENT), 0.75) == "not_it"
    # Auch bei hoher Schwelle bleibt die IT-Richtung der Historie "unsicher", nie "not_it".
    assert context_bucket(ContextAssessment(0.95, ContextSource.CORRESPONDENT), 0.99) == "unsure"


def test_bucket_unbekannt():
    assert context_bucket(ContextAssessment(None, ContextSource.NONE), 0.75) == "unknown"
    assert context_bucket(ContextAssessment(None, ContextSource.UNAVAILABLE), 0.75) == "unknown"


def test_empfaenger_label_wird_ohne_gross_klein_und_rand_verglichen():
    a = _cl(_inv(recipient=" it-consulting "))
    assert (a.confidence, a.source) == (1.0, ContextSource.RECIPIENT)


def test_same_label():
    assert same_label(" IT-Consulting", "it-consulting\t")
    assert not same_label("Familie", "IT-Consulting")
    assert not same_label("", "")
    assert not same_label(None, "IT-Consulting")
