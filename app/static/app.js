// Live-Updates via Server-Sent Events. Bei jedem Dokument-Ereignis wird der dynamische
// Bereich der aktuellen Seite (Historientabelle bzw. Detailansicht) neu geladen und ersetzt.
(function () {
  "use strict";

  function refreshFragment() {
    var table = document.querySelector("table.history[data-fragment]");
    if (table) {
      var body = document.getElementById("history-body");
      fetch(table.getAttribute("data-fragment"), { headers: { "X-Requested-With": "fetch" } })
        .then(function (r) { return r.text(); })
        .then(function (html) { if (body) body.innerHTML = html; })
        .catch(function () {});
    }
    var detail = document.getElementById("detail");
    if (detail) {
      fetch(detail.getAttribute("data-fragment"))
        .then(function (r) { return r.text(); })
        .then(function (html) { detail.innerHTML = html; })
        .catch(function () {});
    }
  }

  function currentDocId() {
    var m = window.location.pathname.match(/^\/documents\/(\d+)/);
    return m ? parseInt(m[1], 10) : null;
  }

  if (!window.EventSource) return;
  var source = new EventSource("/events");
  var docId = currentDocId();
  var pending = false;

  source.onmessage = function (event) {
    var changedId = parseInt(event.data, 10);
    // Auf der Detailseite nur reagieren, wenn das betroffene Dokument gemeint ist.
    if (docId !== null && changedId !== docId) return;
    if (pending) return;
    pending = true;
    // kleine Entprellung, damit Bursts von Ereignissen zu einem Refresh führen
    setTimeout(function () { pending = false; refreshFragment(); }, 250);
  };
})();
