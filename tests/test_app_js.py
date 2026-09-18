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

// Zeitraffer: Poll-Pause und Antwortzeiten werden mit demselben Faktor gestaucht, die
// Reihenfolge der Ereignisse bleibt damit exakt erhalten. Ohne das dauerte ein Test, der
// eine Antwort langsamer als die 2000-ms-Pause machen muss, mehrere Sekunden.
const skala = scenario.scale || 1;
const echterTimeout = setTimeout;
global.setTimeout = (fn, ms) => echterTimeout(fn, Math.round((ms || 0) * skala));
global.clearTimeout = clearTimeout;

// Zeilen-Double fuer den Vergleich vor/nach einem Abgleich. app.js liest je Zeile nur
// data-row-id und data-rev und setzt im Trefferfall eine Klasse — mehr muss der Harness
// nicht koennen, ein echter DOM-Parser waere hier Ballast.
let aufgeleuchtet = [];
function parseRows(html) {
  const rows = [];
  const re = /<tr\\s+data-row-id="([^"]*)"\\s+data-rev="([^"]*)"/g;
  let m;
  while ((m = re.exec(html || "")) !== null) {
    const row = { id: m[1], rev: m[2] };
    row.getAttribute = (name) => (name === "data-row-id" ? row.id : row.rev);
    row.classList = {
      add: (c) => { if (c === "row-updated") aufgeleuchtet.push(row.id); },
      remove: () => {},
    };
    rows.push(row);
  }
  return rows;
}

let tbodyInhalt = null;
let tbodyRows = [];
const tbody = {
  set innerHTML(v) { tbodyInhalt = v; tbodyRows = parseRows(v); },
  get innerHTML() { return tbodyInhalt; },
  querySelectorAll: () => tbodyRows,
};
// Ausgangsbestand wie vom Server gerendert: ohne ihn waere JEDE Zeile des ersten
// Abgleichs neu und wuerde aufleuchten.
if (scenario.initialRows) tbody.innerHTML = scenario.initialRows;

const table = {
  getAttribute: () => "/fragment/empfaenger",
  querySelector: () => tbody,
};

let batchInhalt = null;
const batchStatus = { getAttribute: () => "/fragment/empfaenger/batch-status",
                      set innerHTML(v) { batchInhalt = v; } };

global.document = {
  querySelector: (sel) => {
    if (sel.startsWith("table.history")) return table;
    // Marker eines laufenden KI-Laufs — Signal fuer den Abfragetakt in app.js.
    if (sel.indexOf("data-batch-running") >= 0) return scenario.batchRunning ? {} : null;
    return null;
  },
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
let batchAntwort = 0;
global.fetch = (url, _opts) => {
  const n = i++;
  const ok = n < scenario.responses.length ? scenario.responses[n] : true;
  const vorgabe = (scenario.delays || [])[n];
  const delay = vorgabe === undefined ? (scenario.defaultDelay || 0) : vorgabe;
  let inhalt = (scenario.bodies || [])[n];
  if (inhalt === undefined) {
    // Fortlaufend nummeriert, damit ein Test sieht, WIE OFT der Stand ankam.
    inhalt = String(url).indexOf("batch-status") >= 0
      ? "BATCH" + ++batchAntwort
      : "<tr></tr>";
  }
  const body = () => Promise.resolve(inhalt);
  const res = { ok: ok, status: ok ? 200 : 503, text: body };
  // delay < 0 heisst: antwortet NIE — gestauter Proxy, halboffene Verbindung.
  if (delay < 0) return new Promise(() => {});
  return new Promise((r) => echterTimeout(() => r(res), Math.round(delay * skala)));
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
  // Entprellung (250 ms) plus Zeit für die Fetches abwarten — in echten Millisekunden.
  await new Promise((r) => echterTimeout(r, 900));
  if (scenario.streamRecovers) { sse.onopen(); await new Promise((r) => echterTimeout(r, 50)); }
  console.log(JSON.stringify({
    hinweisSichtbar: hidden === false, inhalt: tbodyInhalt, batchInhalt: batchInhalt,
    aufgeleuchtet: aufgeleuchtet,
  }));
  // Der Abfragetakt plant sich endlos weiter — ohne das bliebe node haengen.
  process.exit(0);
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


def test_langsame_antworten_halten_den_fortschritt_nicht_an(tmp_path):
    """Regression: Der Abfragetakt darf sich nicht selbst überholen.

    Als fester ``setInterval(refreshFragment, 2000)`` gebaut, zog jeder Tick die
    Sequenznummer hoch. Brauchte eine Antwort länger als die Taktpause — bei einem
    Batch-Lauf der Normalfall, das Fragment kostet einen Paperless-Zählaufruf —, war sie
    beim Eintreffen bereits überholt und wurde vom Veralterungsschutz verworfen. Bei
    durchgehend langsamen Antworten kam damit **kein einziger** Stand an: Die Zahl stand
    still, obwohl im Sekundentakt gefragt wurde. Genau der Zustand, den der Takt beheben
    soll.

    Hier antwortet jeder Request 1,5-mal so langsam wie die Taktpause. Es muss trotzdem
    mehrfach ein Stand ankommen.
    """
    ergebnis = _run(
        {
            "responses": [],
            "withBatchStatus": True,
            "batchRunning": True,
            "defaultDelay": 3000,  # langsamer als BATCH_POLL_MS (2000)
            "scale": 0.05,         # Zeitraffer, Reihenfolge bleibt erhalten
        },
        tmp_path,
    )
    assert ergebnis["batchInhalt"] is not None, "kein einziger Stand angekommen"
    angekommen = int(ergebnis["batchInhalt"].removeprefix("BATCH"))
    assert angekommen >= 2, f"nur {angekommen} Stand/Staende angekommen"


def test_ohne_laufenden_batch_kein_abfragetakt(tmp_path):
    """Ausserhalb eines Laufs bleibt es bei SSE — sonst fragt die Seite dauerhaft nach."""
    ergebnis = _run(
        {"responses": [], "withBatchStatus": True, "batchRunning": False,
         "defaultDelay": 0, "scale": 0.05},
        tmp_path,
    )
    # Der einzige Zyklus stammt aus dem SSE-Ereignis des Harness, nicht aus einem Takt.
    assert ergebnis["batchInhalt"] == "BATCH1"


def test_haengender_request_haelt_den_abfragetakt_nicht_an(tmp_path):
    """Regression: Ein Request ohne Antwort darf den Takt nicht dauerhaft stoppen.

    Der Takt plant den nächsten Zyklus erst, wenn der vorige durch ist. ``fetch`` hat von
    sich aus keine Frist, und ``Promise.allSettled`` löst erst auf, wenn **alle**
    Teil-Requests durch sind — ein hängender Request (gestauter Reverse Proxy, halboffene
    Verbindung) ließ die Kette damit nie weiterlaufen. Die Anzeige stand still, ohne dass
    etwas nach einem Fehler aussah: genau der Zustand, den der Takt beheben soll.

    Hier hängen die beiden Requests des ersten Zyklus für immer. Die Frist in
    ``loadFragment`` muss sie abräumen, damit spätere Zyklen wieder Stände liefern.
    """
    ergebnis = _run(
        {
            "responses": [],
            "withBatchStatus": True,
            "batchRunning": True,
            "delays": [-1, -1],  # erster Zyklus: Tabelle und Batch-Status antworten nie
            "defaultDelay": 0,
            "scale": 0.02,  # Zeitraffer: Frist 15 s → 300 ms, Poll-Pause 2 s → 40 ms
        },
        tmp_path,
    )
    assert ergebnis["batchInhalt"] is not None, "Takt nach haengendem Request tot"
    # Nicht nur ein Zufallstreffer: Nach dem Hänger müssen mehrere Stände ankommen.
    # (Der Veraltet-Hinweis steht am Ende zu Recht nicht mehr — die späteren Zyklen sind
    # gelungen, und er meldet den letzten Stand, nicht die Vorgeschichte.)
    angekommen = int(ergebnis["batchInhalt"].removeprefix("BATCH"))
    assert angekommen >= 3, f"Takt kam nach dem Haenger nur auf {angekommen} Staende"


# --- Aufleuchten geänderter Zeilen ------------------------------------------
#
# Die Listen aktualisieren sich von selbst. Ohne sichtbares Signal geschieht eine
# Änderung unbemerkt — und ein Signal, das bei JEDEM Abgleich feuert, ist genauso
# wertlos wie gar keins. Geprüft wird deshalb beides: dass es feuert, wenn sich etwas
# geändert hat, und dass es schweigt, wenn nicht.

_ZEILE = '<tr data-row-id="{id}"\n    data-rev="{rev}"><td>x</td></tr>'


def _rows(*paare: tuple[str, str]) -> str:
    return "\n".join(_ZEILE.format(id=i, rev=r) for i, r in paare)


def test_geaenderte_zeile_leuchtet_auf(tmp_path):
    ergebnis = _run(
        {
            "responses": [True],
            "initialRows": _rows(("1", "processing:2:9:0"), ("2", "done:5:5:0")),
            "bodies": [_rows(("1", "processing:4:9:0"), ("2", "done:5:5:0"))],
        },
        tmp_path,
    )
    assert ergebnis["aufgeleuchtet"] == ["1"]


def test_unveraenderte_zeilen_leuchten_nicht_auf(tmp_path):
    """Sonst blinkt bei jedem Takt die ganze Tabelle und sagt damit nichts mehr aus."""
    bestand = _rows(("1", "done:9:9:0"), ("2", "done:5:5:0"))
    ergebnis = _run(
        {"responses": [True], "initialRows": bestand, "bodies": [bestand]}, tmp_path
    )
    assert ergebnis["aufgeleuchtet"] == []


def test_neu_hinzugekommene_zeile_leuchtet_auf(tmp_path):
    """Ein frisch eingegangenes Dokument ist der wichtigste Fall überhaupt."""
    ergebnis = _run(
        {
            "responses": [True],
            "initialRows": _rows(("1", "done:9:9:0")),
            "bodies": [_rows(("7", "pending:0:0:0"), ("1", "done:9:9:0"))],
        },
        tmp_path,
    )
    assert ergebnis["aufgeleuchtet"] == ["7"]


def test_verschobene_zeile_leuchtet_nicht_auf(tmp_path):
    """Der Vergleich läuft über die id, nicht über die Position: eine Zeile, die durch
    eine neue nur nach unten rutscht, hat sich nicht geändert."""
    ergebnis = _run(
        {
            "responses": [True],
            "initialRows": _rows(("1", "done:9:9:0"), ("2", "done:5:5:0")),
            "bodies": [_rows(("2", "done:5:5:0"), ("1", "done:9:9:0"))],
        },
        tmp_path,
    )
    assert ergebnis["aufgeleuchtet"] == []
