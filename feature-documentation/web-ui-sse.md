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
`<link rel="icon" type="image/svg+xml" href="/static/favicon.svg" />`. SVG statt `.ico`,
da kein Buildchain nötig ist und das Format im LAN-Browserumfeld ausreicht.

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
   eine tote SSE-Verbindung, obwohl dann gar keine Ereignisse mehr eintreffen. Ohne diesen Hinweis stünde
die Seite unbemerkt auf altem Stand — bei einem 45-Minuten-Lauf sähe eine eingefrorene
Tabelle genauso aus wie eine, in der gerade nichts passiert.

## Batch-Statusleiste

Der Zähltext (`12 / 100 verarbeitet`) steht **neben** dem Fortschrittsbalken, nicht darin:
Im Balken stand er als weiße Schrift auf der Füllung und war bei niedrigem Fortschritt
unlesbar, bei längeren Texten zusätzlich abgeschnitten (`overflow: hidden`). Der Balken
(`.batch-bar`) ist rein visuell und meldet seinen Stand über `role="progressbar"` samt
`aria-valuenow`. Die Zahlen nutzen `font-variant-numeric: tabular-nums`, damit die Anzeige
beim Hochzählen nicht springt. Die ältere Klasse `.progress` bleibt unverändert — sie wird
in der Dokument-Detailansicht für den kurzen Seitenfortschritt verwendet.
