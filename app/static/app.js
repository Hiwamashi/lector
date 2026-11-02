// Live-Updates via Server-Sent Events. Tokens haben die Form "doc:<id>" (Dokumente),
// "inv:<id>" (Paperless-Rechnungen), "vouchers:sync" (SevDesk-Belegabzug) bzw.
// "batch:recipient" (Fortschritt des KI-Laufs).
// Bei einem passenden Ereignis wird der dynamische Bereich der aktuellen Seite
// (Listentabelle bzw. Detailansicht) neu geladen und ersetzt. Antworten mit Fehlerstatus
// (z.B. 503, wenn Paperless gerade nicht erreichbar ist) werden verworfen — der zuletzt
// erfolgreich geladene Inhalt bleibt dann stehen, statt durch eine Fehlermeldung zu
// verschwinden.
//
// Waehrend eines laufenden KI-Empfaenger-Laufs kommt ein fester Abfragetakt hinzu (siehe
// syncBatchPolling): Der Fortschritt darf nicht allein an SSE haengen.
(function () {
  "use strict";

  // Schnellfilter (Chips) wirken sofort: ein Klick schickt das Filterformular ab. Ohne JS
  // bleibt der "Filtern"-Knopf der Weg — das Formular ist ein gewöhnliches GET-Formular.
  document.addEventListener("change", function (event) {
    var input = event.target;
    if (!input || !input.closest || !input.closest(".chip")) return;
    var form = input.form;
    if (!form) return;
    if (typeof form.requestSubmit === "function") form.requestSubmit();
    else form.submit();
  });

  // Ein gescheiterter Refresh darf nicht stumm bleiben: der bisherige Inhalt steht dann
  // weiter da und sieht aktuell aus. Sichtbarer Hinweis statt stiller Veraltung.
  //
  // Die beiden Ursachen werden GETRENNT gefuehrt und der Refresh-Zustand erst ausgewertet,
  // wenn ALLE Teil-Requests eines Zyklus durch sind. Sonst blendet ein erfolgreicher
  // Parallel-Request (z.B. Batch-Status) den Hinweis wieder aus, obwohl ein anderer
  // (z.B. die Tabelle) im selben Zyklus fehlgeschlagen ist — oder ein gelungener Refresh
  // ueberdeckt eine abgerissene SSE-Verbindung.
  var refreshFailed = false;
  var streamDown = false;
  // Laufende Zyklen koennen sich ueberholen: die Entprellung verhindert nur Bursts
  // innerhalb von 250 ms, nicht einen langsamen Zyklus, dessen Antwort nach der eines
  // spaeter gestarteten eintrifft. Nur der juengste Zyklus darf wirken — und zwar in
  // BEIDE Richtungen: weder sein Fehlerzustand noch der geladene Inhalt duerfen von einer
  // veralteten Antwort ueberschrieben werden.
  var cycle = 0;

  // Abgelaufene oder fehlende Sitzung (nur im Modus mit Anmeldung): der Server antwortet
  // auf Fragmente und den SSE-Strom mit 401. Das ist kein Aktualisierungsfehler, sondern
  // der Hinweis, sich neu anzumelden — also zur Anmeldeseite wechseln und danach hierher
  // zurueckkehren (next). Das Flag verhindert mehrfaches Umleiten, wenn mehrere Requests
  // eines Zyklus gleichzeitig mit 401 antworten. Im Modus ohne Anmeldung kommt nie ein 401,
  // dort aendert sich nichts.
  var umgeleitet = false;

  function zurAnmeldung() {
    // Auf der Anmeldeseite selbst nie umleiten — sonst verschachtelt sich next endlos.
    if (umgeleitet || window.location.pathname === "/login") return;
    umgeleitet = true;
    window.location.assign("/login?next=" + encodeURIComponent(
      window.location.pathname + window.location.search
    ));
  }

  function updateLiveStatus() {
    var el = document.getElementById("live-status");
    if (el) el.hidden = !(refreshFailed || streamDown);
  }

  // Ein Request ohne Frist kann beliebig lange haengen — ein gestauter Reverse Proxy oder
  // eine halboffene Verbindung liefert weder Antwort noch Fehler. Fuer den Abfragetakt
  // waere das toedlich: Er plant den naechsten Zyklus erst, wenn der vorige durch ist, und
  // ein Zyklus, der nie abschliesst, haelt ihn dauerhaft an — die Anzeige stuende still,
  // ohne dass irgendetwas nach einem Fehler aussieht. Genau der Zustand, den der Takt
  // beheben soll. Mit Frist scheitert der Request stattdessen sichtbar (Veraltet-Hinweis)
  // und der Takt laeuft weiter.
  var FRAGMENT_TIMEOUT_MS = 15000;
  // Aktionen der Leiste (z.B. SevDesk-Export) duerfen deutlich laenger dauern als ein Abruf.
  var POST_TIMEOUT_MS = 120000;

  // Race statt reinem AbortController: Die Frist muss auch dann greifen, wenn
  // AbortController fehlt. Der Abbruch kommt obendrauf und gibt die Verbindung frei.
  function withDeadline(promise, abbruch, dauer) {
    return new Promise(function (resolve, reject) {
      var frist = setTimeout(function () {
        if (abbruch) abbruch.abort();
        reject(new Error("timeout"));
      }, dauer || FRAGMENT_TIMEOUT_MS);
      promise.then(
        function (wert) { clearTimeout(frist); resolve(wert); },
        function (fehler) { clearTimeout(frist); reject(fehler); }
      );
    });
  }

  // Die Listen aktualisieren sich von selbst. Ein harter innerHTML-Tausch macht das
  // unsichtbar: die Zeile steht danach genauso da wie vorher, nur mit anderem Inhalt —
  // wer nicht zufaellig hinsieht, bemerkt nichts und vergleicht gegen sein Gedaechtnis.
  // Deshalb vor dem Tausch die Signaturen (data-rev) sichern, danach vergleichen und nur
  // die wirklich geaenderten Zeilen kurz aufleuchten lassen. Der Vergleich laeuft ueber
  // data-row-id, nicht ueber die Position: eine Zeile, die nur weiter nach oben rutscht,
  // hat sich nicht geaendert und soll nicht blinken.
  var FLASH_MS = 1600;  // Dauer von .row-updated in app.css

  function signaturen(container) {
    var map = {};
    var rows = container.querySelectorAll("tr[data-row-id]");
    for (var i = 0; i < rows.length; i++) {
      map[rows[i].getAttribute("data-row-id")] = rows[i].getAttribute("data-rev");
    }
    return map;
  }

  // Die Klasse muss auch dann wieder verschwinden, wenn gar nicht animiert wird: unter
  // prefers-reduced-motion faerbt app.css die Zeile ohne Animation ein, ein
  // animationend-Ereignis kaeme dort nie — die Zeile bliebe dauerhaft markiert.
  // Deshalb eine Frist statt eines Ereignisses.
  function markiere(row) {
    row.classList.add("row-updated");
    setTimeout(function () { row.classList.remove("row-updated"); }, FLASH_MS);
  }

  // Mehrfachauswahl der Rechnungsliste (Checkboxen name="ids" mit data-select). Ein SSE-
  // Refresh ersetzt die ganze Tabelle per innerHTML und wuerde die Haken verlieren — mitten
  // in einer Auswahl waere das ein Datenverlust fuer den Nutzer. Statt den Refresh zu
  // pausieren (dann stuende die Liste waehrend der Auswahl still, und ein Export-Ergebnis
  // oder neue Belege wuerden nicht sichtbar) werden die gewaehlten IDs vor dem Tausch
  // gesichert und danach wiederhergestellt. Zeilen, die verschwunden oder nicht mehr
  // exportierbar sind, haben danach keine Checkbox mehr und fallen so aus der Auswahl.
  function gewaehlteIds(container) {
    var ids = {};
    var boxes = container.querySelectorAll("input[data-select]:checked");
    for (var i = 0; i < boxes.length; i++) ids[boxes[i].value] = true;
    return ids;
  }

  function stelleAuswahlHer(container, ids) {
    var boxes = container.querySelectorAll("input[data-select]");
    for (var i = 0; i < boxes.length; i++) {
      if (ids[boxes[i].value]) boxes[i].checked = true;
    }
  }

  function aktualisiereAuswahlKnopf() {
    var knopf = document.getElementById("batch-export");
    if (!knopf) return;
    var n = document.querySelectorAll("input[data-select]:checked").length;
    knopf.disabled = n === 0;
    var basis = knopf.getAttribute("data-label") || knopf.textContent;
    knopf.textContent = n > 0 ? basis + " (" + n + ")" : basis;
  }

  document.addEventListener("change", function (ev) {
    if (ev.target && ev.target.matches && ev.target.matches("input[data-select]")) {
      aktualisiereAuswahlKnopf();
    }
  });

  function applyRows(body, html) {
    var vorher = signaturen(body);
    var auswahl = gewaehlteIds(body);
    body.innerHTML = html;
    stelleAuswahlHer(body, auswahl);
    aktualisiereAuswahlKnopf();
    var rows = body.querySelectorAll("tr[data-row-id]");
    for (var i = 0; i < rows.length; i++) {
      // Unbekannte id = neue Zeile, abweichende Signatur = geaenderte Zeile. Beides
      // verdient das Aufleuchten, unveraenderte Zeilen nicht.
      if (vorher[rows[i].getAttribute("data-row-id")] === rows[i].getAttribute("data-rev")) continue;
      markiere(rows[i]);
    }
  }

  // mine: Zyklusnummer des Aufrufers. Ohne (undefined) entfaellt die Zyklusprüfung — die
  // Seitenleiste fuehrt ihre eigene Reihenfolge (panelSeq), weil ein Listen-Refresh sie
  // sonst beim Blaettern verwerfen wuerde. halter: optionales Objekt, das eine abort()-
  // Funktion bekommt, damit der Aufrufer den Request gezielt abbrechen kann.
  // apply bekommt zusaetzlich die endgueltige URL (nach Redirects, z.B. nach einem POST).
  function loadFragment(url, options, apply, mine, halter, dauer) {
    var abbruch = typeof AbortController === "function" ? new AbortController() : null;
    var opts = {};
    if (options) { for (var k in options) opts[k] = options[k]; }
    if (abbruch) opts.signal = abbruch.signal;
    if (halter) halter.abort = function () { if (abbruch) abbruch.abort(); };
    return withDeadline(
      fetch(url, opts)
        .then(function (r) {
          // 401 ist KEIN Fehlerzustand fuer den Hinweis (siehe refreshFragment), sondern
          // fuehrt zur Anmeldung. Der Throw verhindert nur, dass apply() laeuft.
          if (r.status === 401) { zurAnmeldung(); throw new Error("401"); }
          if (!r.ok) { var e = new Error(r.status); e.status = r.status; throw e; }
          return r.text().then(function (html) { return { html: html, url: r.url }; });
        })
        // Inhalt nur einsetzen, solange dieser Zyklus der juengste ist: sonst schreibt eine
        // spaet eintreffende Antwort aelteren Inhalt ueber den bereits aktuelleren.
        .then(function (erg) {
          if (mine === undefined || mine === cycle) apply(erg.html, erg.url);
        }),
      abbruch,
      dauer
    );
  }

  // Der Fortschritt eines KI-Laufs haengt sonst allein am SSE-Strom. Der ist unterwegs
  // fragil: Reverse Proxies puffern `text/event-stream` gern, dann bleibt die Verbindung
  // aeusserlich gesund, waehrend kein Ereignis mehr ankommt — die Zahl steht still, ohne
  // dass irgendetwas nach einem Fehler aussaehe. Solange ein Lauf laeuft, fragt die Seite
  // deshalb zusaetzlich von sich aus nach; ausserhalb eines Laufs bleibt es bei SSE.
  // Die Pause entspricht der Drosselung im Backend (BATCH_PUBLISH_INTERVAL), haeufiger
  // brauchte es nicht: oefter meldet der Lauf ohnehin nichts Neues. Sie liegt ZWISCHEN
  // den Zyklen, nicht in einem festen Raster — siehe scheduleBatchPoll.
  var BATCH_POLL_MS = 2000;
  var batchPolling = false;  // laeuft gerade ein Takt, weil ein Lauf aktiv ist?
  var batchTimer = null;     // Handle des naechsten geplanten Zyklus

  function syncBatchPolling() {
    var laeuft = !!document.querySelector("#batch-status [data-batch-running]");
    if (laeuft === batchPolling) return;
    batchPolling = laeuft;
    if (laeuft) {
      scheduleBatchPoll();
    } else if (batchTimer !== null) {
      clearTimeout(batchTimer);
      batchTimer = null;
    }
  }

  // Kette statt festem Raster: Der naechste Zyklus wird erst geplant, wenn der vorige
  // durch ist. Ein setInterval wuerde bei Antwortzeiten oberhalb von BATCH_POLL_MS jeden
  // laufenden Zyklus vom naechsten ueberholen lassen — der Veralterungsschutz in
  // loadFragment verwirft dann JEDE Antwort, und die Anzeige stuende dauerhaft still.
  // Genau der Zustand, den der Takt beheben soll.
  function scheduleBatchPoll() {
    batchTimer = setTimeout(function () {
      batchTimer = null;
      refreshFragment().then(function () {
        if (batchPolling) scheduleBatchPoll();
      });
    }, BATCH_POLL_MS);
  }

  // ohnePanel: nach einer Aktion in der Seitenleiste ist deren Inhalt schon frisch — nur
  // die Liste muss nachziehen.
  function refreshFragment(ohnePanel) {
    if (umgeleitet) return Promise.resolve();  // Seite wird gerade verlassen
    var mine = ++cycle;
    var jobs = [];

    var table = document.querySelector("table.history[data-fragment]");
    if (table) {
      var body = table.querySelector("tbody");
      // Aktuelles Dokument mitgeben, damit der Server die Markierung (aria-current) setzt.
      var tabellenUrl = table.getAttribute("data-fragment");
      if (panelKey) tabellenUrl = mitDoc(tabellenUrl, panelKey);
      jobs.push(loadFragment(
        tabellenUrl,
        { headers: { "X-Requested-With": "fetch" } },
        function (html) { if (body) { applyRows(body, html); markiereAktuelle(); } },
        mine
      ));
    }
    var panel = document.getElementById("panel");
    if (!ohnePanel && panel && !panel.hidden && panel.getAttribute("data-fragment") &&
        !panelBlockiert()) {
      var panelUrl = panel.getAttribute("data-fragment");
      jobs.push(loadFragment(
        panelUrl, undefined,
        function (html) {
          // Nur wenn die Leiste noch dasselbe zeigt und der Nutzer inzwischen nichts
          // eingegeben hat — eine laufende Eingabe darf nie ueberschrieben werden.
          if (panel.getAttribute("data-fragment") === panelUrl && !panelBlockiert()) {
            setzePanelInhalt(html, "refresh", schluessel(panelUrl));
          }
        },
        mine
      ));
    }
    var detail = document.getElementById("detail");
    if (detail && detail.getAttribute("data-fragment")) {
      jobs.push(loadFragment(
        detail.getAttribute("data-fragment"), undefined,
        function (html) { detail.innerHTML = html; },
        mine
      ));
    }
    var status = document.getElementById("overview-status");
    if (status && status.getAttribute("data-fragment")) {
      jobs.push(loadFragment(
        status.getAttribute("data-fragment"), undefined,
        function (html) { status.innerHTML = html; },
        mine
      ));
    }
    var batch = document.getElementById("batch-status");
    if (batch && batch.getAttribute("data-fragment")) {
      jobs.push(loadFragment(
        batch.getAttribute("data-fragment"), undefined,
        function (html) { batch.innerHTML = html; syncBatchPolling(); },
        mine
      ));
    }
    if (!jobs.length) return Promise.resolve();

    return Promise.allSettled(jobs).then(function (results) {
      if (mine !== cycle) return;  // von einem neueren Zyklus ueberholt
      if (umgeleitet) return;      // 401: kein "Aktualisierung fehlgeschlagen" zeigen
      refreshFailed = results.some(function (r) { return r.status === "rejected"; });
      updateLiveStatus();
    });
  }

  // Liefert {type, id} der aktuellen Detailseite oder null bei Listenseiten.
  function currentDetail() {
    var path = window.location.pathname;
    var doc = path.match(/^\/documents\/(\d+)/);
    if (doc) return { type: "doc", id: parseInt(doc[1], 10) };
    var inv = path.match(/^\/invoices\/(\d+)/);
    if (inv) return { type: "inv", id: parseInt(inv[1], 10) };
    // Paperless-Dokumentseite: die ID ist eine PAPERLESS-ID, die SSE-Tokens "inv:<id>"
    // tragen aber die Lector-Rechnungs-ID. Ein Abgleich waere falsch, also nicht filtern
    // (siehe passtZurDetailseite).
    var pl = path.match(/^\/paperless\/(\d+)/);
    if (pl) return { type: "paperless", id: parseInt(pl[1], 10) };
    return null;
  }

  // Betrifft das SSE-Ereignis die geoeffnete Detailseite? Konservativ: im Zweifel ja.
  function passtZurDetailseite(detail, type, id) {
    if (detail.type === "paperless") {
      // Vorgangs-Ereignisse ("doc:") zeigt die Paperless-Seite nicht; alles andere (inv,
      // vouchers, batch) kann sie betreffen und laesst sich nicht der Paperless-ID zuordnen.
      return type !== "doc";
    }
    return type === detail.type && id === detail.id;
  }

  // ---- Seitenleiste (#panel) --------------------------------------------------
  // Zeilen mit data-panel-url (Fragment) und data-page-url (Seite) oeffnen die Ansicht
  // neben der Liste. Die Adresse traegt ?doc=<Schluessel> (letzte Zahl der Fragment-URL),
  // damit Neuladen, Zurueck-Taste und geteilte Links denselben Zustand herstellen. Ohne JS
  // fuehrt der Titel-Link auf die eigene Seite; nichts davon ist dafuer noetig.
  var panelKey = null;       // Schluessel des geoeffneten Dokuments, null = geschlossen
  var panelInhaltKey = null; // Dokument, zu dem der JETZT gerenderte Inhalt gehoert
  var letzterKey = null;     // zuletzt geoeffnet — Fokusziel nach dem Schliessen
  var panelSeq = 0;          // Reihenfolge der Ladevorgaenge: nur der juengste wirkt
  var panelLadung = null;    // {abort} des laufenden Ladevorgangs
  var panelHtml = "";        // zuletzt gesetzter Inhalt (verhindert sinnloses Neuzeichnen)
  var panelDirty = false;    // Nutzer hat in der Leiste etwas eingegeben
  var panelSendet = 0;       // laufende Formular-Requests der Leiste

  function panelEl() { return document.getElementById("panel"); }

  function istOffen() {
    var p = panelEl();
    return !!p && !p.hidden;
  }

  function schluessel(url) {
    var m = /(\d+)(?:[?#].*)?$/.exec(String(url || ""));
    return m ? m[1] : null;
  }

  function panelZeilen() { return document.querySelectorAll("tr[data-panel-url]"); }

  function zeileFuer(key) {
    var rows = panelZeilen();
    for (var i = 0; i < rows.length; i++) {
      if (schluessel(rows[i].getAttribute("data-panel-url")) === key) return rows[i];
    }
    return null;
  }

  // URL mit gesetztem (key) bzw. entferntem (null) doc-Parameter; uebrige Query bleibt.
  function mitDoc(url, key) {
    var teile = String(url).split("#");
    var hash = teile.length > 1 ? "#" + teile.slice(1).join("#") : "";
    var pq = teile[0].split("?");
    var pfad = pq[0];
    var params = pq.length > 1 && pq[1] ? pq.slice(1).join("?").split("&") : [];
    var rest = [];
    for (var i = 0; i < params.length; i++) {
      if (params[i] && params[i].indexOf("doc=") !== 0) rest.push(params[i]);
    }
    if (key) rest.push("doc=" + encodeURIComponent(key));
    return pfad + (rest.length ? "?" + rest.join("&") : "") + hash;
  }

  function aktuellerDocParam() {
    var m = /[?&]doc=([^&#]*)/.exec(window.location.search || "");
    return m ? decodeURIComponent(m[1]) : null;
  }

  function markiereAktuelle() {
    var rows = panelZeilen();
    for (var i = 0; i < rows.length; i++) {
      var ist = !!panelKey && schluessel(rows[i].getAttribute("data-panel-url")) === panelKey;
      if (ist) rows[i].setAttribute("aria-current", "true");
      else rows[i].removeAttribute("aria-current");
    }
  }

  function setzeContainerKlasse(offen) {
    var main = document.querySelector("main.container");
    if (!main) return;
    if (offen) main.classList.add("has-panel");
    else main.classList.remove("has-panel");
  }

  function fokussiere(el) {
    if (!el || !el.focus) return;
    try { el.focus({ preventScroll: true }); } catch (e) { el.focus(); }
  }

  // Zeigt einen Hinweis oben in der Leiste; der Inhalt darunter bleibt stehen.
  function panelHinweis(text) {
    var p = panelEl();
    if (!p) return;
    var alt = p.querySelector("[data-panel-alert]");
    if (alt && alt.parentNode) alt.parentNode.removeChild(alt);
    var hinweis = document.createElement("p");
    hinweis.className = "alert";
    hinweis.setAttribute("role", "alert");
    hinweis.setAttribute("data-panel-alert", "");
    hinweis.textContent = text;
    p.insertBefore(hinweis, p.firstChild);
  }

  // Eingaben in der Leiste duerfen weder vom SSE-Refresh noch vom Zeilen-Diff verloren gehen.
  // Unabhaengig vom Fokus: wer eine IBAN tippt und dann auf eine leere Flaeche klickt, hat
  // sie trotzdem noch nicht gespeichert. Das Merkmal gilt bis zum naechsten Setzen des
  // Inhalts (Speichern, Dokumentwechsel).
  function panelBlockiert() {
    return panelSendet > 0 || panelDirty;
  }

  // Vorschau-Adresse (object data) — gleiche Adresse heisst: nicht neu laden.
  function vorschauDaten(v) {
    var o = v ? v.querySelector("object") : null;
    return o ? (o.getAttribute("data") || null) : null;
  }

  // Ersetzt den Inhalt der Leiste. Bleibt die Vorschau dieselbe, wird ihr Element nicht
  // angefasst: ein Verschieben oder Neuerzeugen laedt das PDF neu und setzt es zurueck.
  // Nur die Geschwister davor und danach werden getauscht.
  function ersetzeInhalt(p, html) {
    var alt = p.querySelector(".doc-preview");
    if (alt && alt.parentNode === p && vorschauDaten(alt)) {
      var tmp = document.createElement("div");
      tmp.innerHTML = html;
      var neu = tmp.querySelector(".doc-preview");
      if (neu && neu.parentNode === tmp && vorschauDaten(neu) === vorschauDaten(alt)) {
        while (p.firstChild && p.firstChild !== alt) p.removeChild(p.firstChild);
        while (alt.nextSibling) p.removeChild(alt.nextSibling);
        while (tmp.firstChild && tmp.firstChild !== neu) p.insertBefore(tmp.firstChild, alt);
        tmp.removeChild(neu);
        while (tmp.firstChild) p.appendChild(tmp.firstChild);
        return;
      }
    }
    p.innerHTML = html;
  }

  // modus: "wechsel" (anderes Dokument: nach oben, Fokus auf den Titel), "aktion" (Antwort
  // auf ein Formular: Scrollposition bleibt, Fokus auf das ausloesende Element) oder
  // "refresh" (SSE: nichts bewegt sich). key: Dokument, zu dem der Inhalt gehoert.
  function setzePanelInhalt(html, modus, key, fokusIds) {
    var p = panelEl();
    if (!p) return;
    // Unveraendert: nichts neu zeichnen.
    if (modus === "refresh" && html === panelHtml) return;
    var oben = p.scrollTop;
    var ae = document.activeElement;
    var imPanel = !!ae && p.contains(ae);
    var ids = (fokusIds || []).slice();
    if (imPanel && ae.id) ids.push(ae.id);
    ersetzeInhalt(p, html);
    panelHtml = html;
    panelDirty = false;
    if (key) panelInhaltKey = key;
    p.removeAttribute("aria-busy");
    if (modus === "wechsel") {
      p.scrollTop = 0;
      fokussiere(document.getElementById("panel-title"));
      return;
    }
    p.scrollTop = oben;
    for (var i = 0; i < ids.length; i++) {
      var el = ids[i] ? document.getElementById(ids[i]) : null;
      if (el && p.contains(el)) { fokussiere(el); return; }
    }
    // Das fokussierte Element ist weg: der Fokus faellt nicht ins Leere (ohne zu scrollen).
    if (modus === "aktion" && (imPanel || ids.length)) {
      fokussiere(document.getElementById("panel-title"));
    }
  }

  // Waehrend ein anderes Dokument laedt, bleibt der alte Inhalt sichtbar, ist aber
  // gesperrt: ein Formular darin wuerde sonst fuer das neue Dokument gelten.
  function sperrePanel() {
    var p = panelEl();
    if (!p) return;
    p.setAttribute("aria-busy", "true");
    for (var i = 0; i < p.children.length; i++) {
      var k = p.children[i];
      if (!k.classList.contains("panel-bar")) k.setAttribute("inert", "");
    }
  }

  function bricheLadungAb() {
    if (panelLadung && panelLadung.abort) panelLadung.abort();
    panelLadung = null;
  }

  function oeffnePanel(url, push) {
    var p = panelEl();
    var key = schluessel(url);
    if (!p || !key) return;
    var gleich = panelKey === key && !p.hidden;
    if (!gleich) {
      panelDirty = false;  // Wer das Dokument verlaesst, verwirft ungespeicherte Eingaben
      sperrePanel();
    }
    panelKey = key;
    letzterKey = key;
    p.hidden = false;
    p.setAttribute("data-fragment", url);
    setzeContainerKlasse(true);
    markiereAktuelle();
    if (push && !gleich) {
      window.history.pushState({ doc: key }, "", mitDoc(
        window.location.pathname + (window.location.search || ""), key
      ));
    }
    // Schnelles Weiterblaettern: der vorige Ladevorgang wird abgebrochen und seine Antwort,
    // falls sie doch noch eintrifft, am Zaehler erkannt und verworfen.
    bricheLadungAb();
    var seq = ++panelSeq;
    var halter = {};
    panelLadung = halter;
    loadFragment(url, undefined, function (html) {
      if (seq !== panelSeq) return;
      panelLadung = null;
      setzePanelInhalt(html, "wechsel", key);
    }, undefined, halter).catch(function () {
      if (seq !== panelSeq || umgeleitet) return;
      panelLadung = null;
      // Markierung und Adresse stehen schon auf dem neuen Dokument, der alte Inhalt bleibt
      // gesperrt: nur der Hinweis ist bedienbar.
      p.removeAttribute("aria-busy");
      panelHinweis("Die Ansicht konnte nicht geladen werden.");
    });
  }

  function schliessePanel(push, fokus) {
    var p = panelEl();
    if (!p || p.hidden) return;
    bricheLadungAb();
    panelSeq++;
    p.hidden = true;
    p.removeAttribute("data-fragment");
    p.innerHTML = "";
    panelHtml = "";
    panelDirty = false;
    panelKey = null;
    panelInhaltKey = null;
    p.removeAttribute("aria-busy");
    setzeContainerKlasse(false);
    markiereAktuelle();
    if (push) {
      window.history.pushState({}, "", mitDoc(
        window.location.pathname + (window.location.search || ""), null
      ));
    }
    if (fokus) {
      var zeile = letzterKey ? zeileFuer(letzterKey) : null;
      var link = zeile ? zeile.querySelector("td.filename a") : null;
      if (link && link.focus) link.focus();
    }
  }

  function istTitelLink(el) {
    return el.tagName === "A" && !!el.closest("td.filename");
  }

  // Klick auf eine Zeile oder ihren Titel oeffnet die Leiste. Modifikatoren und
  // Mittelklick behalten das normale Link-Verhalten (neuer Tab), ebenso Bedienelemente in
  // der Zeile — sie haben ihre eigene Aufgabe.
  document.addEventListener("click", function (ev) {
    var t = ev.target;
    if (!t || !t.closest) return;
    var schliesser = t.closest("[data-panel-close]");
    if (schliesser) {
      if (!istOffen()) return;
      ev.preventDefault();
      schliessePanel(true, true);
      return;
    }
    if (ev.defaultPrevented || ev.button !== 0) return;
    if (ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.altKey) return;
    if (!panelEl() || !window.history || !window.history.pushState) return;
    // Link in der Leiste mit data-panel-url (z.B. „Abbrechen“ der Export-Rueckfrage): laedt
    // das Fragment in die Leiste — dasselbe Dokument, also kein neuer Verlaufseintrag.
    var innen = t.closest("a[data-panel-url]");
    if (innen && panelEl().contains(innen)) {
      ev.preventDefault();
      oeffnePanel(innen.getAttribute("data-panel-url"), false);
      return;
    }
    var row = t.closest("tr[data-panel-url]");
    if (!row) return;
    var bedienelement = t.closest("input, select, textarea, button, label, form, a, summary");
    if (bedienelement && row.contains(bedienelement) && !istTitelLink(bedienelement)) return;
    ev.preventDefault();
    oeffnePanel(row.getAttribute("data-panel-url"), true);
  });

  // Zurueck-/Vorwaerts-Taste: Zustand aus ?doc= herstellen (auch Schliessen).
  window.addEventListener("popstate", function () {
    var p = panelEl();
    if (!p) return;
    var key = aktuellerDocParam();
    if (!key) { schliessePanel(false, false); return; }
    var zeile = zeileFuer(key);
    var url = zeile ? zeile.getAttribute("data-panel-url") : "";
    if (!url) {
      // Zeile nicht in der Liste (z.B. andere Seite): Fragment-URL aus dem Muster ableiten.
      var basis = p.getAttribute("data-fragment") ||
        (panelZeilen().length ? panelZeilen()[0].getAttribute("data-panel-url") : "");
      url = basis ? basis.replace(/\d+(?=(?:[?#].*)?$)/, key) : "";
    }
    if (url) oeffnePanel(url, false);
  });

  // Tastatur (Design D8) — nur bei offener Leiste.
  document.addEventListener("keydown", function (ev) {
    if (ev.defaultPrevented || !istOffen()) return;
    if (ev.ctrlKey || ev.metaKey || ev.altKey || ev.shiftKey) return;
    var t = ev.target;
    if (t && t.closest && (
      t.closest("input, select, textarea, [contenteditable], object") || t.closest(".doc-preview")
    )) return;
    var key = ev.key;
    var schritt = 0;
    if (key === "ArrowUp" || key === "k") schritt = -1;
    else if (key === "ArrowDown" || key === "j") schritt = 1;
    else if (key === "Escape") {
      ev.preventDefault();
      schliessePanel(true, true);
      return;
    } else if (key === "Enter") {
      // Auf Knoepfen und Links behaelt Enter seine eigene Aufgabe (z.B. „Schliessen“).
      if (t && t.closest && t.closest("button, a, summary")) return;
      var aktuell = panelKey ? zeileFuer(panelKey) : null;
      var ziel = aktuell ? aktuell.getAttribute("data-page-url") : null;
      if (!ziel) {
        var voll = panelEl().querySelector("a.panel-full");
        ziel = voll ? voll.getAttribute("href") : null;
      }
      if (ziel) { ev.preventDefault(); window.location.assign(ziel); }
      return;
    } else return;
    ev.preventDefault();
    var rows = panelZeilen();
    var idx = -1;
    for (var i = 0; i < rows.length; i++) {
      if (schluessel(rows[i].getAttribute("data-panel-url")) === panelKey) { idx = i; break; }
    }
    var neu = idx === -1 ? (schritt > 0 ? 0 : -1) : idx + schritt;
    if (neu < 0 || neu >= rows.length) return;  // Listenende: nichts tun
    oeffnePanel(rows[neu].getAttribute("data-panel-url"), true);
    if (rows[neu].scrollIntoView) rows[neu].scrollIntoView({ block: "nearest" });
  });

  // Eingaben in der Leiste merken (siehe panelBlockiert).
  function eingabeInLeiste(ev) {
    var p = panelEl();
    if (p && ev.target && p.contains(ev.target)) panelDirty = true;
  }
  document.addEventListener("input", eingabeInLeiste);
  document.addEventListener("change", eingabeInLeiste);

  // Formulare der Leiste (data-panel-form) laufen per fetch; die Routen antworten bei
  // X-Lector-Panel mit einem Redirect auf das Fragment, das hier die Leiste ersetzt.
  document.addEventListener("submit", function (ev) {
    var form = ev.target;
    var p = panelEl();
    if (!form || !form.matches || !form.matches("form[data-panel-form]")) return;
    if (!p || !p.contains(form) || !window.fetch) return;
    ev.preventDefault();
    if (form.getAttribute("data-sending")) return;  // Doppelklick
    // Der Inhalt gehoert noch zu einem anderen Dokument als dem gewaehlten (Wechsel laeuft):
    // eine Aktion wuerde sonst am falschen Dokument ankommen.
    if (panelInhaltKey !== panelKey) return;
    // Erst Daten lesen, dann sperren: gesperrte Knoepfe fielen sonst aus den Daten.
    var params = new URLSearchParams();
    new FormData(form).forEach(function (wert, name) {
      if (typeof wert === "string") params.append(name, wert);
    });
    var sender = ev.submitter;
    if (sender && sender.name) params.append(sender.name, sender.value || "");
    var knoepfe = form.querySelectorAll("button");
    form.setAttribute("data-sending", "1");
    for (var i = 0; i < knoepfe.length; i++) knoepfe[i].disabled = true;
    panelSendet++;
    // Das Dokument, zu dem das Formular gerendert wurde — nicht das, was inzwischen gewaehlt ist.
    var gesendetFuer = panelInhaltKey;
    var fokusIds = [form.id, sender && sender.id];
    var erfolg = false;
    var unklar = false;
    loadFragment(
      form.getAttribute("action") || p.getAttribute("data-fragment"),
      {
        method: (form.getAttribute("method") || "post").toUpperCase(),
        headers: { "X-Requested-With": "fetch", "X-Lector-Panel": "1" },
        body: params,
      },
      function (html, url) {
        erfolg = true;  // Die Aktion lief, auch wenn die Leiste inzwischen etwas anderes zeigt.
        // Nur uebernehmen, wenn die Leiste noch dieses Dokument zeigt.
        if (panelKey !== gesendetFuer || panelInhaltKey !== gesendetFuer || !istOffen()) return;
        // Landete der Redirect z.B. auf ?ask=1, soll auch der naechste Refresh dort bleiben.
        if (url) p.setAttribute("data-fragment", String(url).replace(/^https?:\/\/[^\/]+/, ""));
        setzePanelInhalt(html, "aktion", gesendetFuer, fokusIds);
      },
      undefined, undefined, POST_TIMEOUT_MS
    ).catch(function (fehler) {
      if (umgeleitet) return;
      var st = fehler && fehler.status;
      if (st >= 400 && st < 500) {
        panelHinweis("Die Aktion konnte nicht ausgeführt werden. Bitte erneut versuchen.");
      } else {
        // Zeitueberschreitung, Abbruch, 5xx: die Aktion kann trotzdem gelaufen sein.
        unklar = true;
        panelHinweis("Ergebnis unklar – bitte die Liste prüfen.");
      }
    }).then(function () {
      panelSendet--;
      form.removeAttribute("data-sending");
      for (var j = 0; j < knoepfe.length; j++) knoepfe[j].disabled = false;
      if (erfolg || unklar) refreshFragment(true);
    });
  });

  // Server hat die Leiste schon gerendert (?doc= beim Seitenaufruf): Zustand uebernehmen.
  (function () {
    var p = panelEl();
    if (!p || p.hidden || !p.getAttribute("data-fragment")) return;
    panelKey = schluessel(p.getAttribute("data-fragment"));
    panelInhaltKey = panelKey;
    letzterKey = panelKey;
    setzeContainerKlasse(true);
    markiereAktuelle();
  })();

  // Vor dem EventSource-Check: Ohne SSE-Unterstuetzung soll der Fortschritt trotzdem laufen.
  syncBatchPolling();
  aktualisiereAuswahlKnopf();

  if (!window.EventSource) return;
  var source = new EventSource("/events");
  var detail = currentDetail();
  var pending = false;

  // EventSource meldet bei onerror keinen Statuscode. Ob die Sitzung abgelaufen ist (401),
  // klaert deshalb ein leichter Statusaufruf. Der Browser verbindet nach Fehlern selbst
  // neu und feuert onerror dabei wiederholt — daher gedrosselt und nie parallel. Alles
  // ausser 401 (204, Netzwerkfehler, 404 im Modus ohne Anmeldung) bleibt beim bisherigen
  // Verhalten: Hinweis "Live-Verbindung unterbrochen".
  var SESSION_CHECK_MS = 5000;
  var letztePruefung = 0;
  var pruefLaeuft = false;

  function pruefeSitzung() {
    if (umgeleitet || pruefLaeuft) return;
    var jetzt = Date.now();
    if (letztePruefung && jetzt - letztePruefung < SESSION_CHECK_MS) return;
    letztePruefung = jetzt;
    pruefLaeuft = true;
    fetch("/auth/status", { cache: "no-store", credentials: "same-origin" })
      .then(function (r) { if (r.status === 401) zurAnmeldung(); })
      .catch(function () { /* Netzwerkfehler: kein Beleg fuer eine abgelaufene Sitzung */ })
      .then(function () { pruefLaeuft = false; });
  }

  source.onerror = function () { streamDown = true; updateLiveStatus(); pruefeSitzung(); };
  source.onopen = function () { streamDown = false; updateLiveStatus(); };

  source.onmessage = function (event) {
    var parts = String(event.data).split(":");
    var type = parts[0];
    var id = parseInt(parts[1], 10);
    // Auf einer Detailseite nur reagieren, wenn das betroffene Objekt gemeint ist.
    if (detail !== null && !passtZurDetailseite(detail, type, id)) return;
    // Waehrend eines Laufs laeuft der Takt schon — SSE wuerde nur verdoppeln.
    if (batchPolling) return;
    if (pending) return;
    pending = true;
    // kleine Entprellung, damit Bursts von Ereignissen zu einem Refresh führen
    setTimeout(function () { pending = false; refreshFragment(); }, 250);
  };
})();
