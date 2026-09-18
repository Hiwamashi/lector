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
  var stale = 0;

  function setStale(failed) {
    stale = failed ? stale + 1 : 0;
    var el = document.getElementById("live-status");
    if (el) el.hidden = stale === 0;
  }

  function refreshFragment() {
    var table = document.querySelector("table.history[data-fragment]");
    if (table) {
      var body = table.querySelector("tbody");
      fetch(table.getAttribute("data-fragment"), { headers: { "X-Requested-With": "fetch" } })
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
        .then(function (html) { if (body) body.innerHTML = html; setStale(false); })
        .catch(function () { setStale(true); });
    }
    var detail = document.getElementById("detail");
    if (detail && detail.getAttribute("data-fragment")) {
      fetch(detail.getAttribute("data-fragment"))
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
        .then(function (html) { detail.innerHTML = html; setStale(false); })
        .catch(function () { setStale(true); });
    }
    var batch = document.getElementById("batch-status");
    if (batch && batch.getAttribute("data-fragment")) {
      fetch(batch.getAttribute("data-fragment"))
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
        .then(function (html) { batch.innerHTML = html; setStale(false); })
        .catch(function () { setStale(true); });
    }
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

  source.onerror = function () { setStale(true); };
  source.onopen = function () { setStale(false); };

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
