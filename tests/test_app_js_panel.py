# ruff: noqa: E501  (eingebettetes JS im Harness und in den Szenarien)
"""Prüft die Seitenleiste in ``app/static/app.js`` (Klick, Verlauf, Tastatur, Formulare, SSE).

Wie ``test_app_js.py``: kein Browser, kein jsdom (bewusst kein Node-Buildchain), sondern ein
kleiner DOM-Ersatz in Node. Er kann Elemente mit Attributen, Eltern/Kind, ``closest``,
``matches`` und einfache Selektoren (Tag, ``#id``, ``.klasse``, ``[attr]``, ``[attr=wert]``,
Komma-Listen, Nachfahren) — genau das, was ``app.js`` für die Leiste braucht. Jeder Test
liefert ein JS-Skript, das gegen den Ersatz läuft und ein Ergebnisobjekt zurückgibt.
Was nur ein echter Browser zeigt (Layout, Fokusring, PDF-Vorschau), steht in tasks.md als
manuelle Prüfung.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

APP_JS = Path(__file__).resolve().parents[1] / "app" / "static" / "app.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node nicht verfügbar")

HARNESS = r"""
const fs = require("fs");
const config = JSON.parse(process.argv[2]);
const script = process.argv[4];
const echterTimeout = setTimeout;
// Zeitraffer fuer die Fristen in app.js (15 s / 120 s); Helfer und Netz bleiben in echter Zeit.
if (config.scale) global.setTimeout = (fn, ms) => echterTimeout(fn, Math.round((ms || 0) * config.scale));

// ---- Selektoren ------------------------------------------------------------
function parseCompound(s) {
  const c = { tag: null, id: null, classes: [], attrs: [] };
  let m = /^[a-zA-Z][\w-]*|^\*/.exec(s);
  if (m) { c.tag = m[0].toUpperCase(); s = s.slice(m[0].length); }
  while (s.length) {
    if ((m = /^\.([\w-]+)/.exec(s))) c.classes.push(m[1]);
    else if ((m = /^#([\w-]+)/.exec(s))) c.id = m[1];
    else if ((m = /^\[([\w-]+)(?:=([^\]]*))?\]/.exec(s))) c.attrs.push([m[1], m[2] === undefined ? null : m[2]]);
    else throw new Error("Selektor nicht unterstuetzt: " + s);
    s = s.slice(m[0].length);
  }
  return c;
}
function matchCompound(el, c) {
  if (c.tag && c.tag !== "*" && el.tagName !== c.tag) return false;
  if (c.id && el.getAttribute("id") !== c.id) return false;
  const cls = (el.getAttribute("class") || "").split(/\s+/);
  if (!c.classes.every((k) => cls.includes(k))) return false;
  return c.attrs.every(([n, v]) => el.hasAttribute(n) && (v === null || el.getAttribute(n) === v));
}
function matchesSel(el, sel) {
  return sel.split(",").some((part) => {
    const toks = part.trim().split(/\s+/).map(parseCompound);
    if (!matchCompound(el, toks[toks.length - 1])) return false;
    let i = toks.length - 2, a = el.parent;
    while (i >= 0 && a) { if (a.hasAttribute && matchCompound(a, toks[i])) i--; a = a.parent; }
    return i < 0;
  });
}

// ---- Elemente --------------------------------------------------------------
class El {
  constructor(tag, attrs, parent) {
    this.tagName = tag.toUpperCase();
    this.attrs = {};
    for (const k in attrs || {}) this.attrs[k] = String(attrs[k]);
    this.children = [];
    this.parent = null;
    this.hidden = false;
    this.disabled = false;
    this.scrollTop = 0;
    this._html = "";
    this.textContent = "";
    this.fields = [];
    if (parent) parent.appendChild(this);
    const self = this;
    this.classList = {
      add(c) { const l = (self.attrs.class || "").split(/\s+/).filter(Boolean); if (!l.includes(c)) l.push(c); self.attrs.class = l.join(" "); },
      remove(c) { self.attrs.class = (self.attrs.class || "").split(/\s+/).filter((x) => x && x !== c).join(" "); },
      contains(c) { return (self.attrs.class || "").split(/\s+/).includes(c); },
    };
  }
  get id() { return this.attrs.id || ""; }
  get name() { return this.attrs.name || ""; }
  get value() { return this.attrs.value || ""; }
  set className(v) { this.attrs.class = v; }
  getAttribute(n) { return n in this.attrs ? this.attrs[n] : null; }
  hasAttribute(n) { return n in this.attrs; }
  setAttribute(n, v) { this.attrs[n] = String(v); }
  removeAttribute(n) { delete this.attrs[n]; }
  appendChild(c) { if (c.parent) c.parent.removeChild(c); c.parent = this; this.children.push(c); return c; }
  insertBefore(c, ref) {
    if (c.parent) c.parent.removeChild(c);
    c.parent = this;
    const i = ref ? this.children.indexOf(ref) : -1;
    if (i < 0) this.children.push(c); else this.children.splice(i, 0, c);
    return c;
  }
  removeChild(c) { this.children = this.children.filter((x) => x !== c); c.parent = null; }
  get firstChild() { return this.children[0] || null; }
  get parentNode() { return this.parent; }
  get nextSibling() {
    if (!this.parent) return null;
    return this.parent.children[this.parent.children.indexOf(this) + 1] || null;
  }
  matches(sel) { return matchesSel(this, sel); }
  closest(sel) { for (let e = this; e && e.matches; e = e.parent) if (e.matches(sel)) return e; return null; }
  contains(o) { for (let e = o; e; e = e.parent) if (e === this) return true; return false; }
  descendants() { const out = []; const walk = (e) => e.children.forEach((c) => { out.push(c); walk(c); }); walk(this); return out; }
  querySelectorAll(sel) { return this.descendants().filter((d) => d.matches(sel)); }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  focus() { document.activeElement = this; const tr = this.closest("tr"); focusLog.push(this.attrs.id || (tr && tr.attrs["data-row-id"]) || this.tagName); }
  scrollIntoView(o) { scrolled.push(this.attrs["data-row-id"]); }
  get innerHTML() { return this._html; }
  // Kein HTML-Parser: Kinder werden verworfen; Zeilen (<tr ...>) und die Leistenelemente,
  // die app.js danach sucht (#panel-title), werden aus dem Text nachgebaut.
  set innerHTML(h) {
    this._html = h;
    this.children.forEach((c) => { c.parent = null; });
    this.children = [];
    if (this.tagName === "TBODY") {
      const re = /<tr\s+([^>]*)>/g;
      let m;
      while ((m = re.exec(h)) !== null) {
        const attrs = {};
        const are = /([\w-]+)="([^"]*)"/g;
        let a;
        while ((a = are.exec(m[1])) !== null) attrs[a[1]] = a[2];
        mkRow(attrs, this);
      }
    }
    if (this.tagName !== "TBODY") {
      // Flach: Elemente mit id, die Vorschau (section.doc-preview > object) und der Verlauf
      // (details.doc-log) in Dokumentreihenfolge. section.paperless-embedded ist ein
      // Container: alles danach gehoert hinein (wie im echten Dokument, wo er zuletzt steht).
      const tre = /<(\w+)([^>]*)>/g;
      let t, sektion = null, behaelter = this;
      while ((t = tre.exec(h)) !== null) {
        const attrs = {};
        const are = /([\w-]+)="([^"]*)"/g;
        let a;
        while ((a = are.exec(t[2])) !== null) attrs[a[1]] = a[2];
        if (t[1] === "details" && /\sopen(\s|$)/.test(t[2])) attrs.open = "";
        if (t[1] === "object" && sektion) new El("object", attrs, sektion);
        else if (t[1] === "section" && attrs.class === "doc-preview") sektion = new El("section", attrs, behaelter);
        else if (t[1] === "section" && attrs.class === "paperless-embedded") behaelter = new El("section", attrs, this);
        else if (t[1] === "details" && attrs.class === "doc-log") new El("details", attrs, behaelter);
        else if (attrs.id) new El(t[1], attrs, behaelter);
      }
    }
  }
}
const focusLog = [];
const scrolled = [];

