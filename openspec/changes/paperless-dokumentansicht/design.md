# Design

## Context

Motivation siehe `proposal.md`. Ausgangslage im Code:

- **Paperless-Zugriff:** `PaperlessClient` (`app/paperless.py`) hat bereits `get_document`,
  `download_preview`, `correspondent_map`, `list_tags`, `list_custom_fields` und `get_notes`.
  Es fehlen: Dokumenttyp-ID→Name, Tag- und Feld-ID→Name als Maps, Notizen mit Verfasser und
  Zeitpunkt, die Felder `added`, `archive_serial_number` und `notes` in `_to_document`. Der
  Client hat keinen Cache; `PaperlessSync` öffnet pro Vorgang einen neuen Client
  (`_paperless()`) und hält nur Korrespondenten und das Empfänger-Feld im Speicher.
- **Freischaltung:** Rechnungen hängen an `sync.enabled` (Feature-Flag + URL + Token),
  Empfänger an `sync.recipient_enabled` (nur URL + Token). Die Vorschau
  (`sync.fetch_preview`) nimmt heute eine Lector-Rechnungs-ID und verlangt `enabled`.
- **Seiten und Fragmente:** Muster Seite + `/fragment/…` mit `#detail[data-fragment]`, das
  `app.js` bei SSE-Ereignissen neu lädt (`refreshFragment`). Listen ersetzen `tbody` per
  `applyRows` und Zeilen-Diff über `data-row-id`/`data-rev`.
- **Aktionen:** Alle Rechnungs- und Empfänger-Aktionen sind Formular-POSTs mit 303-Redirect
  zurück auf die Seite (`/invoices/{id}`, `_recipient_redirect`). Es gibt kein fetch-basiertes
  Absenden.
- **JS:** eine IIFE in ES5-Stil, kein History-API-Einsatz, keine Tastatur-Handler. `currentDetail()`
  erkennt Detailseiten über Pfad-Regex.
- **Zeilen-IDs sind uneinheitlich:** Rechnungen nutzen die Lector-Rechnungs-ID,
  Empfänger die Paperless-ID, Dokumente die Lector-Dokument-ID.
- **Zugangsschutz:** `AuthMiddleware` schützt jeden nicht ausdrücklich offenen Pfad; neue
  Routen sind automatisch geschützt, POSTs laufen durch die Herkunftsprüfung.

## Goals / Non-Goals

**Goals:**

- Ein Baustein (Fragment) für die Dokumentansicht, der als Seite und als Seitenleiste
  dient; keine zweite Darstellung.
- Seitenleiste ohne neue Abhängigkeiten, als Erweiterung des bestehenden Fragment-Musters.
- Bestehende Aktionen weiterverwenden statt sie für die Seitenleiste neu zu bauen.
- Ohne JavaScript bleibt alles bedienbar (Seite statt Leiste).

**Non-Goals:**

- Kein clientseitiges Rendering, kein Framework, kein Template-Duplikat in JS.
- Keine Persistenz von Paperless-Metadaten in SQLite; Lector liest bei jedem Öffnen frisch.
- Keine Verknüpfung von Scans mit Paperless (Folge-Change `scan-paperless-verknuepfung`).

## Decisions

### D1: Adresse `/paperless/{paperless_id}` als Seite, `/fragment/paperless/{paperless_id}` als Fragment

Die Paperless-ID ist die einzige ID, die Rechnungen und Empfänger gemeinsam haben, und sie
ist auch außerhalb von Lector bekannt. Das Fragment rendert ein neues Partial
`partials/paperless_doc_body.html` mit drei Teilen: Kopf (Titel, Absprung), Vorschau,
Metadaten, darunter ein Kontextbereich. Der Kontextbereich bindet bei einer bekannten
Rechnung (`repo` Lookup über `paperless_id`) die bestehenden Rechnungsabschnitte aus
`invoice_detail_body.html` ein und, wenn ein Empfänger-Feld existiert, das Empfänger-Formular.
Die Rechnungsabschnitte werden dazu in ein eigenes Partial `partials/invoice_sections.html`
herausgelöst, das beide nutzen.

*Alternative:* Rechnungsdetail behalten und eine zweite Ansicht für Nicht-Rechnungen bauen.
Verworfen, weil dann Vorschau, Metadaten und Absprung doppelt gepflegt würden.

`/invoices/{id}` antwortet künftig mit 303 auf `/paperless/{paperless_id}`;
`/fragment/invoices/{id}` liefert das neue Fragment für dieselbe Rechnung, damit offene Tabs
und SSE-Refresh weiterlaufen. Für unbekannte Rechnungs-IDs bleibt es bei 404.

