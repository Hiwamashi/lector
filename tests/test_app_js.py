"""Prüft die Live-Update-Logik in ``app/static/app.js`` über einen Node-Harness.

Das UI hat kein JS-Testframework (bewusst kein Node-Buildchain). Die Zustandsführung des
Veraltet-Hinweises ist aber zweimal in Folge falsch gewesen — einmal wurden Fehler ganz
verschluckt, einmal blendete ein erfolgreicher Parallel-Request den Hinweis trotz eines
fehlgeschlagenen wieder aus. Deshalb hier ein minimaler Harness mit gefaktem DOM, analog zu
``test_push_image_script.py``, das ebenfalls ein Nicht-Python-Artefakt prüft.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

APP_JS = Path(__file__).resolve().parents[1] / "app" / "static" / "app.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node nicht verfügbar")

HARNESS = """
const fs = require("fs");
const scenario = JSON.parse(process.argv[2]);

let hidden = true;               // Ausgangszustand des Hinweises
const liveStatus = { set hidden(v) { hidden = v; }, get hidden() { return hidden; } };

let tbodyInhalt = null;
const tbody = { set innerHTML(v) { tbodyInhalt = v; }, get innerHTML() { return tbodyInhalt; } };
const table = {
  getAttribute: () => "/fragment/empfaenger",
  querySelector: () => tbody,
};

const batchStatus = { getAttribute: () => "/fragment/empfaenger/batch-status",
                      set innerHTML(_v) {} };

global.document = {
  querySelector: (sel) => (sel.startsWith("table.history") ? table : null),
  getElementById: (id) => {
    if (id === "live-status") return liveStatus;
    // Zweites Fragment nur, wenn das Szenario es verlangt — so laufen wahlweise
    // ein oder zwei Requests parallel.
    if (id === "batch-status" && scenario.withBatchStatus) return batchStatus;
    return null;
  },
};
global.window = { EventSource: function () {}, location: { pathname: "/empfaenger" } };

// Reihenfolge der Antworten laut Szenario; "ok" = 200, sonst Fehlerstatus.
let i = 0;
global.fetch = (_url, _opts) => {
  const n = i++;
  const ok = scenario.responses[n];
  const delay = (scenario.delays || [])[n] || 0;
  const inhalt = (scenario.bodies || [])[n] || "<tr></tr>";
  const body = () => Promise.resolve(inhalt);
  const res = { ok: ok, status: ok ? 200 : 503, text: body };
  return new Promise((r) => setTimeout(() => r(res), delay));
};

let sse = null;
global.EventSource = function () { sse = this; };
window.EventSource = global.EventSource;

eval(fs.readFileSync(process.argv[3], "utf8"));

(async () => {
  if (scenario.streamDown) sse.onerror();
  sse.onmessage({ data: "batch:recipient" });
  if (scenario.secondCycleAfter) {
    // Nach Ablauf der Entprellung einen zweiten Zyklus starten, der den ersten überholt.
    await new Promise((r) => setTimeout(r, scenario.secondCycleAfter));
    sse.onmessage({ data: "batch:recipient" });
  }
  // Entprellung (250 ms) plus Zeit für die Fetches abwarten.
  await new Promise((r) => setTimeout(r, 900));
  if (scenario.streamRecovers) { sse.onopen(); await new Promise((r) => setTimeout(r, 50)); }
  console.log(JSON.stringify({ hinweisSichtbar: hidden === false, inhalt: tbodyInhalt }));
})();
"""


def _run(scenario: dict, tmp_path: Path) -> dict:
    harness = tmp_path / "harness.js"
    harness.write_text(HARNESS, encoding="utf-8")
    out = subprocess.run(
        ["node", str(harness), json.dumps(scenario), str(APP_JS)],
        capture_output=True, text=True, timeout=30, check=True,
    )
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_hinweis_bleibt_aus_wenn_alles_gelingt(tmp_path):
    assert _run({"responses": [True], "streamDown": False}, tmp_path)["hinweisSichtbar"] is False


def test_hinweis_erscheint_bei_fehlgeschlagenem_fragment(tmp_path):
    assert _run({"responses": [False], "streamDown": False}, tmp_path)["hinweisSichtbar"] is True


def test_abgerissener_stream_bleibt_sichtbar_trotz_erfolgreichem_refresh(tmp_path):
    """Regression: Ein gelungener Refresh darf eine tote SSE-Verbindung nicht überdecken."""
    assert _run({"responses": [True], "streamDown": True}, tmp_path)["hinweisSichtbar"] is True


def test_hinweis_verschwindet_wenn_stream_zurueckkommt(tmp_path):
    assert _run(
        {"responses": [True], "streamDown": True, "streamRecovers": True}, tmp_path
    )["hinweisSichtbar"] is False


def test_erfolgreicher_parallel_refresh_ueberdeckt_fehlgeschlagenen_nicht(tmp_path):
    """Regression: Zwei Fragmente werden parallel geladen. Schlägt eines fehl und
    gelingt das andere, muss der Hinweis stehen bleiben — der Zustand wird erst
    ausgewertet, wenn alle Requests eines Zyklus durch sind."""
    ergebnis = _run(
        {"responses": [False, True], "streamDown": False, "withBatchStatus": True},
        tmp_path,
    )
    assert ergebnis["hinweisSichtbar"] is True


def test_beide_fragmente_erfolgreich_blendet_hinweis_aus(tmp_path):
    ergebnis = _run(
        {"responses": [True, True], "streamDown": False, "withBatchStatus": True},
        tmp_path,
    )
    assert ergebnis["hinweisSichtbar"] is False


def test_veralteter_zyklus_ueberschreibt_aktuellen_fehler_nicht(tmp_path):
    """Regression: Zyklen können sich überholen.

    Zyklus 1 lädt erfolgreich, aber langsam (600 ms). Zyklus 2 startet danach und
    schlägt sofort fehl — der Hinweis erscheint. Träfe danach das veraltete
    Erfolgsergebnis von Zyklus 1 ein, würde es den Hinweis fälschlich ausblenden.
    """
    ergebnis = _run(
        {
            "responses": [True, False],   # Zyklus 1 ok, Zyklus 2 Fehler
            "delays": [600, 0],           # Zyklus 1 antwortet als Letzter
            "secondCycleAfter": 300,      # nach Ablauf der Entprellung
            "streamDown": False,
        },
        tmp_path,
    )
    assert ergebnis["hinweisSichtbar"] is True


def test_veralteter_zyklus_ueberschreibt_neueren_inhalt_nicht(tmp_path):
    """Regression: Nicht nur der Fehlerzustand, auch der geladene Inhalt darf nicht
    von einer verspäteten Antwort überschrieben werden.

    Zyklus 1 liefert "ALT", braucht dafür aber 600 ms. Zyklus 2 startet danach und
    liefert sofort "NEU". Trifft "ALT" danach ein, darf es die Tabelle nicht
    zurücksetzen.
    """
    ergebnis = _run(
        {
            "responses": [True, True],
            "delays": [600, 0],
            "bodies": ["ALT", "NEU"],
            "secondCycleAfter": 300,
            "streamDown": False,
        },
        tmp_path,
    )
    assert ergebnis["inhalt"] == "NEU"