function mkRow(attrs, parent) {
  const tr = new El("tr", attrs, parent);
  const td = new El("td", { class: "filename" }, tr);
  new El("a", { href: attrs["data-page-url"] || "#" }, td);
  return tr;
}

// ---- Seite -----------------------------------------------------------------
const body = new El("body");
const main = new El("main", { class: "container" + (config.panelOpen ? " has-panel" : "") }, body);
const table = new El("table", { class: "history", "data-fragment": config.tableFragment || "/fragment/invoices?status=open" }, main);
const tbody = new El("tbody", {}, table);
const ids = config.rows || [11, 12, 13];
const rows = ids.map((id) => {
  const attrs = {
    "data-row-id": id, "data-rev": "r" + id,
    "data-panel-url": "/fragment/paperless/" + id, "data-page-url": "/paperless/" + id,
  };
  if (config.panelOpen === id) attrs["aria-current"] = "true";
  const tr = mkRow(attrs, tbody);
  // Zweite Spalte mit einem fremden Link und einer Checkbox: Bedienelemente der Zeile.
  const td2 = new El("td", {}, tr);
  new El("a", { href: "/extern/" + id, class: "other" }, td2);
  new El("input", { type: "checkbox", name: "ids", value: id }, td2);
  return tr;
});
const panel = new El("aside", { id: "panel" }, main);
if (config.panelOpen) {
  panel.attrs["data-fragment"] = "/fragment/paperless/" + config.panelOpen;
  new El("h1", { id: "panel-title" }, panel);
} else {
  panel.hidden = true;
}
if (config.detailFragment) new El("div", { id: "detail", "data-fragment": config.detailFragment }, body);

const listeners = {};
const winListeners = {};
const document = {
  activeElement: body,
  addEventListener: (t, f) => { (listeners[t] = listeners[t] || []).push(f); },
  getElementById: (id) => body.descendants().find((e) => e.attrs.id === id) || null,
  querySelector: (sel) => body.querySelector(sel),
  querySelectorAll: (sel) => body.querySelectorAll(sel),
  createElement: (tag) => new El(tag),
};
global.document = document;

const pushes = [];
const assigns = [];
const win = {
  addEventListener: (t, f) => { (winListeners[t] = winListeners[t] || []).push(f); },
  location: { pathname: config.pathname || "/invoices", search: config.search === undefined ? "?status=open" : config.search,
              assign: (u) => assigns.push(u) },
  history: {
    pushState: (st, t, url) => {
      pushes.push(url);
      const i = url.indexOf("?");
      win.location.pathname = i < 0 ? url : url.slice(0, i);
      win.location.search = i < 0 ? "" : url.slice(i);
    },
  },
};
global.window = win;

// ---- Netz ------------------------------------------------------------------
const routes = {};
const calls = [];
global.FormData = function (form) { this.forEach = (cb) => form.fields.forEach(([n, v]) => cb(v, n)); };
global.fetch = (url, opts) => {
  opts = opts || {};
  const method = (opts.method || "GET").toUpperCase();
  const route = routes[method + " " + url] || routes[url] || {};
  calls.push({ url, method, headers: opts.headers || {}, body: opts.body === undefined ? null : String(opts.body) });
  const status = route.status || 200;
  const inhalt = route.body !== undefined ? route.body : '<h1 id="panel-title">' + url + "</h1>";
  return new Promise((res, rej) => {
    if ((route.delay || 0) < 0) {  // antwortet nie
      if (opts.signal) opts.signal.addEventListener("abort", () => rej(new Error("abort")));
      return;
    }
    const t = echterTimeout(() => res({ ok: status < 300, status, url: route.url || url, text: () => Promise.resolve(inhalt) }), route.delay || 0);
    if (opts.signal) opts.signal.addEventListener("abort", () => { clearTimeout(t); rej(new Error("abort")); });
  });
};
win.fetch = global.fetch;

let sse = null;
if (config.sse) { global.EventSource = function () { sse = this; }; win.EventSource = global.EventSource; }

eval(fs.readFileSync(process.argv[3], "utf8"));

// ---- Helfer fuer die Skripte -----------------------------------------------
function dispatch(type, ev) {
  ev.defaultPrevented = false;
  ev.preventDefault = () => { ev.defaultPrevented = true; };
  (listeners[type] || []).forEach((f) => f(ev));
  return ev;
}
const sleep = (ms) => new Promise((r) => echterTimeout(r, ms));
const H = {
  main, panel, table, tbody, rows, body, calls, pushes, assigns, routes, focusLog, scrolled, win, document,
  El, sleep, dispatch,
  sse: () => sse,
  click: (target, o) => dispatch("click", Object.assign({ target, button: 0 }, o || {})),
  key: (target, k, o) => dispatch("keydown", Object.assign({ target, key: k }, o || {})),
  submit: (form, submitter) => dispatch("submit", { target: form, submitter }),
  popstate: () => (winListeners.popstate || []).forEach((f) => f({})),
  titel: (i) => rows[i].querySelector("td.filename a"),
  aktuell: () => rows.filter((r) => r.getAttribute("aria-current") === "true").map((r) => r.getAttribute("data-row-id")),
  hatPanelKlasse: () => main.classList.contains("has-panel"),
};

