// Live-Updates via Server-Sent Events. Tokens haben die Form "doc:<id>" (Dokumente),
// "inv:<id>" (Paperless-Rechnungen) bzw. "batch:recipient" (Fortschritt des KI-Laufs).
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

  // Race statt reinem AbortController: Die Frist muss auch dann greifen, wenn
  // AbortController fehlt. Der Abbruch kommt obendrauf und gibt die Verbindung frei.
  function withDeadline(promise, abbruch) {
    return new Promise(function (resolve, reject) {
      var frist = setTimeout(function () {
        if (abbruch) abbruch.abort();
        reject(new Error("timeout"));
      }, FRAGMENT_TIMEOUT_MS);
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

  function applyRows(body, html) {
    var vorher = signaturen(body);
    body.innerHTML = html;
    var rows = body.querySelectorAll("tr[data-row-id]");
    for (var i = 0; i < rows.length; i++) {
      // Unbekannte id = neue Zeile, abweichende Signatur = geaenderte Zeile. Beides
      // verdient das Aufleuchten, unveraenderte Zeilen nicht.
      if (vorher[rows[i].getAttribute("data-row-id")] === rows[i].getAttribute("data-rev")) continue;
      markiere(rows[i]);
    }
  }

  function loadFragment(url, options, apply, mine) {
    var abbruch = typeof AbortController === "function" ? new AbortController() : null;
    var opts = {};
    if (options) { for (var k in options) opts[k] = options[k]; }
    if (abbruch) opts.signal = abbruch.signal;
    return withDeadline(
      fetch(url, opts)
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
        // Inhalt nur einsetzen, solange dieser Zyklus der juengste ist: sonst schreibt eine
        // spaet eintreffende Antwort aelteren Inhalt ueber den bereits aktuelleren.
        .then(function (html) { if (mine === cycle) apply(html); }),
      abbruch
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

  function refreshFragment() {
    var mine = ++cycle;
    var jobs = [];

    var table = document.querySelector("table.history[data-fragment]");
    if (table) {
      var body = table.querySelector("tbody");
      jobs.push(loadFragment(
        table.getAttribute("data-fragment"),
        { headers: { "X-Requested-With": "fetch" } },
        function (html) { if (body) applyRows(body, html); },
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
    return null;
  }

  // Vor dem EventSource-Check: Ohne SSE-Unterstuetzung soll der Fortschritt trotzdem laufen.
  syncBatchPolling();

  if (!window.EventSource) return;
  var source = new EventSource("/events");
  var detail = currentDetail();
  var pending = false;

  source.onerror = function () { streamDown = true; updateLiveStatus(); };
  source.onopen = function () { streamDown = false; updateLiveStatus(); };

  source.onmessage = function (event) {
    var parts = String(event.data).split(":");
    var type = parts[0];
    var id = parseInt(parts[1], 10);
    // Auf einer Detailseite nur reagieren, wenn das betroffene Objekt gemeint ist.
    if (detail !== null && (type !== detail.type || id !== detail.id)) return;
    // Waehrend eines Laufs laeuft der Takt schon — SSE wuerde nur verdoppeln.
    if (batchPolling) return;
    if (pending) return;
    pending = true;
    // kleine Entprellung, damit Bursts von Ereignissen zu einem Refresh führen
    setTimeout(function () { pending = false; refreshFragment(); }, 250);
  };
})();
