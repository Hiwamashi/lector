# Rechnungs-UI: Dokumentdatum, Sortierung & Dokumentvorschau

Erweiterungen der Rechnungsoberfläche (`/invoices` und `/invoices/{id}`) um drei
zusammenhängende Komfortfunktionen. Alle bauen auf dem bestehenden
[Sync-Feature](sync-und-aktionen.md) auf.

## 1. Dokumentdatum

Das Datum des Dokuments (Paperless-Feld `created`) wird mitgeführt und in Liste und
Detailansicht angezeigt.

- **Quelle:** `PaperlessClient._to_document` übernimmt `created` aus der Paperless-API in
  `PaperlessDocument.created` (`app/paperless.py`). Paperless liefert je nach Dokument ein
  reines Datum (`2026-06-06`) oder einen ISO-Zeitstempel — `Repository._parse_dt` verarbeitet
  beide.
- **Speicherung:** neue Spalte `document_date` in `paperless_invoices` (`app/db.py`). Bestehende
  Datenbanken werden über die Mini-Migration `_migrate()` in `init_db()` per `ALTER TABLE`
  nachgezogen (`CREATE TABLE IF NOT EXISTS` greift dort nicht).
- **Durchreichung:** `Repository.upsert_invoice(..., document_date=...)` wird aus beiden
  Sync-Pfaden (`_sync_invoices`, `_sync_sevdesk_tag`) mit `doc.created` befüllt und bei jedem
  Sync aktualisiert.
- **Anzeige:** Jinja-Filter `fmt_date` (Datum ohne Uhrzeit, `app/main.py`).

## 2. Sortierbare Spalten

Jede Spaltenüberschrift der Liste ist ein Sortier-Link.

- **Backend:** `Repository.list_invoices(sort=..., descending=...)`. Die Sortierspalte wird
  gegen die **Whitelist** `Repository.INVOICE_SORT_COLUMNS` aufgelöst (Schutz vor
  SQL-Injection) — ein unbekannter Wert fällt sicher auf `document_date` zurück. Sekundär wird
  stets nach `id DESC` sortiert, damit die Reihenfolge stabil bleibt.
- **Routen:** `/invoices` und `/fragment/invoices` nehmen `sort` und `dir` (`asc`/`dec`)
  entgegen; `_invoice_sort()` validiert beides. Default: Datum absteigend.
- **Template:** Das Makro `sort_th` in `invoices.html` erzeugt die Kopf-Links inkl. Pfeil-
  Indikator (▲/▼ aktiv, ⇅ inaktiv) und toggelt die Richtung der aktiven Spalte.
- **SSE-Kompatibilität:** Das `data-fragment`-Attribut der Tabelle trägt `sort`/`dir` mit, damit
  der automatische Live-Refresh (`app/static/app.js`) die gewählte Sortierung beibehält.

## 3. Sprung zum Dokument + eingebettete Vorschau

In der Detailansicht (`partials/invoice_detail_body.html`):

- **„In Paperless öffnen"-Link:** öffnet das Dokument in Paperless. Verwendet
  `PAPERLESS_PUBLIC_URL` (Fallback: `PAPERLESS_URL`). Wichtig, weil im Compose-Stack
  `PAPERLESS_URL` die container-interne Adresse (`http://webserver:8000`) ist, die im Browser
  **nicht** auflösbar ist.
- **Eingebettete PDF-Vorschau:** `<object data="/invoices/{id}/preview">`. Die Route
  `invoice_preview` (`app/main.py`) lädt die Vorschau serverseitig über
  `PaperlessSync.fetch_preview` → `PaperlessClient.download_preview` (Paperless-Endpoint
  `/api/documents/{id}/preview/`) und reicht sie über **Lectors eigene Origin** durch.

  **Warum Proxy statt direktem iframe?** Paperless sendet `X-Frame-Options: SAMEORIGIN`
  (gegen die Live-Instanz verifiziert). Ein iframe von Lectors Origin auf Paperless würde
  daher geblockt. Der Proxy liefert das PDF stattdessen von Lector selbst aus — same-origin,
  ohne Paperless-Session im Browser und ohne CORS-Probleme. Die Token-Auth läuft serverseitig.

## Konfiguration

| ENV | Default | Zweck |
|---|---|---|
| `PAPERLESS_PUBLIC_URL` | — | Browser-erreichbare Paperless-URL für den Sprung-Link. Leer = Fallback auf `PAPERLESS_URL`. Für die Vorschau **nicht** nötig. |

Die Vorschau ist aktiv, sobald `PAPERLESS_URL` und `PAPERLESS_TOKEN` gesetzt sind
(`preview_enabled` im Detail-Kontext).