const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
new AsyncFunction("H", script)(H).then(
  (r) => { console.log(JSON.stringify(r === undefined ? null : r)); process.exit(0); },
  (e) => { console.error(e && e.stack || e); process.exit(1); }
);
"""


def _run(script: str, tmp_path: Path, **config) -> dict:
    harness = tmp_path / "harness_panel.js"
    harness.write_text(HARNESS, encoding="utf-8")
    out = subprocess.run(
        ["node", str(harness), json.dumps(config), str(APP_JS), textwrap.dedent(script)],
        capture_output=True, text=True, timeout=30,
    )
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


# --- Öffnen per Klick -----------------------------------------------------------

def test_klick_auf_titel_oeffnet_leiste_mit_adresse_markierung_und_fokus(tmp_path):
    erg = _run("""
        const ev = H.click(H.titel(1));
        await H.sleep(30);
        return { verhindert: ev.defaultPrevented, hidden: H.panel.hidden, klasse: H.hatPanelKlasse(),
                 push: H.pushes, aktuell: H.aktuell(), fetches: H.calls.map(c => c.url),
                 fokus: H.focusLog[H.focusLog.length - 1], html: H.panel.innerHTML,
                 fragment: H.panel.getAttribute("data-fragment") };
    """, tmp_path)
    assert erg["verhindert"] is True
    assert erg["hidden"] is False and erg["klasse"] is True
    # Übrige Query bleibt, doc kommt dazu.
    assert erg["push"] == ["/invoices?status=open&doc=12"]
    assert erg["aktuell"] == ["12"]
    assert erg["fetches"] == ["/fragment/paperless/12"]
    assert erg["fokus"] == "panel-title"
    assert erg["fragment"] == "/fragment/paperless/12"


def test_klick_auf_zeile_ausserhalb_des_titels_oeffnet_ebenfalls(tmp_path):
    erg = _run("""
        const td = H.rows[0].children[1];  // zweite Zelle, nicht der Titel
        H.click(td);
        await H.sleep(20);
        return { fetches: H.calls.map(c => c.url) };
    """, tmp_path)
    assert erg["fetches"] == ["/fragment/paperless/11"]


def test_modifier_mittelklick_und_bedienelemente_oeffnen_nicht(tmp_path):
    erg = _run("""
        const verhindert = [];
        verhindert.push(H.click(H.titel(0), { ctrlKey: true }).defaultPrevented);
        verhindert.push(H.click(H.titel(0), { metaKey: true }).defaultPrevented);
        verhindert.push(H.click(H.titel(0), { shiftKey: true }).defaultPrevented);
        verhindert.push(H.click(H.titel(0), { altKey: true }).defaultPrevented);
        verhindert.push(H.click(H.titel(0), { button: 1 }).defaultPrevented);
        verhindert.push(H.click(H.rows[0].querySelector("a.other")).defaultPrevented);
        verhindert.push(H.click(H.rows[0].querySelector("input")).defaultPrevented);
        await H.sleep(20);
        return { verhindert, fetches: H.calls.length, pushes: H.pushes.length, hidden: H.panel.hidden };
    """, tmp_path)
    assert erg["verhindert"] == [False] * 7
    assert erg["fetches"] == 0 and erg["pushes"] == 0 and erg["hidden"] is True


def test_schneller_wechsel_bricht_den_vorigen_ladevorgang_ab(tmp_path):
    erg = _run("""
        H.routes["/fragment/paperless/11"] = { body: '<h1 id="panel-title">ALT</h1>', delay: 200 };
        H.routes["/fragment/paperless/12"] = { body: '<h1 id="panel-title">NEU</h1>', delay: 0 };
        H.click(H.titel(0));
        await H.sleep(20);
        H.click(H.titel(1));
        await H.sleep(300);
        return { html: H.panel.innerHTML, aktuell: H.aktuell(), pushes: H.pushes,
                 hinweis: !!H.panel.querySelector("[data-panel-alert]") };
    """, tmp_path)
    assert "NEU" in erg["html"]
    assert erg["aktuell"] == ["12"]
    assert erg["pushes"] == ["/invoices?status=open&doc=11", "/invoices?status=open&doc=12"]
    assert erg["hinweis"] is False  # der abgebrochene Request meldet keinen Fehler


def test_ladefehler_zeigt_hinweis_in_der_leiste(tmp_path):
    erg = _run("""
        H.routes["/fragment/paperless/11"] = { status: 503 };
        H.click(H.titel(0));
        await H.sleep(30);
        const a = H.panel.querySelector("[data-panel-alert]");
        return { alert: !!a, rolle: a && a.getAttribute("role"), klasse: a && a.getAttribute("class") };
    """, tmp_path)
    assert erg == {"alert": True, "rolle": "alert", "klasse": "alert"}


# --- Verlauf --------------------------------------------------------------------

def test_popstate_stellt_dokument_und_schliessen_her(tmp_path):
    erg = _run("""
        H.click(H.titel(0)); await H.sleep(20);
        H.click(H.titel(1)); await H.sleep(20);
        const pushesVorher = H.pushes.length;
        H.win.location.search = "?status=open&doc=11";  // Zurück-Taste
        H.popstate(); await H.sleep(20);
        const nachZurueck = { aktuell: H.aktuell(), fragment: H.panel.getAttribute("data-fragment") };
        H.win.location.search = "?status=open";          // noch einmal zurück: geschlossen
        H.popstate(); await H.sleep(20);
        return { nachZurueck, pushesNeu: H.pushes.length - pushesVorher,
                 hidden: H.panel.hidden, klasse: H.hatPanelKlasse(), aktuell: H.aktuell(),
                 fragment: H.panel.getAttribute("data-fragment") };
    """, tmp_path)
    assert erg["nachZurueck"] == {"aktuell": ["11"], "fragment": "/fragment/paperless/11"}
    assert erg["pushesNeu"] == 0  # popstate darf nicht erneut pushen
    assert erg["hidden"] is True and erg["klasse"] is False
    assert erg["aktuell"] == [] and erg["fragment"] is None


def test_schliessen_knopf_entfernt_doc_und_fokussiert_titel_der_zeile(tmp_path):
    erg = _run("""
        H.click(H.titel(1)); await H.sleep(20);
        const knopf = new H.El("button", { "data-panel-close": "" }, H.panel);
        const ev = H.click(knopf);
        return { verhindert: ev.defaultPrevented, hidden: H.panel.hidden, klasse: H.hatPanelKlasse(),
                 push: H.pushes[H.pushes.length - 1], aktuell: H.aktuell(),
                 fokus: H.focusLog[H.focusLog.length - 1], leer: H.panel.innerHTML };
    """, tmp_path)
    assert erg["hidden"] is True and erg["klasse"] is False
    assert erg["push"] == "/invoices?status=open"
    assert erg["aktuell"] == []
    assert erg["fokus"] == "12"  # Titel-Link der zuletzt geöffneten Zeile
    assert erg["leer"] == ""


def test_serverseitig_gerenderte_leiste_wird_uebernommen(tmp_path):
    """Seitenaufruf mit ?doc=: JS übernimmt Zustand, Klick darauf wechselt ohne Fehler."""
    erg = _run("""
        H.click(H.titel(2)); await H.sleep(20);
        return { aktuell: H.aktuell(), push: H.pushes };
    """, tmp_path, panelOpen=12, search="?status=open&doc=12")
    assert erg["aktuell"] == ["13"]
    assert erg["push"] == ["/invoices?status=open&doc=13"]


# --- Tastatur -------------------------------------------------------------------

def test_j_k_und_pfeile_wechseln_in_dom_reihenfolge(tmp_path):
    erg = _run("""
        const t = H.body;
        const verlauf = [];
        const schritt = async (k) => { H.key(t, k); await H.sleep(20); verlauf.push(H.aktuell()[0]); };
        await schritt("j");          // 12 -> 13
        await schritt("k");          // 13 -> 12
        await schritt("ArrowDown");  // 12 -> 13
        await schritt("ArrowUp");    // 13 -> 12
        await schritt("k");          // 12 -> 11
        await schritt("k");          // Listenanfang: bleibt 11
        return { verlauf, scrolled: H.scrolled.slice(0, 2) };
    """, tmp_path, panelOpen=12)
    assert erg["verlauf"] == ["13", "12", "13", "12", "11", "11"]
    assert erg["scrolled"] == ["13", "12"]


def test_am_listenende_passiert_nichts(tmp_path):
    erg = _run("""
        const ev = H.key(H.body, "j"); await H.sleep(20);
        return { aktuell: H.aktuell(), calls: H.calls.length, pushes: H.pushes.length };
    """, tmp_path, panelOpen=13)
    assert erg == {"aktuell": ["13"], "calls": 0, "pushes": 0}


def test_escape_schliesst_und_fokussiert_die_zeile(tmp_path):
    erg = _run("""
        const ev = H.key(H.body, "Escape");
        return { verhindert: ev.defaultPrevented, hidden: H.panel.hidden,
                 push: H.pushes[H.pushes.length - 1], fokus: H.focusLog[H.focusLog.length - 1] };
    """, tmp_path, panelOpen=12)
    assert erg == {"verhindert": True, "hidden": True, "push": "/invoices?status=open", "fokus": "12"}


def test_enter_oeffnet_die_seite(tmp_path):
    erg = _run("""
        H.key(H.body, "Enter");
        return { assigns: H.assigns };
    """, tmp_path, panelOpen=12)
    assert erg["assigns"] == ["/paperless/12"]


def test_enter_auf_knopf_behaelt_seine_aufgabe(tmp_path):
    erg = _run("""
        const knopf = new H.El("button", {}, H.panel);
        const ev = H.key(knopf, "Enter");
        return { assigns: H.assigns, verhindert: ev.defaultPrevented };
    """, tmp_path, panelOpen=12)
    assert erg == {"assigns": [], "verhindert": False}


def test_tasten_werden_in_eingabefeldern_modifiern_und_vorschau_ignoriert(tmp_path):
    erg = _run("""
        const eingabe = new H.El("input", { type: "text" }, H.panel);
        const auswahl = new H.El("select", {}, H.panel);
        const text = new H.El("textarea", {}, H.panel);
        const edit = new H.El("div", { contenteditable: "true" }, H.panel);
        const vorschau = new H.El("section", { class: "doc-preview" }, H.panel);
        const objekt = new H.El("object", {}, vorschau);
        const behandelt = [];
        for (const ziel of [eingabe, auswahl, text, edit, objekt, vorschau]) {
          for (const k of ["j", "k", "ArrowDown", "Escape", "Enter"]) {
            behandelt.push(H.key(ziel, k).defaultPrevented);
          }
        }
        // Modifikatoren am neutralen Ziel
        for (const o of [{ ctrlKey: true }, { metaKey: true }, { altKey: true }, { shiftKey: true }]) {
          behandelt.push(H.key(H.body, "j", o).defaultPrevented);
          behandelt.push(H.key(H.body, "Escape", o).defaultPrevented);
        }
        await H.sleep(20);
        return { behandelt: behandelt.some(Boolean), calls: H.calls.length, hidden: H.panel.hidden,
                 assigns: H.assigns };
    """, tmp_path, panelOpen=12)
    assert erg == {"behandelt": False, "calls": 0, "hidden": False, "assigns": []}


def test_tasten_wirken_nicht_bei_geschlossener_leiste(tmp_path):
    erg = _run("""
        const e = ["j", "ArrowDown", "Escape", "Enter"].map(k => H.key(H.body, k).defaultPrevented);
        await H.sleep(20);
        return { e, calls: H.calls.length, assigns: H.assigns };
    """, tmp_path)
    assert erg == {"e": [False] * 4, "calls": 0, "assigns": []}


# --- Formulare ------------------------------------------------------------------

_FORM = """
    const form = new H.El("form", { "data-panel-form": "", action: "/empfaenger/12", method: "post" }, H.panel);
    form.fields = [["recipient", "Mueller"]];
    const knopf = new H.El("button", { name: "paid", value: "yes" }, form);