### D2: Freischaltung über `recipient_enabled` (URL + Token), Rechnungsbereich zusätzlich über `enabled`

Die Ansicht braucht nur den Paperless-Zugang, nicht das Rechnungs-Feature. So funktioniert
sie auch für Nutzer, die nur die Empfänger-Zuordnung verwenden. Der Rechnungsbereich
erscheint nur, wenn `sync.enabled` gilt und Lector das Dokument als Rechnung führt.
Die Eigenschaft wird als `sync.view_enabled` benannt, um die Absicht lesbar zu machen
(gleiche Bedingung wie `recipient_enabled`).

### D3: Allgemeiner Vorschau-Proxy `/paperless/{id}/preview`

Neue Methode `PaperlessSync.fetch_document_preview(paperless_id)`, die ohne Rechnungs-Lookup
`download_preview` ruft. Die bestehende Prüfung (`_PREVIEW_TYPE_RE`, 415 bei anderen
Typen, 502 bei Paperless-Fehler) und die Header `X-Frame-Options: SAMEORIGIN` plus CSP
`default-src 'self'; script-src 'none'; frame-ancestors 'self'` werden in eine
Hilfsfunktion gezogen und von beiden Routen genutzt. `/invoices/{id}/preview` bleibt
bestehen und delegiert. `Cache-Control: private, max-age=300`, damit Hin- und
Herspringen mit j/k nicht jedes Mal neu lädt.

*Sicherheit:* Bewusst kein Abgleich gegen „Lector kennt dieses Dokument“ (vom Nutzer
entschieden). Die ID wird als `int` geparst, damit keine Pfadmanipulation zum
Paperless-API möglich ist.

### D4: Metadaten frisch lesen, Namenslisten mit kurzer Lebensdauer zwischenspeichern

Pro Öffnen: `GET /api/documents/{id}/` und `GET /api/documents/{id}/notes/` parallel
(`asyncio.gather`). Namen für Korrespondenten, Dokumenttypen, Tags und Custom Fields kommen
aus einem Cache in `PaperlessSync` mit 10 Minuten Lebensdauer (bisheriges `_corr_map` wird
darin aufgenommen und bekommt damit erstmals eine Invalidierung). Eine unbekannte ID
(z. B. neuer Tag seit dem letzten Abruf) löst einmal ein Neuladen der betroffenen Liste
aus, sonst erscheint `#<id>`.

*Alternative:* Metadaten in SQLite spiegeln. Verworfen: zusätzlicher Sync-Zustand für reine
Anzeige, veraltet sofort bei Änderungen in Paperless.

`PaperlessDocument` bekommt die Felder `added`, `archive_serial_number`, `page_count`
(optional, für die Vorschau-Beschriftung); `get_notes` bleibt, daneben kommt
`get_note_entries` mit Text, Verfasser und Zeitpunkt.

### D5: Seitenleiste als Container `#panel` mit `?doc=` in der URL

Jede Listenseite bekommt nach der Tabelle ein leeres `<aside id="panel" hidden>`. Zeilen
erhalten `data-panel-url` (Fragment) und `data-page-url` (Seite); der Titel-Link zeigt auf
die Seite, damit er ohne JS funktioniert. `app.js` fängt den Klick ab, lädt das Fragment
über das vorhandene `loadFragment`, setzt `?doc=<schlüssel>` per `history.pushState` und
markiert die Zeile (`aria-current="true"`). `popstate` stellt den Zustand her. Beim
Seitenaufruf mit `?doc=` rendert der Server die Leiste gleich mit (kein Flackern, ohne JS
sichtbar), JS übernimmt danach.

Der Schlüssel in `?doc=` ist je Liste die ID, die die Leiste braucht: Paperless-ID für
Rechnungen und Empfänger, Lector-Dokument-ID für die Dokumente-Liste. Rechnungszeilen
bekommen dazu `data-paperless-id`.

Die Leiste lädt beim SSE-Refresh mit: `refreshFragment` behandelt `#panel[data-fragment]`
wie `#detail`. `currentDetail()` lernt `/paperless/(\d+)` und den Leisten-Zustand, damit
Ereignisse gefiltert werden.

*Alternative:* `<dialog>` als Leiste. Verworfen für breite Fenster, weil ein modaler Dialog
die Liste sperrt; das Schieben-Layout braucht ein normales Element im Fluss.

### D6: Aktionen in der Leiste per fetch mit Fragment-Antwort

