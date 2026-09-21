"""Hält die vier Stellen zusammen, an denen die Zustandsmenge redundant gepflegt ist.

`DocStatus` ist die Quelle; Label, Kachelreihenfolge und die beiden CSS-Regeln je Zustand
leben getrennt davon in `app/main.py`, `dashboard.html` und `app.css`. Ein vergessener
Eintrag knallt nicht — er geht still daneben: eine Kachel ohne Farbe, ein Zustand, der im
Filter fehlt. Die Spec `verarbeitungs-historie` verlangt ausdrücklich, dass kein Zustand nur
in der Datenbank existiert; dieser Test ist ihre Prüfung.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.main import STATUS_LABELS
from app.models import DocStatus

APP_DIR = Path(__file__).resolve().parents[1] / "app"
CSS_RAW = (APP_DIR / "static" / "app.css").read_text(encoding="utf-8")
# Ohne die Kommentare zu entfernen, würde ein Selektor, der nur in einem Kommentar
# vorkommt, als vorhanden gelten — die Suche liefe über den Kommentar hinweg bis zur
# nächsten echten Regel und prüfte deren Rumpf.
CSS = re.sub(r"/\*.*?\*/", "", CSS_RAW, flags=re.S)
DASHBOARD = (APP_DIR / "templates" / "dashboard.html").read_text(encoding="utf-8")


def _tile_order() -> list[str]:
    match = re.search(r"set tile_order\s*=\s*\[(.*?)\]", DASHBOARD, re.S)
    assert match, "tile_order nicht in dashboard.html gefunden"
    return re.findall(r'"([^"]+)"', match.group(1))


@pytest.mark.parametrize("status", list(DocStatus))
def test_every_status_has_a_label(status):
    assert status in STATUS_LABELS
    assert STATUS_LABELS[status].strip()


@pytest.mark.parametrize("status", list(DocStatus))
def test_every_status_has_a_tile(status):
    assert status.value in _tile_order()


def _rule_body(selector: str) -> str:
    """Liefert den Rumpf einer CSS-Regel — und fällt durch, wenn es sie nicht gibt.

    Bewusst nicht als Teilstringsuche über die ganze Datei: Ein Treffer in einem
    Kommentar wäre sonst genauso grün wie eine echte Deklaration.
    """
    match = re.search(re.escape(selector) + r"(?=[\s{,])[^{};]*\{([^}]*)\}", CSS)
    assert match, f"Keine CSS-Regel für {selector}"
    return match.group(1)


def _token_sections() -> tuple[str, str]:
    """Teilt das Stylesheet in den hellen und den dunklen Tokenblock."""
    marker = "@media (prefers-color-scheme: dark)"
    assert marker in CSS, "Dunkel-Modus-Block nicht gefunden"
    hell, _, rest = CSS.partition(marker)
    # Der Tokenblock endet vor der ersten Regel danach.
    dunkel = rest.split("* { box-sizing", 1)[0]
    assert "--bg:" in dunkel, "Struktur des Dunkel-Blocks hat sich geändert"
    return hell, dunkel


@pytest.mark.parametrize("status", list(DocStatus))
def test_every_status_has_tile_and_badge_css(status):
    assert _rule_body(f".tile--{status.value}").strip()
    assert _rule_body(f".badge--{status.value}").strip()


@pytest.mark.parametrize("status", list(DocStatus))
def test_status_colors_are_defined_in_both_themes(status):
    """Ein Farbton, den nur der helle Block kennt, bricht den Dunkel-Modus still —
    genau davor warnt der Kopfkommentar des Stylesheets."""
    hell, dunkel = _token_sections()
    used = set()
    for selector in (f".tile--{status.value}", f".badge--{status.value}"):
        used.update(re.findall(r"var\((--[\w-]+)\)", _rule_body(selector)))

    assert used, f"{status.value} nutzt gar kein Farbtoken"
    for token in used:
        assert f"{token}:" in hell, f"{token} fehlt im hellen Tokenblock"
        assert f"{token}:" in dunkel, f"{token} fehlt im Dunkel-Modus"


def test_tile_order_holds_no_unknown_status():
    known = {s.value for s in DocStatus}
    assert set(_tile_order()) <= known