"""


def test_formular_sendet_per_fetch_ersetzt_leiste_und_aktualisiert_liste(tmp_path):
    erg = _run(_FORM + """
        H.routes["POST /empfaenger/12"] = { url: "https://x.test/fragment/paperless/12?ask=1",
                                           body: '<h1 id="panel-title">NACH AKTION</h1>' };
        const ev = H.submit(form, knopf);
        const waehrend = knopf.disabled;
        await H.sleep(50);
        const post = H.calls.find(c => c.method === "POST");
        const tabelle = H.calls.filter(c => c.url.indexOf("/fragment/invoices") === 0);
        return { verhindert: ev.defaultPrevented, waehrend, danach: knopf.disabled, post,
                 html: H.panel.innerHTML, fragment: H.panel.getAttribute("data-fragment"),
                 tabelle: tabelle.map(c => c.url), panelLaeufe: H.calls.filter(c => c.url.indexOf("/fragment/paperless") === 0).length,
                 fokus: H.focusLog[H.focusLog.length - 1] };
    """, tmp_path, panelOpen=12)
    assert erg["verhindert"] is True
    assert erg["waehrend"] is True and erg["danach"] is False
    assert erg["post"]["headers"] == {"X-Requested-With": "fetch", "X-Lector-Panel": "1"}
    # Submitter-Wert wird mitgeschickt, auch wenn der Knopf danach gesperrt ist.
    assert erg["post"]["body"] == "recipient=Mueller&paid=yes"
    assert "NACH AKTION" in erg["html"]
    # Der Redirect auf ?ask=1 bleibt für spätere Refreshes erhalten, ohne Origin.
    assert erg["fragment"] == "/fragment/paperless/12?ask=1"
    # Listen-Refresh mit aktuellem doc (Markierung bleibt); die Leiste lädt nicht doppelt.
    assert erg["tabelle"] == ["/fragment/invoices?status=open&doc=12"]
    assert erg["panelLaeufe"] == 0
    assert erg["fokus"] == "panel-title"


def test_doppelklick_sendet_nur_einmal(tmp_path):
    erg = _run(_FORM + """
        H.routes["POST /empfaenger/12"] = { delay: 50 };
        H.submit(form, knopf);
        H.submit(form, knopf);
        await H.sleep(100);
        return { posts: H.calls.filter(c => c.method === "POST").length };
    """, tmp_path, panelOpen=12)
    assert erg["posts"] == 1


def test_formularfehler_zeigt_hinweis_und_laesst_inhalt_stehen(tmp_path):
    erg = _run(_FORM + """
        H.panel.innerHTML = "";               // neutralen Ausgangsinhalt setzen
        H.panel.appendChild(form);
        H.routes["POST /empfaenger/12"] = { status: 400 };
        H.submit(form, knopf);
        await H.sleep(50);
        const a = H.panel.querySelector("[data-panel-alert]");
        return { alert: !!a, rolle: a && a.getAttribute("role"), zuerst: H.panel.children[0] === a,
                 text: a && a.textContent,
                 formNochDa: H.panel.contains(form), knopfFrei: knopf.disabled === false,
                 listeNachgeladen: H.calls.some(c => c.url.indexOf("/fragment/invoices") === 0),
                 nochSendend: form.hasAttribute("data-sending") };
    """, tmp_path, panelOpen=12)
    assert erg["alert"] is True and erg["rolle"] == "alert" and erg["zuerst"] is True
    assert "nicht ausgeführt" in erg["text"]
    assert erg["formNochDa"] is True and erg["knopfFrei"] is True
    assert erg["listeNachgeladen"] is False
    assert erg["nochSendend"] is False


def test_antwort_fuer_ein_anderes_dokument_ersetzt_die_leiste_nicht(tmp_path):
    erg = _run(_FORM + """
        H.routes["POST /empfaenger/12"] = { delay: 100, body: '<h1 id="panel-title">ALT</h1>' };
        H.submit(form, knopf);
        await H.sleep(10);
        H.click(H.titel(2));                 // Nutzer wechselt auf 13, während gesendet wird
        await H.sleep(200);
        return { html: H.panel.innerHTML, fragment: H.panel.getAttribute("data-fragment") };
    """, tmp_path, panelOpen=12)
    assert "ALT" not in erg["html"]
    assert erg["fragment"] == "/fragment/paperless/13"


def test_formulare_ausserhalb_der_leiste_bleiben_normal(tmp_path):
    erg = _run("""
        const form = new H.El("form", { "data-panel-form": "" }, H.main);   // nicht in #panel
        form.fields = [];
        const ev = H.submit(form);
        const gewoehnlich = new H.El("form", {}, H.panel);
        const ev2 = H.submit(gewoehnlich);
        return { a: ev.defaultPrevented, b: ev2.defaultPrevented, calls: H.calls.length };
    """, tmp_path, panelOpen=12)
    assert erg == {"a": False, "b": False, "calls": 0}


# --- SSE ------------------------------------------------------------------------

def test_sse_laedt_liste_und_leiste_mit(tmp_path):
    erg = _run("""
        H.sse().onmessage({ data: "inv:5" });
        await H.sleep(400);
        return { urls: H.calls.map(c => c.url).sort() };
    """, tmp_path, panelOpen=12, sse=True)
    assert erg["urls"] == ["/fragment/invoices?status=open&doc=12", "/fragment/paperless/12"]


def test_sse_laesst_aria_current_der_liste_nicht_verlieren(tmp_path):
    erg = _run("""
        H.routes["/fragment/invoices?status=open&doc=12"] = { body:
          '<tr data-row-id="11" data-rev="a" data-panel-url="/fragment/paperless/11" data-page-url="/paperless/11">' +
          '<tr data-row-id="12" data-rev="b" data-panel-url="/fragment/paperless/12" data-page-url="/paperless/12">' };
        H.sse().onmessage({ data: "inv:5" });
        await H.sleep(400);
        return { aktuell: H.aktuell() };
    """, tmp_path, panelOpen=12, sse=True)
    assert erg["aktuell"] == ["12"]


def test_sse_ueberschreibt_keine_eingabe_in_der_leiste(tmp_path):
    erg = _run("""
        const feld = new H.El("input", { type: "text", id: "betrag" }, H.panel);
        feld.focus();
        H.dispatch("input", { target: feld });            // Nutzer hat getippt
        H.sse().onmessage({ data: "inv:5" });
        await H.sleep(400);
        const urls = H.calls.map(c => c.url);
        return { panelGeladen: urls.some(u => u.indexOf("/fragment/paperless") === 0),
                 listeGeladen: urls.some(u => u.indexOf("/fragment/invoices") === 0),
                 feldNochDa: H.panel.contains(feld) };
    """, tmp_path, panelOpen=12, sse=True)
    assert erg == {"panelGeladen": False, "listeGeladen": True, "feldNochDa": True}


def test_sse_laedt_leiste_wenn_feld_fokussiert_aber_unveraendert(tmp_path):
    erg = _run("""
        const feld = new H.El("input", { type: "text", id: "betrag" }, H.panel);
        feld.focus();                                      // nur fokussiert, nichts getippt
        H.sse().onmessage({ data: "inv:5" });
        await H.sleep(400);
        return { panelGeladen: H.calls.some(c => c.url.indexOf("/fragment/paperless") === 0) };
    """, tmp_path, panelOpen=12, sse=True)
    assert erg["panelGeladen"] is True


def test_sse_pausiert_die_leiste_waehrend_ein_formular_sendet(tmp_path):
    erg = _run(_FORM + """
        H.routes["POST /empfaenger/12"] = { delay: 300 };
        H.submit(form, knopf);
        H.sse().onmessage({ data: "inv:5" });
        await H.sleep(280);                                // Debounce vorbei, POST läuft noch
        return { panelGeladen: H.calls.some(c => c.method === "GET" && c.url.indexOf("/fragment/paperless") === 0) };
    """, tmp_path, panelOpen=12, sse=True)
    assert erg["panelGeladen"] is False


def test_geschlossene_leiste_wird_nicht_mitgeladen(tmp_path):
    erg = _run("""
        H.sse().onmessage({ data: "inv:5" });
        await H.sleep(400);
        return { urls: H.calls.map(c => c.url) };
    """, tmp_path, sse=True)
    assert erg["urls"] == ["/fragment/invoices?status=open"]


def test_paperless_seite_nimmt_inv_ereignisse_an_und_ignoriert_vorgaenge(tmp_path):
    """Die ID der Seite ist eine Paperless-ID, "inv:" trägt die Rechnungs-ID: kein
    Abgleich möglich, also konservativ aktualisieren. "doc:" betrifft die Seite nicht."""
    erg = _run("""
        H.table.parent.removeChild(H.table);
        H.sse().onmessage({ data: "doc:3" });
        await H.sleep(400);
        const nachDoc = H.calls.length;
        H.sse().onmessage({ data: "inv:99" });
        await H.sleep(400);
        return { nachDoc, urls: H.calls.map(c => c.url) };
    """, tmp_path, sse=True, pathname="/paperless/7", detailFragment="/fragment/paperless/7")
    assert erg["nachDoc"] == 0
    assert erg["urls"] == ["/fragment/paperless/7"]


def test_dokumentseite_filtert_weiter_nach_id(tmp_path):
    erg = _run("""
        H.table.parent.removeChild(H.table);
        H.sse().onmessage({ data: "doc:4" });
        H.sse().onmessage({ data: "rec:3" });
        await H.sleep(400);
        const fremd = H.calls.length;
        H.sse().onmessage({ data: "doc:3" });
        await H.sleep(400);
        return { fremd, urls: H.calls.map(c => c.url) };
    """, tmp_path, sse=True, pathname="/documents/3", detailFragment="/fragment/documents/3")
    assert erg["fremd"] == 0
    assert erg["urls"] == ["/fragment/documents/3"]


# --- Überprüfungsbefunde: Eingaben, Wechsel, Fristen, Scroll/Fokus --------------------

def test_sse_ueberschreibt_eingabe_auch_bei_fokus_ausserhalb_der_leiste_nicht(tmp_path):
    """IBAN getippt, dann auf leere Fläche geklickt: Fokus liegt nicht mehr in der Leiste,
    die Eingabe ist aber ungespeichert."""
    erg = _run("""
        const feld = new H.El("input", { type: "text", id: "iban" }, H.panel);
        H.dispatch("input", { target: feld });
        H.document.activeElement = H.body;                 // Fokus ausserhalb
        H.sse().onmessage({ data: "inv:5" });
        await H.sleep(400);
        return { panelGeladen: H.calls.some(c => c.url.indexOf("/fragment/paperless") === 0),
                 listeGeladen: H.calls.some(c => c.url.indexOf("/fragment/invoices") === 0) };
    """, tmp_path, panelOpen=12, sse=True)
    assert erg == {"panelGeladen": False, "listeGeladen": True}


def test_wechsel_sperrt_alten_inhalt_und_blockiert_formular(tmp_path):
    erg = _run(_FORM + """
        H.routes["/fragment/paperless/13"] = { delay: 100, body: '<h1 id="panel-title">B</h1>' };
        H.click(H.titel(2));                               // Wechsel auf 13 läuft
        await H.sleep(10);
        const waehrend = { busy: H.panel.getAttribute("aria-busy"), inert: form.hasAttribute("inert") };
        H.submit(form, knopf);                             // Formular von 12 darf nicht senden
        const posts = H.calls.filter(c => c.method === "POST").length;
        await H.sleep(200);
        return { waehrend, posts, busyDanach: H.panel.getAttribute("aria-busy"),
                 html: H.panel.innerHTML };
    """, tmp_path, panelOpen=12)
    assert erg["waehrend"] == {"busy": "true", "inert": True}
    assert erg["posts"] == 0
    assert erg["busyDanach"] is None and "B" in erg["html"]


def test_antwort_von_a_wird_nach_wechsel_auf_b_nicht_uebernommen(tmp_path):
    erg = _run(_FORM + """
        H.routes["POST /empfaenger/12"] = { delay: 150, body: '<h1 id="panel-title">ANTWORT-A</h1>' };
        H.routes["/fragment/paperless/13"] = { delay: 20, body: '<h1 id="panel-title">B</h1>' };
        H.submit(form, knopf);                             // läuft für Dokument 12
        await H.sleep(10);
        H.key(H.body, "j");                                // Wechsel auf 13
        await H.sleep(300);
        return { html: H.panel.innerHTML, fragment: H.panel.getAttribute("data-fragment"),
                 listeNachgeladen: H.calls.some(c => c.url.indexOf("/fragment/invoices") === 0) };
    """, tmp_path, panelOpen=12)
    assert "ANTWORT-A" not in erg["html"] and "B" in erg["html"]
    assert erg["fragment"] == "/fragment/paperless/13"
    assert erg["listeNachgeladen"] is True  # die Aktion lief trotzdem: Liste aktualisieren


def test_ladefehler_beim_wechsel_laesst_alten_inhalt_gesperrt_mit_hinweis(tmp_path):
    erg = _run(_FORM + """
        H.routes["/fragment/paperless/13"] = { status: 503 };
        H.click(H.titel(2));
        await H.sleep(40);
        return { alert: !!H.panel.querySelector("[data-panel-alert]"), aktuell: H.aktuell(),
                 push: H.pushes[H.pushes.length - 1], busy: H.panel.getAttribute("aria-busy"),
                 formGesperrt: form.hasAttribute("inert"),
                 hinweisGesperrt: H.panel.querySelector("[data-panel-alert]").hasAttribute("inert") };
    """, tmp_path, panelOpen=12)
    assert erg == {"alert": True, "aktuell": ["13"], "push": "/invoices?status=open&doc=13",
                   "busy": None, "formGesperrt": True, "hinweisGesperrt": False}


def test_langer_post_scheitert_nicht_an_der_15_sekunden_frist(tmp_path):
    """Zeitraffer 0,01: Abruf-Frist 150 ms, POST-Frist 1200 ms. Der POST braucht 600 ms."""
    erg = _run(_FORM + """
        H.routes["POST /empfaenger/12"] = { delay: 600, body: '<h1 id="panel-title">FERTIG</h1>' };
        H.submit(form, knopf);
        await H.sleep(900);
        return { html: H.panel.innerHTML, hinweis: !!H.panel.querySelector("[data-panel-alert]") };
    """, tmp_path, panelOpen=12, scale=0.01)
    assert "FERTIG" in erg["html"] and erg["hinweis"] is False


def test_haengender_post_meldet_ergebnis_unklar_und_aktualisiert_die_liste(tmp_path):
    erg = _run(_FORM + """
        H.routes["POST /empfaenger/12"] = { delay: -1 };
        H.submit(form, knopf);
        await H.sleep(1700);                               // 120 s * 0,01 = 1,2 s
        const a = H.panel.querySelector("[data-panel-alert]");
        return { text: a && a.textContent, frei: knopf.disabled === false,
                 liste: H.calls.some(c => c.url.indexOf("/fragment/invoices") === 0) };
    """, tmp_path, panelOpen=12, scale=0.01)
    assert "unklar" in erg["text"] and "nicht ausgeführt" not in erg["text"]
    assert erg["frei"] is True and erg["liste"] is True


def test_serverfehler_5xx_ist_ergebnis_unklar_mit_listen_refresh(tmp_path):
    erg = _run(_FORM + """
        H.routes["POST /empfaenger/12"] = { status: 500 };
        H.submit(form, knopf);
        await H.sleep(60);
        const a = H.panel.querySelector("[data-panel-alert]");
        return { text: a && a.textContent,
                 liste: H.calls.some(c => c.url.indexOf("/fragment/invoices") === 0) };
    """, tmp_path, panelOpen=12)
    assert "unklar" in erg["text"] and erg["liste"] is True


_ANTWORT_D = ('<h1 id="panel-title">T</h1><section class="doc-preview"><object data="{pdf}"></object>'
              '</section><form id="zahl"></form>')


def test_aktion_behaelt_scroll_fokus_und_vorschau(tmp_path):
    erg = _run("""
        const vor = new H.El("section", { class: "doc-preview" }, H.panel);
        new H.El("object", { data: "/vorschau.pdf" }, vor);
        vor.marker = "alt";
        const form = new H.El("form", { "data-panel-form": "", action: "/empfaenger/12", method: "post", id: "zahl" }, H.panel);
        form.fields = [];
        H.panel.scrollTop = 250;
        H.routes["POST /empfaenger/12"] = { body: '""" + _ANTWORT_D.format(pdf="/vorschau.pdf") + """' };
        H.submit(form);
        await H.sleep(60);
        const jetzt = H.panel.querySelector(".doc-preview");
        const ids = H.panel.children.map(c => c.attrs.id || c.attrs.class);
        return { gleichesElement: jetzt === vor, marker: jetzt && jetzt.marker, scroll: H.panel.scrollTop,
                 fokus: H.focusLog[H.focusLog.length - 1], ids };
    """, tmp_path, panelOpen=12)
    assert erg["gleichesElement"] is True and erg["marker"] == "alt"
    assert erg["scroll"] == 250
    assert erg["fokus"] == "zahl"  # Fokus auf dem ersetzten Formular, nicht auf dem Titel
    assert erg["ids"] == ["panel-title", "doc-preview", "zahl"]


def test_geaenderte_vorschau_wird_neu_aufgebaut(tmp_path):
    erg = _run("""
        const vor = new H.El("section", { class: "doc-preview" }, H.panel);
        new H.El("object", { data: "/alt.pdf" }, vor);
        const form = new H.El("form", { "data-panel-form": "", action: "/empfaenger/12", method: "post" }, H.panel);
        form.fields = [];
        H.routes["POST /empfaenger/12"] = { body: '""" + _ANTWORT_D.format(pdf="/neu.pdf") + """' };
        H.submit(form);
        await H.sleep(60);
        const jetzt = H.panel.querySelector(".doc-preview");
        return { gleich: jetzt === vor, daten: jetzt && jetzt.querySelector("object").getAttribute("data") };
    """, tmp_path, panelOpen=12)
    assert erg == {"gleich": False, "daten": "/neu.pdf"}


def test_dokumentwechsel_setzt_scroll_zurueck_und_fokussiert_titel(tmp_path):
    erg = _run("""
        H.panel.scrollTop = 300;
        H.click(H.titel(2));
        await H.sleep(40);
        return { scroll: H.panel.scrollTop, fokus: H.focusLog[H.focusLog.length - 1] };
    """, tmp_path, panelOpen=12)
    assert erg == {"scroll": 0, "fokus": "panel-title"}


# --- Links mit data-panel-url in der Leiste (z.B. „Abbrechen“) -----------------------

def test_link_in_der_leiste_laedt_fragment_ohne_neuen_verlaufseintrag(tmp_path):
    erg = _run("""
        H.panel.setAttribute("data-fragment", "/fragment/paperless/12?ask=1");
        const link = new H.El("a", { href: "/paperless/12", "data-panel-url": "/fragment/paperless/12" }, H.panel);
        const ev = H.click(link);
        await H.sleep(40);
        return { verhindert: ev.defaultPrevented, pushes: H.pushes.length,
                 fragment: H.panel.getAttribute("data-fragment"),
                 fetches: H.calls.map(c => c.url) };
    """, tmp_path, panelOpen=12)
    assert erg == {"verhindert": True, "pushes": 0, "fragment": "/fragment/paperless/12",
                   "fetches": ["/fragment/paperless/12"]}


def test_link_in_der_leiste_mit_modifier_und_ausserhalb_bleibt_normal(tmp_path):
    erg = _run("""
        const innen = new H.El("a", { href: "/paperless/12", "data-panel-url": "/fragment/paperless/12" }, H.panel);
        const aussen = new H.El("a", { href: "/paperless/12", "data-panel-url": "/fragment/paperless/12" }, H.main);
        const r = [
          H.click(innen, { ctrlKey: true }).defaultPrevented,
          H.click(innen, { button: 1 }).defaultPrevented,
          H.click(aussen).defaultPrevented,
        ];
        await H.sleep(20);
        return { r, calls: H.calls.length };
    """, tmp_path, panelOpen=12)
    assert erg == {"r": [False, False, False], "calls": 0}


def test_dokumentseite_nimmt_rechnungs_und_belegereignisse_an(tmp_path):
    """Der eingebettete Rechnungsbereich hängt an inv:/vouchers:, nicht an der Vorgangs-ID."""
    erg = _run("""
        H.table.parent.removeChild(H.table);
        H.sse().onmessage({ data: "inv:99" });
        await H.sleep(400);
        const nachInv = H.calls.length;
        H.sse().onmessage({ data: "vouchers:sync" });
        await H.sleep(400);
        return { nachInv, urls: H.calls.map(c => c.url) };
    """, tmp_path, sse=True, pathname="/documents/3", detailFragment="/fragment/documents/3")
    assert erg["nachInv"] == 1
    assert erg["urls"] == ["/fragment/documents/3", "/fragment/documents/3"]


# --- Kombinierte Vorgangsansicht: Vorschau und Verlauf überstehen den Tausch -----------

_ANTWORT_K = ('<h1 id="panel-title">T</h1><details class="doc-log"{offen}></details>'
              '<section class="paperless-embedded"><h2 id="titel">Z</h2>'
              '<section class="doc-preview"><object data="{pdf}"></object></section>'
              '<form id="zahl"></form>')

_AUFBAU_K = """
        const details = new H.El("details", { class: "doc-log", "data-server-open": "0" }, H.panel);
        const emb = new H.El("section", { class: "paperless-embedded" }, H.panel);
        new H.El("h2", { id: "titel" }, emb);
        const vor = new H.El("section", { class: "doc-preview" }, emb);
        new H.El("object", { data: "/vorschau.pdf" }, vor);
        new H.El("form", { id: "zahl" }, emb);