Formulare in der Leiste bekommen `data-panel-form`. `app.js` sendet sie per `fetch` mit
Kopf `X-Requested-With: fetch` und `X-Lector-Panel: 1`. Die bestehenden Routen bleiben, nur
ihr Redirect-Ziel ändert sich bei diesem Kopf: statt `/invoices/{id}` bzw. `/empfaenger?…`
leiten sie auf `/fragment/paperless/{paperless_id}` (mit `?ask=1`, wenn eine Rückfrage
nötig ist). fetch folgt dem 303 und erhält das Fragment, das die Leiste ersetzt. Danach löst
JS einen Listen-Refresh aus; der bestehende Zeilen-Diff markiert die geänderte Zeile.
Fehler (4xx/5xx) zeigt die Leiste als Hinweis, der Inhalt bleibt stehen.

*Alternative:* eigene JSON-Endpunkte. Verworfen: doppelte Validierung und doppelte Logik
für Rückfragen. Die Herkunftsprüfung für POSTs gilt bei fetch genauso.

### D7: Layout über CSS-Grid mit Container-Klasse, drei Stufen

`main.container` bekommt bei offener Leiste die Klasse `has-panel`. Ab 1280 px: Grid mit
`minmax(0, 1fr) minmax(28rem, 42%)`, die Leiste ist `position: sticky; top: …;
height: calc(100dvh - …)` und scrollt in sich. Spalten, die die Leiste zeigt, bekommen in
den Tabellen die Klasse `col-secondary` und werden unter `.has-panel` ausgeblendet. Zwischen
720 und 1280 px: Leiste `position: fixed` rechts, min(36rem, 90vw), mit Schatten über der
Liste. Unter 720 px: Vollbild mit Schließen-Knopf im Kopf. Die Vorschau in der Leiste nutzt
`clamp(18rem, 60dvh, 48rem)` statt der heutigen 70vh (ein `flex: 1` hätte eine Flex-Spalte um den ganzen Leisteninhalt verlangt). Neue Tokens in `DESIGN.md`: `panel-surface`,
`panel-border`, `row-current`.

### D8: Tastatur

Ein `keydown`-Handler auf `document`, aktiv nur bei offener Leiste. Er ignoriert Ereignisse
mit Modifikatortasten und solche, deren Ziel ein `input`, `select`, `textarea`,
`[contenteditable]` oder das `object` der Vorschau ist. Reihenfolge der Einträge ergibt sich
aus der aktuellen DOM-Reihenfolge der Zeilen mit `data-panel-url`. Am Listenende passiert
nichts (kein Seitenwechsel der Paginierung in diesem Change). `Esc` schließt und setzt den
Fokus auf den Titel-Link der zuletzt geöffneten Zeile.

## Risks / Trade-offs

- [Eingebettetes PDF fängt Tastatur und Scrollen ab] → Tasten wirken nur außerhalb der
  Vorschau; die Leiste bekommt nach dem Laden den Fokus auf ihre Überschrift, nicht auf das
  PDF.
- [Jedes Wechseln lädt bis zu drei Paperless-Anfragen] → Namen aus dem Cache,
  Vorschau mit `Cache-Control`, Dokument und Notizen parallel; laufende Ladevorgänge werden
  beim schnellen Weiterblättern per `AbortController` abgebrochen.
- [Herauslösen der Rechnungsabschnitte bricht bestehende Tests der Detailseite] → Tests
  prüfen Inhalte, nicht Template-Namen; Redirect-Tests werden angepasst.
- [Proxy gibt mit Lectors Token alle Dokumente frei] → vom Nutzer so entschieden;
  dokumentiert in `feature-documentation/` und `PRODUCT.md`, ID nur als Ganzzahl.
- [Uneinheitliche Zeilen-IDs] → die Leiste nutzt eigene `data-panel-url`-Attribute statt
  `data-row-id`; der bestehende Zeilen-Diff bleibt unverändert.
- [Breite Rechnungstabelle] → bei offener Leiste nur Titel, Datum, Betrag, Status sichtbar;
  ohne Leiste unverändert (Breitenproblem ohne Leiste bleibt ein eigener Punkt).

## Migration Plan

Keine Datenmigration. Rollout als normales Image-Update. Alte Links `/invoices/{id}`
leiten weiter. Rollback: vorheriges Image; es entstehen keine neuen Daten.

## Open Questions

- Ob die Paginierung beim Blättern mit `j` am Seitenende automatisch zur nächsten Seite
  springen soll, kann nach der ersten Nutzung entschieden werden.
