# Web-UI & Live-Updates (SSE)

**Module:** `app/main.py` (Routen/App), `app/events.py` (SSE-Bus),
`app/templates/` (Jinja2), `app/static/` (CSS/JS)

## App & Lifespan

`app/main.py` baut die FastAPI-App. Im Lifespan werden `Settings`, `Repository` (mit
SSE-Notifier), OCR-Adapter und `Worker` erzeugt und gestartet; beim Herunterfahren sauber
gestoppt. Keine Authentifizierung (LAN-only, PRD §3.3).

## Routen

| Pfad | Zweck |
|---|---|
| `GET /` | Dashboard: Status-Kacheln + filterbare Historientabelle |
| `GET /fragment/history` | Tabellen-Fragment (Filter `status`,`q`,`period`) — auch für SSE-Refresh |
| `GET /documents/{id}` | Detailseite (Metadaten, Fortschritt, Verlauf, Fehler) |
| `GET /fragment/documents/{id}` | Detail-Fragment für SSE-Refresh |
| `GET /events` | SSE-Stream der geänderten `document_id` |
| `GET /healthz` | Health-Check |

## Live-Updates

- `EventBus`: Abonnenten sind asyncio-Queues. Der Worker (Threads) meldet Änderungen über
  `publish_threadsafe` → `loop.call_soon_threadsafe` speist die Verteilung in den Event-Loop.
- `/events` streamt `data: <id>`-Zeilen plus Keepalive-Kommentare.
- `app/static/app.js`: lauscht via `EventSource`; bei einem Ereignis wird (entprellt) das
  dynamische Fragment der aktuellen Seite per `fetch` neu geladen und ersetzt — auf der
  Detailseite nur, wenn die betroffene ID passt.

## Design

`app/static/app.css`: handgeschrieben, offline-fähig. Ruhiger „Werkstatt"-Look — neutrale
Grautöne, ein Akzent, Ampelfarben (grün/orange/rot) ausschließlich für Status. Hell-Modus,
Desktop-primär und responsive (PRD §5.1). Siehe Abweichungshinweis in [README.md](README.md).

## Favicon