"""


def test_eingebettete_vorschau_bleibt_bei_aktion_und_sse_erhalten(tmp_path):
    erg = _run(_AUFBAU_K + """
        vor.marker = "alt";
        const form = H.panel.querySelector("#zahl");
        form.attrs["data-panel-form"] = ""; form.attrs.action = "/empfaenger/12"; form.attrs.method = "post";
        form.fields = [];
        H.routes["POST /empfaenger/12"] = { body: '""" + _ANTWORT_K.format(offen="", pdf="/vorschau.pdf") + """' };
        H.submit(form);
        await H.sleep(60);
        const jetzt = H.panel.querySelector(".doc-preview");
        return { gleich: jetzt === vor, marker: jetzt && jetzt.marker,
                 eltern: jetzt && jetzt.parent.getAttribute("class"),
                 anzahlEmb: H.panel.querySelectorAll(".paperless-embedded").length };
    """, tmp_path, panelOpen=12)
    assert erg == {"gleich": True, "marker": "alt", "eltern": "paperless-embedded", "anzahlEmb": 1}


def test_eingebettete_geaenderte_vorschau_wird_neu_aufgebaut(tmp_path):
    erg = _run(_AUFBAU_K + """
        const form = H.panel.querySelector("#zahl");
        form.attrs["data-panel-form"] = ""; form.attrs.action = "/empfaenger/12"; form.fields = [];
        H.routes["POST /empfaenger/12"] = { body: '""" + _ANTWORT_K.format(offen="", pdf="/neu.pdf") + """' };
        H.submit(form);
        await H.sleep(60);
        const jetzt = H.panel.querySelector(".doc-preview");
        return { gleich: jetzt === vor, daten: jetzt.querySelector("object").getAttribute("data") };
    """, tmp_path, panelOpen=12)
    assert erg == {"gleich": False, "daten": "/neu.pdf"}


def test_vom_nutzer_geaenderter_verlauf_bleibt_beim_tausch_erhalten(tmp_path):
    erg = _run(_AUFBAU_K + """
        details.setAttribute("open", "");  // Nutzer klappt auf (Server hatte zu: data-server-open=0)
        const form = H.panel.querySelector("#zahl");
        form.attrs["data-panel-form"] = ""; form.attrs.action = "/empfaenger/12"; form.fields = [];
        H.routes["POST /empfaenger/12"] = { body: '""" + _ANTWORT_K.format(offen="", pdf="/vorschau.pdf") + """' };
        H.submit(form);
        await H.sleep(60);
        const neu = H.panel.querySelector("details.doc-log");
        return { offen: neu.hasAttribute("open"), server: neu.getAttribute("data-server-open") };
    """, tmp_path, panelOpen=12)
    assert erg == {"offen": True, "server": "0"}


def test_unveraenderter_verlauf_folgt_dem_server_und_dokumentwechsel_setzt_zurueck(tmp_path):
    erg = _run(_AUFBAU_K + """
        // Server rendert jetzt offen (z.B. Vorgang ist fehlgeschlagen), Nutzer hat nichts angefasst.
        H.routes["/fragment/paperless/12"] = { body: '""" + _ANTWORT_K.format(offen=" open", pdf="/vorschau.pdf") + """' };
        H.sse().onmessage({ data: "doc:12" });
        await H.sleep(400);
        const folgt = H.panel.querySelector("details.doc-log").hasAttribute("open");
        // Nutzer klappt zu, dann Dokumentwechsel: Serverzustand (offen) gilt wieder.
        H.panel.querySelector("details.doc-log").removeAttribute("open");
        H.routes["/fragment/paperless/13"] = { body: '""" + _ANTWORT_K.format(offen=" open", pdf="/x.pdf") + """' };
        H.click(H.titel(1));
        await H.sleep(60);
        return { folgt, nachWechsel: H.panel.querySelector("details.doc-log").hasAttribute("open") };
    """, tmp_path, panelOpen=12, sse=True)
    assert erg == {"folgt": True, "nachWechsel": True}


def test_detailseite_setzt_unveraenderten_inhalt_nicht_neu_und_behaelt_vorschau(tmp_path):
    erg = _run("""
        H.table.parent.removeChild(H.table);
        const detail = H.document.getElementById("detail");
        const details = new H.El("details", { class: "doc-log", "data-server-open": "0" }, detail);
        const emb = new H.El("section", { class: "paperless-embedded" }, detail);
        const vor = new H.El("section", { class: "doc-preview" }, emb);
        new H.El("object", { data: "/vorschau.pdf" }, vor);
        vor.marker = "alt";
        details.setAttribute("open", "");  // Nutzer klappt auf
        const html = '""" + _ANTWORT_K.format(offen="", pdf="/vorschau.pdf") + """';
        H.routes["/fragment/documents/3"] = { body: html };
        H.sse().onmessage({ data: "doc:3" });
        await H.sleep(400);
        const v1 = detail.querySelector(".doc-preview");
        const d1 = detail.querySelector("details.doc-log");
        const erste = { gleich: v1 === vor, offen: d1.hasAttribute("open") };
        d1.marker = "neu";
        H.sse().onmessage({ data: "doc:3" });
        await H.sleep(400);
        const zweite = { gleichesDetails: detail.querySelector("details.doc-log").marker === "neu" };
        return { erste, zweite };
    """, tmp_path, sse=True, pathname="/documents/3", detailFragment="/fragment/documents/3")
    assert erg["erste"] == {"gleich": True, "offen": True}
    assert erg["zweite"] == {"gleichesDetails": True}  # identischer Inhalt: nichts neu gesetzt
