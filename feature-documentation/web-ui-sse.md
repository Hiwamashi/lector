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
