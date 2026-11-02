# Rechnungs-UI: Export-Übersicht, Dokumentdatum, Sortierung & Dokumentvorschau

Erweiterungen der Rechnungsoberfläche (`/invoices`). Die Rechnungsdetailseite `/invoices/{id}` ist
seit dem Change `paperless-dokumentansicht` eine Weiterleitung auf die Dokumentansicht
(`/paperless/{paperless_id}`, siehe [dokumentansicht.md](dokumentansicht.md)). Abschnitt 1 bis 3 sind
die Komfortfunktionen des Sync-Features, Abschnitt 4 ist die Export-Übersicht des Changes
`sevdesk-export-uebersicht`. Alle bauen auf dem bestehenden
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
- **Durchreichung:** Beide Sync-Pfade (`_sync_invoices`, `_sync_sevdesk_tag`) übergeben `doc.created`
  als `document_date` an `Repository.upsert_invoices` (Einzelfall: `upsert_invoice`). Das Datum wird nur
  bei Neuanlage oder Änderung geschrieben, siehe [sync-und-aktionen.md](sync-und-aktionen.md#änderungserkennung-und-gesammeltes-schreiben).
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

In der Dokumentansicht (Kopf und Vorschau in `partials/paperless_doc_body.html`, Seite
`/paperless/{paperless_id}` bzw. Seitenleiste):

- **„In Paperless öffnen ↗"-Link:** öffnet das Dokument in Paperless. Verwendet
  `PAPERLESS_PUBLIC_URL` (Fallback: `PAPERLESS_URL`). Wichtig, weil im Compose-Stack
  `PAPERLESS_URL` die container-interne Adresse (`http://webserver:8000`) ist, die im Browser
  **nicht** auflösbar ist.
- **Eingebettete PDF-Vorschau:** `<object data="/paperless/{paperless_id}/preview">`. Die Route
  `paperless_preview` (`app/main.py`) lädt die Vorschau serverseitig über
  `PaperlessSync.fetch_document_preview` → `PaperlessClient.download_preview` (Paperless-Endpoint
  `/api/documents/{id}/preview/`) und reicht sie über **Lectors eigene Origin** durch. Die alte
  Adresse `/invoices/{id}/preview` delegiert an denselben Kern (`_preview_response`), nutzt aber
  `PaperlessSync.fetch_preview` und damit nur mit `FEATURE_PAPERLESS_SYNC`.

  **Warum Proxy statt direktem iframe?** Paperless sendet `X-Frame-Options: SAMEORIGIN`
  (gegen die Live-Instanz verifiziert). Ein iframe von Lectors Origin auf Paperless würde
  daher geblockt. Der Proxy liefert das PDF stattdessen von Lector selbst aus — same-origin,
  ohne Paperless-Session im Browser und ohne CORS-Probleme. Die Token-Auth läuft serverseitig.

## 4. Export-Übersicht (`/invoices`)

Die Rechnungsliste ist zugleich die Export-Übersicht. Es gibt keine zweite Seite: Zwei Listen
derselben Rechnungen mit unterschiedlichen Spalten würden auseinanderlaufen (Design 1). Jede
Zeile zeigt Einstufung, Abgleich und Exportsperren. Die Berechnung liegt in
`app/invoice_overview.py` (`build_rows`) und benötigt keinen Paperless-, SevDesk- oder KI-Aufruf.

### Spalten

| Spalte | Inhalt | Bedingung |
|---|---|---|
| Auswahl | Checkbox für die Mehrfachauswahl | nur bei aktivem SevDesk-Export; Checkbox nur bei Zeilen **ohne harte Sperre** |
| Datum | Dokumentdatum | immer |
| Titel | Link zur Dokumentansicht `/paperless/{paperless_id}`; mit Seitenleiste öffnet ein Klick die Leiste | immer |
| Korrespondent | Name | immer |
| Betrag | Betrag mit Währung | immer |
| Kontext | Bereichslabel, Konfidenz, Quelle | siehe [kontext-einstufung.md](kontext-einstufung.md) |
| Abgleich | Zustand mit Beleg-ID und ggf. Score | siehe [sevdesk-abgleich.md](sevdesk-abgleich.md) |
| GiroCode | Zahldaten-Status | immer |
| SevDesk | Export-Status | immer |
| Überwiesen | „Ja“ oder „—“ | immer |

Eine Spalte „Details“ mit eigenem Link gibt es nicht mehr. Der Titel führt zur Dokumentansicht.

Die Abgleich-Spalte zeigt je nach Zustand die Labels „Abgleich nicht verfügbar“, „In SevDesk“,
„Beleg in SevDesk nicht gefunden“, „Mögliche Dublette“, „Ohne Betrag nicht prüfbar“ oder
„Kein Treffer“.

Die Spalte SevDesk zeigt zusätzlich das Kennzeichen „Rückschrieb offen“, solange eine exportierte
Rechnung noch keinen erledigten Rückschrieb nach Paperless hat (siehe
[sync-und-aktionen.md](sync-und-aktionen.md)).

### Filter

Alle Filter sind kombinierbar (UND). Die Parameter stehen in der URL:

| Filter | Parameter | Wirkung |
|---|---|---|
| Kontext ab Schwelle | `ctx=it` | Bereich `it`: Konfidenz ≥ `SEVDESK_CONTEXT_MIN_CONFIDENCE` |
| Nicht exportiert | `open=1` | Status ist nicht `exported`, der Abgleich ist nicht „In SevDesk“ **und** die Zeile ist exportierbar (keine harte Sperre). Damit fallen auch `uncertain`, `exporting` und „Beleg in SevDesk nicht gefunden“ heraus |
| Mögliche Dublette | `dup=1` | Abgleich ist „Mögliche Dublette“ |
| Zu prüfen | `review=1` | SevDesk-Status `review` (Filter in SQL) |
| SevDesk-Status | `sevdesk=<status>` | Auswahl aus den Statuswerten (SQL) |
| Suche | `q=<text>` | Titel oder Korrespondent (SQL) |

Sortierung (`sort`, `dir`) und die Filter bleiben beim Sortieren, beim Live-Refresh und bei der
Rückkehr über das Feld `back` erhalten.

### Ladegrenze

- Ohne Python-seitige Filter lädt die Übersicht höchstens **200** Rechnungen
  (`UNFILTERED_LIMIT`).
- Sobald einer der Filter `ctx`, `open` oder `dup` aktiv ist, lädt sie bis zu **5000**
  Rechnungen (`FILTERED_LIMIT`). Einstufung und Abgleich werden in Python gefiltert, daher muss
  die Menge vorher vollständig sein.
- `review`, `sevdesk` und `q` wirken in SQL **vor** der Obergrenze. Die Grenze von 200 gilt dann
  für das Ergebnis nach dem Filter.
- Liegen mehr als 5000 Rechnungen im gefilterten Bestand, fehlen die übrigen. Die gewählte
  Sortierung wirkt vor der Grenze (Standard: Datum absteigend, also die neuesten zuerst).

### Kopfbereich

Die Statuszeile (`partials/invoice_overview_status.html`, Element `#overview-status`) zeigt:

- den Hinweis „Rechnungen sind nicht einstufbar“, wenn die Kontext-Option im Feld „Empfänger“
  fehlt (mit dem erwarteten Label),
- „Abgleich: Stand <Zeitpunkt>“ bzw. „Abgleich: noch nicht abgerufen“,
- bei einem fehlgeschlagenen letzten Abruf eine Fehlerbox mit Zeitpunkt, Grund und dem Hinweis,
  ob ein früherer Stand weiter angezeigt wird.

Knöpfe (nur bei aktivem SevDesk-Export):

- **„Abgleich aktualisieren“** → `POST /invoices/sevdesk-refresh`. Ruft den Belegabruf sofort auf
  und leitet zurück auf die Übersicht.
- **„Ausgewählte exportieren (n)“** → `POST /invoices/export-batch`. Der Knopf ist deaktiviert,
  solange nichts ausgewählt ist. Die Anzahl steht im Beschriftungstext.

### Mehrfachauswahl und Erhalt über den Live-Refresh

- Die Checkboxen tragen den Namen `ids` und hängen am Formular `batch-form`.
- Ein SSE-Refresh ersetzt die Tabelle vollständig. `app/static/app.js` merkt sich deshalb die
  gewählten IDs vor dem Tausch und stellt sie danach wieder her.
- Zeilen, die verschwunden sind oder keine Checkbox mehr haben (harte Sperre), fallen aus der
  Auswahl.

### Ergebnis des Mehrfachexports

`POST /invoices/export-batch` liefert **keine** Weiterleitung, sondern die Seite
`invoice_batch_result.html`:

- eine Zusammenfassung mit der Zahl der exportierten und der nicht exportierten Rechnungen,
- je Rechnung eine Zeile mit Titel, Ergebnis (Labels aus `EXPORT_RESULT_LABELS`) und Grund,
- ein Link „← Alle Rechnungen“, der über das Feld `back` mit den Filtern zurückführt.

Eine Rechnung mit Rückfragegrund wird übersprungen und nennt den Grund. Bestätigen lässt sich
dort nichts. Dafür gibt es die Dokumentansicht der Rechnung (`/paperless/{paperless_id}`).

### Rückkehr-URL (Feld `back`)

Die Formulare für Belegabruf und Mehrfachexport senden `back` mit. `_overview_back()` baut daraus
eine Rückkehr-URL, und zwar nur mit diesen Parametern: `q`, `sevdesk`, `ctx`, `open`, `dup`,
`review`, `sort`, `dir`. Nur Parameter mit Wert bleiben erhalten. Die URL ist immer relativ auf
`/invoices`. Ein fremder Pfad aus dem Formularfeld wird nie übernommen.

### Rechnungsbereich der Dokumentansicht

Die alte Adresse `/invoices/{id}` leitet mit 303 auf `/paperless/{paperless_id}` weiter (`?ask=1`
bleibt erhalten). Der Rechnungsbereich erscheint dort nur, wenn `FEATURE_PAPERLESS_SYNC` aktiv ist
und Lector das Dokument als Rechnung führt. Er steht in `partials/invoice_sections.html`, die Hinweise
oben in `partials/invoice_notices.html`. Der Rechnungsbereich zeigt zusätzlich zu den Zahldaten und dem Verlauf:

- **Kontext:** Bereichslabel, Konfidenz, Quelle und die Begründung je Quelle.
- **SevDesk-Abgleich:** der Zustand mit Beleg-ID. Bei „In SevDesk“ ein Link „In SevDesk öffnen“.
  Bei offenen ähnlichen Treffern eine Tabelle mit Beleg, Datum, Lieferant, Betrag und Score und
  den Knöpfen „Derselbe Beleg“ und „Anderer Beleg“. Die Entscheidung ist nur für offene Treffer
  möglich (Details in [sevdesk-abgleich.md](sevdesk-abgleich.md)).
- **Prüffall** (Status `review`): Box „Zu prüfen“ mit den **aktuellen** Gründen (bei harter Sperre
  mit „Aktuell gesperrt: …“). Darunter steht „Ursprünglicher Grund“ mit dem beim Vormerken
  gespeicherten Grund. Dazu „Trotzdem exportieren“ und „Verwerfen“. „Trotzdem exportieren“ sendet
  kein `confirm`. Bestehen Rückfragegründe, leitet die Route auf `?ask=1` um.
- **Rückschrieb offen:** Hinweis „Rückschrieb an Paperless offen — wird beim nächsten Sync
  nachgeholt.“, solange der Status `exported` ist und kein Rückschrieb erledigt wurde.
- **Zuletzt geändert:** Eintrag in den Rechnungsangaben (`partials/invoice_sections.html`) mit dem Wert
  der Spalte `last_synced_at`. Die Spalte heißt historisch so, bedeutet aber „zuletzt geändert“. Sie
  wird nur gesetzt, wenn der Sync die Rechnung neu anlegt oder eine ihrer gespiegelten Angaben (Titel,
  Korrespondent, Rechnungsdatum, Empfänger, Beleg-Vermerk) ändert. Ein Lauf ohne Änderung verschiebt
  den Zeitpunkt nicht. Werte aus der Zeit vor dem Change `paperless-sync-ohne-stillstand` bleiben
  erhalten und zeigen den letzten Lauf, bis sich die Rechnung ändert. Der Eintrag hieß vorher
  „Zuletzt synchronisiert“.
- **Rückfrage** (`?ask=1`): Box „Vor dem Export klären“ mit den Gründen und dem Knopf
  „Trotzdem exportieren“. Die Gründe werden bei jedem Aufruf neu berechnet. Der Block bleibt beim
  Live-Refresh stehen und verschwindet, sobald nichts mehr zu klären ist.
- **Export-Knopf:** deaktiviert ohne SevDesk-Export oder bei harter Sperre. Die Sperre steht als
  Text daneben („Export gesperrt: …“).

Ablauf des Export-Knopfs: Gibt es Rückfragegründe, leitet die Route auf `?ask=1` um. Ohne
Gründe erfolgt der Export, und die Seite wird neu geladen.

Das Feld „Empfänger“ (Zahldaten, Rückschrieb) und die Ereignisse der Rechnung sind in
[sync-und-aktionen.md](sync-und-aktionen.md) beschrieben.

## Konfiguration

| ENV | Default | Zweck |
|---|---|---|
| `PAPERLESS_PUBLIC_URL` | — | Browser-erreichbare Paperless-URL für den Sprung-Link. Leer = Fallback auf `PAPERLESS_URL`. Für die Vorschau **nicht** nötig. |

Die Vorschau der Dokumentansicht ist aktiv, sobald `PAPERLESS_URL` und `PAPERLESS_TOKEN` gesetzt sind
(`PaperlessSync.view_enabled`, unabhängig von `FEATURE_PAPERLESS_SYNC`). Das Kontextfeld
`preview_enabled` der früheren Detailseite wird von keinem Template mehr gelesen.

Die SevDesk-Variablen für die Übersicht (`SEVDESK_CONTEXT_LABEL`, `SEVDESK_CONTEXT_MIN_CONFIDENCE`,
`SEVDESK_MATCH_WINDOW_DAYS`, `SEVDESK_MATCH_MIN_SCORE`, `SEVDESK_VOUCHER_SYNC_MINUTES`) stehen in
[konfiguration.md](../konfiguration.md).
