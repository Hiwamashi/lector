// Live-Updates via Server-Sent Events. Tokens haben die Form "doc:<id>" (Dokumente),
// "inv:<id>" (Paperless-Rechnungen) bzw. "batch:recipient" (Fortschritt des KI-Laufs).
// Bei einem passenden Ereignis wird der dynamische Bereich der aktuellen Seite
// (Listentabelle bzw. Detailansicht) neu geladen und ersetzt. Antworten mit Fehlerstatus
// (z.B. 503, wenn Paperless gerade nicht erreichbar ist) werden verworfen — der zuletzt
// erfolgreich geladene Inhalt bleibt dann stehen, statt durch eine Fehlermeldung zu
// verschwinden.
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

  function updateLiveStatus() {
    var el = document.getElementById("live-status");
    if (el) el.hidden = !(refreshFailed || streamDown);
  }

  function loadFragment(url, options, apply) {
    return fetch(url, options)
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
      .then(apply);
  }

  function refreshFragment() {
    var jobs = [];

    var table = document.querySelector("table.history[data-fragment]");
    if (table) {
      var body = table.querySelector("tbody");
      jobs.push(loadFragment(
        table.getAttribute("data-fragment"),
        { headers: { "X-Requested-With": "fetch" } },
        function (html) { if (body) body.innerHTML = html; }
      ));
    }
    var detail = document.getElementById("detail");
    if (detail && detail.getAttribute("data-fragment")) {
      jobs.push(loadFragment(
        detail.getAttribute("data-fragment"), undefined,
        function (html) { detail.innerHTML = html; }
      ));
    }
    var batch = document.getElementById("batch-status");
    if (batch && batch.getAttribute("data-fragment")) {
      jobs.push(loadFragment(
        batch.getAttribute("data-fragment"), undefined,
        function (html) { batch.innerHTML = html; }
      ));
    }
    if (!jobs.length) return;

    Promise.allSettled(jobs).then(function (results) {
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
    if (pending) return;
    pending = true;
    // kleine Entprellung, damit Bursts von Ereignissen zu einem Refresh führen
    setTimeout(function () { pending = false; refreshFragment(); }, 250);
  };
})();
