// Live-Updates via Server-Sent Events. Tokens haben die Form "doc:<id>" (Dokumente) bzw.
// "inv:<id>" (Paperless-Rechnungen). Bei einem passenden Ereignis wird der dynamische Bereich
// der aktuellen Seite (Listentabelle bzw. Detailansicht) neu geladen und ersetzt.
(function () {
  "use strict";

  function refreshFragment() {
    var table = document.querySelector("table.history[data-fragment]");
    if (table) {
      var body = table.querySelector("tbody");
      fetch(table.getAttribute("data-fragment"), { headers: { "X-Requested-With": "fetch" } })
        .then(function (r) { return r.text(); })
        .then(function (html) { if (body) body.innerHTML = html; })
        .catch(function () {});
    }
    var detail = document.getElementById("detail");
    if (detail && detail.getAttribute("data-fragment")) {
      fetch(detail.getAttribute("data-fragment"))
        .then(function (r) { return r.text(); })
        .then(function (html) { detail.innerHTML = html; })
        .catch(function () {});
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