`app/static/favicon.svg`: schlankes SVG-Favicon im Branding (Dokument-Glyph in der
Akzentfarbe `#2f6f8f`, passend zur Brand-Mark „▤"). Eingebunden in `base.html` per
`<link rel="icon" type="image/svg+xml" href="{{ static_url('favicon.svg') }}" />`. SVG statt `.ico`,
da kein Buildchain nötig ist und das Format im LAN-Browserumfeld ausreicht.

## Statische Dateien & Cache-Busting

`base.html` bindet CSS, JS und Favicon **nicht** über feste Pfade ein, sondern über den
Jinja-Global `static_url()` aus `app/main.py`:

```html
<link rel="stylesheet" href="{{ static_url('app.css') }}" />
<script src="{{ static_url('app.js') }}" defer></script>
```

`static_url()` hängt einen zehnstelligen SHA-256-Präfix des Dateiinhalts als `?v=…` an und
merkt sich das Ergebnis im Prozess. Ein neues Image heißt neuer Prozess und damit neue
URL; eine unveränderte Datei behält ihre URL und bleibt im Browser-Cache nutzbar.

**Warum das nötig ist:** Starlettes `StaticFiles` liefert `ETag` und `Last-Modified`, aber
**kein** `Cache-Control`. Ohne beides wenden Browser heuristisches Caching an (RFC 9111
§4.2.2, üblich: 10 % des Alters seit `Last-Modified`) und benutzen die Datei stundenlang
weiter, **ohne** zu revalidieren. Nach einem Deploy sah der Anwender dadurch frisches HTML
mit altem CSS/JS — konkret: die Batch-Statusleiste kam unformatiert (kein Fortschrittsbalken,
„Abbrechen" untereinander statt rechts) und der Zähler stand still, weil das gecachte
`app.js` das Batch-Fragment noch gar nicht kannte. Mehrere Fixes an `app.js` blieben
deshalb scheinbar wirkungslos: Sie sind nie im Browser angekommen.

Abgesichert durch `test_statische_dateien_tragen_einen_fingerabdruck` in `tests/test_web.py`.

## Paperless nicht erreichbar

`app/main.py` registriert einen `@app.exception_handler(httpx.HTTPError)`. Jeder
Paperless-Aufruf, der bis zur Route durchschlägt — typisch beim Hochfahren des Stacks,
wenn Paperless noch nicht antwortet —, endet dadurch in einer **503**-Antwort statt in
einem Internal Server Error mit Stacktrace:

- **Seiten** rendern `templates/unavailable.html` mit einer Erklärung und dem Hinweis,
  dass die Dokumentverarbeitung davon unberührt weiterläuft.
- **Fragmente** (`/fragment/…`) bekommen nur einen kurzen Hinweis-Absatz. Ihr Inhalt wird
  per `innerHTML` eingesetzt; eine komplette Fehlerseite würde die Tabelle zerschießen.

Ergänzend verwirft `app/static/app.js` Fragment-Antworten mit Fehlerstatus (`r.ok`), statt
sie einzusetzen — der zuletzt erfolgreich geladene Inhalt bleibt dann stehen.

**Damit das nicht still passiert**, blendet `app.js` in dem Fall die Hinweiszeile
`#live-status` aus `base.html` ein („Live-Aktualisierung unterbrochen — die Anzeige kann
veraltet sein"). Sie verschwindet beim nächsten erfolgreichen Refresh von selbst. Ausgelöst
wird sie auch, wenn die SSE-Verbindung abreißt (`source.onerror`).

Zwei Fallstricke stecken in dieser Zustandsführung, beide durch
`tests/test_app_js.py` abgesichert (Node-Harness mit gefaktem DOM, übersprungen wenn kein
`node` vorhanden ist):

1. **Auswertung pro Zyklus, nicht pro Request.** `refreshFragment()` lädt bis zu drei
   Fragmente parallel. Der Zustand wird über `Promise.allSettled` erst bestimmt, wenn alle
   durch sind — sonst blendet ein erfolgreicher Parallel-Request den Hinweis wieder aus,
   obwohl ein anderer im selben Zyklus fehlgeschlagen ist.
2. **Getrennte Ursachen.** Fehlgeschlagener Refresh (`refreshFailed`) und abgerissener
   Stream (`streamDown`) werden getrennt geführt. Sonst überdeckt ein gelungener Refresh
   eine tote SSE-Verbindung, obwohl dann gar keine Ereignisse mehr eintreffen.
3. **Nur der jüngste Zyklus wirkt — in beide Richtungen.** Jeder Aufruf zieht eine
   Sequenznummer (`cycle`). Verworfen wird bei einem überholten Zyklus **sowohl** das
   Statusergebnis **als auch** der geladene Inhalt (`loadFragment` prüft vor `apply`). Die
   Entprellung von 250 ms verhindert nur Bursts, nicht einen langsamen Zyklus, dessen
   Antwort nach der eines später gestarteten eintrifft — sonst überschreibt ein veralteter
   Erfolg den aktuellen Fehlerzustand, oder eine verspätete Antwort setzt älteren
   Tabelleninhalt über den bereits aktuelleren. Ohne diesen Hinweis stünde
die Seite unbemerkt auf altem Stand — bei einem 45-Minuten-Lauf sähe eine eingefrorene
Tabelle genauso aus wie eine, in der gerade nichts passiert.

## Aufleuchten geänderter Zeilen

Die Historientabelle aktualisiert sich von selbst; ein einfacher `innerHTML`-Tausch macht diese Änderung unsichtbar — die Zeile steht danach genauso da wie vorher, nur mit anderem Inhalt. Wer nicht zufällig hinsieht, bemerkt nichts und vergleicht gegen sein Gedächtnis.

Deshalb markiert `app.js` nur die Zeilen optisch, die sich **wirklich** geändert haben.

### Wie es funktioniert

Jede Listenzeile trägt zwei Attribute:
- **`data-row-id`**: eindeutige Kennung (z. B. `doc.id`)
- **`data-rev`**: Signatur der veränderlichen Felder, z. B. `"processing:5:12:1"` (status:processed_pages:total_pages:attempt_count)

Der Workflow (in `app.js` Funktionen `signaturen()`, `applyRows()`, `markiere()`):

1. **Vor dem HTML-Tausch:** `signaturen(container)` scannt alle Zeilen und erstellt eine Map `{ row-id → data-rev }`.
2. **HTML wird neu geladen** und ersetzt den `tbody`-Inhalt.
3. **Nach dem Tausch:** Die neuen Zeilen werden gegen die alte Map abgeglichen.
4. **Markierung:** Nur Zeilen, deren `data-rev` sich **geändert hat** oder deren `data-row-id` völlig neu ist, bekommen die Klasse `.row-updated`. Diese stellt den Hintergrund für `FLASH_MS` (1600 ms) auf Akzent-Farbe ein und entfernt die Klasse dann per Timeout.

### Vergleich läuft über die ID, nicht die Position

Eine Zeile, die nur um ein oder zwei Positionen nach oben rutscht (weil eine frühere Zeile den Status wechselte), leuchtet **nicht** auf — nur die Zeilen mit geändertem `data-rev`. Das ist wichtig für lange Listen, in denen ständig Zeilen neu sortiert werden würden.

### Warum nicht `animationend`?

Die Klasse wird per `setTimeout` entfernt, nicht per `animationend`-Ereignis. Unter `prefers-reduced-motion: reduce` läuft die Animation nicht, es feuert also kein `animationend`. Eine Zeile bliebe dauerhaft markiert. Mit Timeout funktioniert es in beiden Modi.

### Wichtiger Hinweis für künftige Änderungen

**Wer ein Feld ergänzt, das sich im Betrieb ändern kann, muss es auch in `data-rev` aufnehmen,** sonst bleibt die Änderung unsichtbar.

Beispiel aus `partials/history_rows.html` (Zeile 16):
```html
data-rev="{{ doc.status }}:{{ doc.processed_pages }}:{{ doc.total_pages }}:{{ doc.attempt_count }}"
```

Wenn z. B. ein neues Feld `doc.error_code` hinzukommt und sich beim Fehlerfall ändert, muss es auch in `data-rev` aufgenommen werden:
```html
data-rev="{{ doc.status }}:{{ doc.processed_pages }}:{{ doc.total_pages }}:{{ doc.attempt_count }}:{{ doc.error_code }}"
```

### Test-Abdeckung

Die Logik wird in `tests/test_app_js.py` über einen Node-Harness abgedeckt, der ein gefaktes DOM bietet. Das Test-Skript wird übersprungen, wenn `node` nicht vorhanden ist.

## Batch-Statusleiste

Sitzt in `partials/batch_status.html` und wird während eines Laufs als eigene Karte
gerendert — sie ist der einzige Bereich der Seite, der sich von selbst bewegt.

- **Zähltext neben dem Balken, nicht darin.** Im Balken stand er als weiße Schrift auf der
  Füllung, war bei niedrigem Fortschritt unlesbar und bei längeren Texten abgeschnitten
  (`overflow: hidden`). Die Zahlen nutzen `font-variant-numeric: tabular-nums`, damit die
  Anzeige beim Hochzählen nicht springt.
- **Segmentierter Balken.** Ein Lauf hat drei Ausgänge, und der Balken zeigt sie getrennt:
  `.batch-seg--done` (Akzent), `--skipped` (Amber), `--failed` (Rot) — dieselben Farben, die
  die App sonst für Status benutzt. Ein einfarbiger Balken würde behaupten, alles Gefüllte
  sei erledigt. Nullwerte erzeugen weder ein Segment noch einen Legendeneintrag.
- **Puls an der Füllkante** (`.batch-pulse`). Ein einzelnes Dokument kann Sekunden dauern,
  in denen keine Zahl sich bewegt; ohne Puls sieht ein gesunder Lauf aus wie ein hängender.
  Unter `prefers-reduced-motion: reduce` steht er still.
- **Barrierefreiheit:** `role="progressbar"` mit `aria-valuenow` und `aria-valuetext`.
- Die ältere Klasse `.progress` bleibt unverändert — sie trägt in der Dokument-Detailansicht
  den kurzen Seitenfortschritt.

### Fortschritt hängt nicht allein an SSE

Solange ein Lauf läuft, trägt das Fragment `data-batch-running`. `app.js` fragt daraufhin
von sich aus nach (`syncBatchPolling`/`scheduleBatchPoll`, Pause = `BATCH_PUBLISH_INTERVAL`
im Backend, 2 s) und ignoriert in dieser Zeit SSE-Ereignisse, die den Refresh nur verdoppeln
würden. Endet der Lauf, verschwindet das Attribut und der Takt wird abgeschaltet.

**Jeder Fragment-Request hat eine Frist** (`FRAGMENT_TIMEOUT_MS`, 15 s, in `loadFragment`).
`fetch` bricht von sich aus nie ab, und `Promise.allSettled` löst erst auf, wenn **alle**
Teil-Requests durch sind — ein hängender Request (gestauter Proxy, halboffene Verbindung)
hielte den Takt sonst dauerhaft an, weil der nächste Zyklus erst nach dem Abschluss des
vorigen geplant wird. Die Frist ist als `Promise.race` gebaut (`withDeadline`), damit sie
auch ohne `AbortController` greift; ist einer da, wird der Request zusätzlich abgebrochen
und die Verbindung freigegeben. Ein abgelaufener Request zählt als Fehlschlag und blendet
den Veraltet-Hinweis ein — bis der nächste Zyklus gelingt. Abgesichert durch
`test_haengender_request_haelt_den_abfragetakt_nicht_an`.

**Die Pause liegt zwischen den Zyklen, nicht in einem festen Raster.** Ein
`setInterval(refreshFragment, 2000)` zieht bei jedem Tick die Sequenznummer `cycle` hoch.
Braucht eine Antwort länger als die Pause — bei einem Lauf der Normalfall, das Fragment
kostet einen Paperless-Zählaufruf —, ist sie beim Eintreffen überholt und wird vom
Veralterungsschutz in `loadFragment` verworfen. Bei durchgehend langsamen Antworten kommt
dann **kein einziger** Stand an und die Zahl steht still, obwohl im Sekundentakt gefragt
wird: genau der Zustand, den der Takt beheben soll. `scheduleBatchPoll` plant den nächsten
Zyklus deshalb erst, wenn der vorige durch ist. Abgesichert durch
`test_langsame_antworten_halten_den_fortschritt_nicht_an` (Node-Harness mit Zeitraffer:
Poll-Pause und Antwortzeiten werden mit demselben Faktor gestaucht, die Reihenfolge der
Ereignisse bleibt dadurch erhalten).

Grund: `text/event-stream` wird von Reverse Proxies gern gepuffert. Die Verbindung wirkt
dann äußerlich gesund — `onerror` feuert nicht, der Veraltet-Hinweis erscheint nicht —,
während kein Ereignis mehr ankommt und der Zähler stillsteht. Der Takt kostet nur während
eines Laufs etwas und macht den Fortschritt unabhängig von dieser Eigenart. Nebeneffekt:
Browser ohne `EventSource` zeigen den Fortschritt ebenfalls (`syncBatchPolling()` läuft vor
dem Feature-Check).
