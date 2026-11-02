# Dokumentansicht: Paperless-Dokumente in Lector

**Module:** `app/main.py` (Routen, `_paperless_view_context`, `_preview_response`,
`_list_panel_context`, `_invoice_redirect`, `_recipient_redirect`), `app/paperless_sync.py`
(`view_enabled`, `load_document_view`, `fetch_document_preview`, `_names`), `app/paperless.py`
(Client-Helfer), `app/auth.py` (Zugangsschutz), Templates `paperless_doc.html`,
`partials/paperless_doc_body.html`, `partials/document_panel.html` (Vorgangsleiste, bettet die Ansicht
ein), `partials/panel_aside.html`, `partials/panel_bar.html`,
`partials/invoice_sections.html`, `partials/invoice_notices.html`, Listen-Partials
`partials/invoice_rows.html`, `partials/recipient_rows.html`, `partials/history_rows.html`;
`app/static/app.js` (Abschnitt „Seitenleiste“), `app/static/app.css` (Abschnitt „Seitenleiste neben
den Listen“).

## Zweck

Lector zeigt ein Paperless-Dokument lesend: Vorschau, Metadaten und Notizen. Die Ansicht gibt es
als eigene Seite `/paperless/{paperless_id}` und als Seitenleiste neben den Listen Rechnungen,
Empfänger und Dokumente. Ist ein Vorgang der Dokumente-Liste mit seinem Paperless-Dokument verknüpft,
bettet die Vorgangsansicht dieselbe Darstellung ein (siehe „Einbettung in die Vorgangsansicht“).
Sie gilt für jedes Dokument, das Lectors Paperless-Token lesen darf, nicht
nur für Rechnungen.

Bearbeitet werden nur Angaben, die Lector schon vorher bearbeitete: Empfänger, Rechnungsdaten
(Betrag, IBAN, BIC, Verwendungszweck, „überwiesen“) und der SevDesk-Export. Tags, Korrespondent,
Dokumenttyp, Titel, Archivnummer, Notizen und Custom Fields sind nur sichtbar. Die Grenze steht in
[PRODUCT.md](../../PRODUCT.md).

Der Rechnungsbereich ist die frühere Rechnungsdetailseite. Sie ist jetzt Teil der Dokumentansicht
und erscheint nur bei Dokumenten, die Lector als Rechnung führt.

Entscheidungen im Code:

- Die Paperless-ID ist der Schlüssel der Ansicht. Rechnungen und Empfänger haben sie gemeinsam.
  Die Lector-Rechnungs-ID ist nur für den Rechnungsbereich nötig.
- Paperless-Metadaten werden bei jedem Öffnen frisch gelesen. SQLite spiegelt sie nicht. Lokal
  liegen nur die Rechnungsdaten und der KI-Vorschlag-Cache.
- Seite und Seitenleiste nutzen dasselbe Fragment (`partials/paperless_doc_body.html`). Es gibt keine
  zweite Darstellung.

## Freischaltung

| Bedingung | Wirkung |
|---|---|
| `PAPERLESS_URL` und `PAPERLESS_TOKEN` gesetzt (`PaperlessSync.view_enabled`) | Dokumentansicht, Vorschau-Proxy `/paperless/{id}/preview`, Seitenleiste in Rechnungen, Empfänger und Dokumenten (Dokumente zeigt sie auch ohne Paperless) |
| zusätzlich `FEATURE_PAPERLESS_SYNC=true` (`PaperlessSync.enabled`) | Rechnungsbereich erscheint bei Dokumenten, die Lector als Rechnung führt. Die bisherige Vorschau `/invoices/{id}/preview` antwortet nur mit diesem Feature |
| URL oder Token fehlt | `/paperless/{id}` und `/fragment/paperless/{id}` antworten mit 404, die Vorschau ebenfalls. Die Rechnungsliste zeigt keine Seitenleiste |

Der Rechnungsbereich braucht außerdem, dass Lector das Dokument als Rechnung kennt
(`repo.get_invoice_by_paperless`). Ohne Eintrag erscheinen nur die Paperless-Angaben und der
Empfänger.

Das Empfänger-Formular erscheint nur, wenn das Custom Field `CF_RECIPIENT` (Standard „Empfänger“)
am Dokument existiert (`recipient_field_present`). Der KI-Vorschlag-Knopf erscheint nur bei
`FEATURE_RECIPIENT_LLM=true` mit `ANTHROPIC_API_KEY` (`PaperlessSync.recipient_llm_enabled`).

## Einbettung in die Vorgangsansicht

Die Vorgangsansicht der Dokumente-Liste (`/documents/{id}`, `/fragment/documents/{id}` und die
Seitenleiste) bettet diese Ansicht ein, wenn der Vorgang verknüpft ist (`link_state = embedded` in
`_document_context`, `app/main.py`). Dafür gibt es in `partials/paperless_doc_body.html` den Schalter
`embedded`:

- Die Leiste oben (`panel_bar`) und der Titel `h1#panel-title` entfallen. Beides gehört der umgebenden
  Vorgangsleiste. Der Titel wird zu einem `h2`.
- Alle übrigen Abschnitte (Vorschau, Angaben, Felder, Notizen, Empfänger und Rechnungsbereich) bleiben
  gleich.
- Formulare in der eingebetteten Ansicht senden das Feld `back=doc:<id>` (`partials/back_field.html`).
  Die Antwort führt dann zurück in die Vorgangsansicht und nicht in die Listen-Seitenleiste.

Ohne Verknüpfung zeigt die Vorgangsansicht stattdessen das lokale Original, und bei nicht erreichbarem
oder gelöschtem Paperless-Dokument einen Hinweis. Aufbau, Zustände und den Rückweg beschreibt
[scan-verknuepfung.md](scan-verknuepfung.md#leiste-vorgang-und-dokument-zusammen).

## Routen

| Methode und Pfad | Wirkung |
|---|---|
| `GET /paperless/{paperless_id}` | Dokumentansicht als eigene Seite. `?ask=1` zeigt die Rückfrage nach einem Export-Versuch. 404 mit Hinweistext bei fehlender Anbindung, unbekannter ID oder 403/404 von Paperless |
| `GET /fragment/paperless/{paperless_id}` | Fragment `partials/paperless_doc_body.html` für die Seitenleiste und den SSE-Refresh. `?ask=1` wird durchgereicht. 404 mit leerem Body wie oben |
| `GET /paperless/{paperless_id}/preview` | PDF- bzw. Bildvorschau über Lector (Proxy), siehe Abschnitt „Vorschau-Proxy und Sicherheit“ |
| `GET /invoices/{invoice_id}` | Alte Adresse der Rechnungsdetailseite. 303 auf `/paperless/{paperless_id}`, `?ask=1` bleibt erhalten. Unbekannte Rechnung: 404 |
| `GET /fragment/invoices/{invoice_id}` | Fragment der Dokumentansicht für dieselbe Rechnung, damit offene Tabs mit der alten Adresse per SSE weiter laufen. Unbekannte Rechnung: 404 |
| `GET /invoices/{invoice_id}/preview` | Bisherige Vorschau-Adresse. Läuft über `PaperlessSync.fetch_preview` und braucht `FEATURE_PAPERLESS_SYNC` |

### Seitenleiste per Adresse

Die Listen öffnen die Leiste serverseitig, wenn `?doc=` gesetzt ist (`_list_panel_context`):

| Liste | Schlüssel in `?doc=` | Inhalt der Leiste |
|---|---|---|
| `GET /invoices?doc=<paperless_id>` | Paperless-ID | Dokumentansicht (Rechnungsbereich, wenn vorhanden) |
| `GET /empfaenger?doc=<paperless_id>` | Paperless-ID | Dokumentansicht |
| `GET /?doc=<lector_dokument_id>` | Lector-Dokument-ID | Vorgangsleiste (`partials/document_panel.html`) aus `GET /fragment/documents/{id}`: Kopf, Verlauf und darunter die eingebettete Paperless-Ansicht oder das lokale Original. Siehe „Einbettung in die Vorgangsansicht“ |

Ein unbekannter Schlüssel lässt die Leiste zu, die Liste bleibt vollständig. Ist Paperless beim
Öffnen nicht erreichbar, bleibt die Liste bedienbar und die Leiste zeigt den Hinweis „Paperless ist
derzeit nicht erreichbar. Die Liste bleibt bedienbar.“ (`panel_error`).

### Aktionen mit Kopf `X-Lector-Panel: 1`

Formulare der Leiste senden den Kopf `X-Lector-Panel: 1` (siehe „Aktionen in der Seitenleiste“).
Die Routen leiten dann auf das Fragment um, statt auf die volle Seite:

| Route | Ohne Kopf | Mit Kopf `X-Lector-Panel: 1` |
|---|---|---|
| `POST /invoices/{id}/giro`, `/export`, `/dismiss`, `/paid`, `/matches/{voucher_id}` | 303 auf `/invoices/{id}` (bei Export mit Rückfrage `?ask=1`) | 303 auf `/fragment/paperless/{paperless_id}` (bei Rückfrage mit `?ask=1`) |
| `POST /empfaenger/{paperless_id}` und `/empfaenger/{paperless_id}/suggest` | Formfeld `view=doc`: 303 auf `/paperless/{paperless_id}`. Sonst 303 auf `/empfaenger?…` mit Seite und Filtern | 303 auf `/fragment/paperless/{paperless_id}` |

Der Kopf ändert nur das Ziel. Die Herkunftsprüfung für POST gilt weiterhin (siehe unten).

## Angezeigte Daten

Die Daten kommen als `DocumentView` aus `PaperlessSync.load_document_view`. Dokument und Notizen
werden parallel gelesen (`asyncio.gather`).

- **Kopf:** Titel (fehlt er, `#<id>`), bei Rechnungen die Badges GiroCode und SevDesk, und der Link
  „In Paperless öffnen ↗“. Der Link nutzt `PAPERLESS_PUBLIC_URL` und fällt auf `PAPERLESS_URL` zurück.
  Er zeigt auf `/documents/{id}/details` und öffnet in einem neuen Tab.
- **Dokument:** `<object>` mit der Vorschau. Ohne Vorschau steht „Keine Vorschau verfügbar“ mit den
  Links „In neuem Tab öffnen“ und „In Paperless öffnen ↗“.
- **Angaben aus Paperless:** Korrespondent, Dokumenttyp, „Ausgestellt“ (Paperless-Feld `created`),
  „Hinzugefügt“ (`added`), Archivnummer (ASN), Seiten (`page_count`), Paperless-ID und Tags als
  Badges. Tags sind nur Namen, ohne Bedienelement.
- **Felder:** alle Custom Fields mit Name und Wert. Leere Werte zeigen „—“, Wahrheitswerte
  „Ja“/„Nein“, Listen werden kommagetrennt. Bei Select-Feldern steht das Label statt der
  Options-ID. Das Feld „Empfänger“ erscheint hier ebenfalls, mit dem Label des gesetzten Werts.
- **Notizen:** Zeitpunkt (`fmt_iso_dt`, Ortszeit), Verfasser (sonst „—“) und Text. Quelle ist
  `PaperlessClient.get_note_entries`.
- **Empfänger:** Auswahlfeld mit allen Optionen des Felds und „— kein —“. Der gesetzte Wert ist
  vorausgewählt.
- **Rechnungsbereich** (nur bei Rechnung und `FEATURE_PAPERLESS_SYNC`): Hinweise zu Fehlern und
  Rückfragen (`invoice_notices.html`), dann Kontext, SevDesk-Abgleich, Zahldaten, Aktionen,
  Rechnungsdaten und Verlauf (`invoice_sections.html`). Die Abschnitte sind dieselben wie vorher in
  der Rechnungsdetailseite.

Fehlende Angaben erscheinen als „—“ und werden nicht ausgelassen. Das gilt für Korrespondent,
Dokumenttyp, Datum, ASN, Seiten, Tags, Felder und Notizen.

### Namens-Cache

Paperless liefert Korrespondenten, Dokumenttypen, Tags und Feld-IDs nur als IDs. Die Namen kommen
aus `PaperlessSync._names(client, kind, need)`:

- **Arten:** `correspondent` (`correspondent_map`), `document_type` (`document_type_map`), `tag`
  (`tag_map`) und `field` (`custom_field_map`). Bei `field` werden in derselben Abfrage die
  Select-Optionen je Feld mitgeladen (`_field_options`).
- **Lebensdauer:** `NAME_CACHE_TTL = 600.0` Sekunden (10 Minuten). Der Cache liegt im Speicher des
  Prozesses, nicht in SQLite.
- **Neuladen:** Ist eine Liste älter als die Lebensdauer, lädt `_names` sie neu. Fehlt eine benötigte
  ID, lädt es genau einmal je Aufruf neu. Bleibt die ID unbekannt, zeigt die Ansicht `#<id>`.
- **Weitere Nutzer des Caches:** `_corr_map_cached` (Empfänger-Liste) liest den Korrespondenten über
  denselben Cache. Der periodische
  Sync `sync_once` ruft `correspondent_map()` bewusst ohne Cache auf (`app/paperless_sync.py`,
  Kommentar bei dem Aufruf).
- **Empfänger-Feld:** `_recipient_field_cached` löst das Feld einmal je Prozess auf, auch das
  Ergebnis „kein Feld“. Danach aktualisiert es der periodische Sync `sync_once`, sofern er läuft.
  Ohne Sync bleibt die einmal aufgelöste Fassung bis zum Neustart.

## Seitenleiste

### Aufbau

`partials/panel_aside.html` setzt `<aside id="panel" class="panel" aria-label="Dokumentansicht">`
unter jede Liste, nach der Tabelle. Ohne `?doc=` ist die Leiste `hidden` und leer. Ihr Kopf
(`partials/panel_bar.html`) enthält „Schließen ✕“ (`data-panel-close`) und „Als Seite öffnen“.

Die Zeilen tragen die Adressen, die `app.js` braucht:

| Liste | Zeilenattribute | Titel-Link (ohne JavaScript) |
|---|---|---|
| Rechnungen (`invoice_rows.html`) | `data-panel-url="/fragment/paperless/{paperless_id}"`, `data-page-url="/paperless/{paperless_id}"`, `data-paperless-id` | `/paperless/{paperless_id}` |
| Empfänger (`recipient_rows.html`) | `data-panel-url`, `data-page-url` mit der Paperless-ID | `/paperless/{paperless_id}` |
| Dokumente (`history_rows.html`) | `data-panel-url="/fragment/documents/{id}"`, `data-page-url="/documents/{id}"` | `/documents/{id}` |

Die geöffnete Zeile trägt `aria-current="true"`. Bei Rechnungen fehlen die Attribute und der Titel
führt auf `/invoices/{invoice_id}`, wenn die Anbindung fehlt (`panel_enabled` false). Die Dokumente-Liste
hat die Attribute immer.

### Breitenstufen

Stufen aus `app/static/app.css` (Abschnitt „Seitenleiste neben den Listen“):

- **Ab 1280px, nebeneinander.** `main.container.has-panel` wird Grid mit
  `minmax(0, 1fr) minmax(28rem, 42%)`. Der Container wird 1680px breit. Die Leiste steht rechts,
  `position: sticky`, Höhe `calc(100dvh - 5.5rem)`, und scrollt in sich. Spalten mit der Klasse
  `col-secondary` werden ausgeblendet.
- **720 bis 1279px, Überlagerung.** Die Leiste liegt `position: fixed` rechts, Breite
  `min(36rem, 90vw)`, mit Schatten über der Liste. Die Liste bleibt darunter vollständig. Das
  Einblenden dauert 0,18 s und entfällt bei `prefers-reduced-motion`.
- **Unter 720px, Vollbild.** `inset: 0`. Der Schließen-Knopf und der Link „Als Seite öffnen“ haben
  mindestens 44px Trefferfläche.

Die Vorschau in der Leiste misst `clamp(18rem, 60dvh, 48rem)`. Auf der vollen Seite gelten weiter
70vh.

### Öffnen, Wechseln, Schließen (`app/static/app.js`)

- **Klick:** Ein Klick auf die Zeile oder den Titel-Link öffnet die Leiste. Strg, Cmd, Shift, Alt
  und Mittelklick behalten das normale Verhalten, also etwa einen neuen Tab. Bedienelemente in der
  Zeile (Eingabefelder, Knöpfe, Links außer dem Titel) bleiben unberührt.
- **Laden:** `loadFragment` mit `AbortController`. Beim schnellen Wechseln bricht der vorige
  Ladevorgang ab. Antworten, die nicht mehr zum Zustand passen, verwirft `panelSeq`.
- **Adresse:** `history.pushState` setzt `?doc=<schlüssel>`. Der Schlüssel ist die letzte Zahl der
  Fragment-URL. Andere Parameter der Liste (Filter, Sortierung, Seite) bleiben erhalten.
- **Zurück-Taste:** `popstate` stellt den Zustand aus `?doc=` her. Ohne `?doc=` schließt die Leiste.
- **Schließen:** „Schließen ✕“ und Esc entfernen `?doc` per `pushState`. Der Fokus geht auf den
  Titel-Link der zuletzt geöffneten Zeile.
- **Fokus:** Nach dem Laden springt der Fokus auf die Überschrift `#panel-title`.
- **Fehler:** Scheitert der Abruf, erscheint in der Leiste der Hinweis „Die Ansicht konnte nicht
  geladen werden.“ (`role="alert"`).

Beim Seitenaufruf mit `?doc=` rendert der Server die Leiste gleich mit und markiert die Zeile. JS
übernimmt dann den Zustand, ohne die Leiste neu zu laden.

## Tastatur

Die Tasten wirken nur bei offener Leiste (`keydown` auf dem Dokument):

| Taste | Wirkung |
|---|---|
| `↑` bzw. `k` | vorheriger Eintrag der Liste |
| `↓` bzw. `j` | nächster Eintrag der Liste |
| `Esc` | Leiste schließen, Fokus auf die zuletzt geöffnete Zeile |
| `Enter` | volle Seite öffnen (`data-page-url` der aktuellen Zeile) |

Ignoriert werden Ereignisse mit Strg, Cmd, Alt oder Shift. Ignoriert werden auch Ziele innerhalb von
`input`, `select`, `textarea`, `[contenteditable]`, `object` und `.doc-preview`. Auf Knöpfen, Links
und `summary` behält `Enter` seine eigene Aufgabe. Am Listenende passiert nichts, die Liste wird
nicht weitergeblättert.

## Aktionen in der Seitenleiste

Formulare mit `data-panel-form` (Empfänger setzen, KI-Vorschlag, Zahldaten, Export, Verwerfen,
Abgleichsentscheidung, „überwiesen“) laufen per `fetch`:

- **Senden:** Die Formdaten gehen als `URLSearchParams` mit den Kopfen `X-Requested-With: fetch` und
  `X-Lector-Panel: 1`. Der gedrückte Knopf wird mitgeschickt. Während des Sendens sind die Knöpfe
  gesperrt, ein Doppelklick sendet nur einmal (`data-sending`).
- **Antwort:** `fetch` folgt dem 303 auf das Fragment. Die Leiste ersetzt ihren Inhalt, sofern noch
  dasselbe Dokument offen ist. Liegt die Antwort bei `?ask=1`, bleibt die Rückfrage in der Leiste.
- **Liste:** Danach lädt `refreshFragment(true)` nur die Liste neu. Die Leiste wird dabei nicht
  erneut geladen. Der bestehende Zeilen-Diff zeigt die geänderte Zeile.
- **Fehler:** Scheitert die Aktion, erscheint oben in der Leiste „Die Aktion konnte nicht
  ausgeführt werden. Bitte erneut versuchen.“ Der bisherige Inhalt bleibt stehen.
- **401:** Abgelaufene Anmeldung führt zur Anmeldung.

## Live-Updates (SSE)

Die Seitenleiste ist in den SSE-Refresh eingebunden (siehe [web-ui-sse.md](../web-ui-sse.md)):

- `refreshFragment` lädt die Tabelle, die offene Leiste (`#panel[data-fragment]`) und, falls
  vorhanden, `#detail` neu.
- Die Leiste wird nicht überschrieben, solange der Nutzer in ihr etwas eingibt
  (`panelDirty`) oder ein Formular sendet (`panelSendet`).
- Auf der Seite `/paperless/{id}` filtert `passtZurDetailseite` die Ereignisse: Vorgangs-Ereignisse
  (`doc:`) betreffen die Paperless-Ansicht nicht. Alle anderen Ereignisse (Rechnung `inv:`,
  Belegabruf, Batch) laden neu.

## Vorschau-Proxy und Sicherheit

Die Vorschau läuft über Lector, damit der Browser keine Verbindung zu Paperless braucht. Lector
holt sie mit dem Token von Paperless (`PaperlessClient.download_preview`) und liefert sie selbst aus.
Der Token bleibt auf dem Server.

- **Typen:** Ausgeliefert werden nur `application/pdf` und `image/png`, `image/jpeg`, `image/gif`,
  `image/webp`, `image/tiff` (`_PREVIEW_TYPE_RE`). Jeder andere Typ führt zu 415 mit „Vorschau nicht
  verfügbar“, der Inhalt geht nicht hinaus.
- **Fehler:** Scheitert der Abruf, antwortet Lector mit 502. Liefert Paperless 403 oder 404, antwortet
  Lector mit 404.
- **Header:** `X-Frame-Options: SAMEORIGIN` und
  `Content-Security-Policy: default-src 'self'; script-src 'none'; frame-ancestors 'self'`.
  `Cache-Control: private, max-age=300` lässt das Hin- und Herblättern in der Leiste ohne erneuten
  Abruf laufen.
- **Keine Freigabe pro Dokument:** Der Proxy prüft nicht, ob Lector das Dokument kennt. Die ID
  ist ein `int` im Pfad (`{paperless_id:int}`), damit kein Pfad in die Paperless-API eingeschleust
  werden kann. Die Ansicht zeigt damit jedes Dokument, das Lectors Token lesen darf (siehe
  [PRODUCT.md](../../PRODUCT.md)):
  - `AUTH_MODE=paperless`: alle angemeldeten Nutzer sehen diese Dokumente.
  - `AUTH_MODE=none`: wer die Oberfläche erreicht.
- **Zugangsschutz:** `AuthMiddleware` (`app/auth.py`) schützt die neuen Routen wie die übrigen.
  Offen sind nur `/healthz`, `/login`, `/api/info`, `/api/v1/login` und `/static/`.
- **Herkunftsprüfung:** Sie gilt für POST nur bei `AUTH_MODE=paperless`. Der Kopf
  `X-Lector-Panel` umgeht sie nicht.
- **Keine Speicherung:** Lector legt Paperless-Metadaten nicht in SQLite ab. Jedes Öffnen liest sie
  frisch. Pro Öffnen gibt es einen Dokumentabruf und einen Notizenabruf bei Paperless, parallel. Die
  Vorschau kommt separat dazu, und die Namenslisten sind gecacht.

Fällt Paperless aus, läuft die Ausnahme (`httpx.HTTPError`) bis zum Handler `paperless_unavailable`
in `app/main.py`. Dort erscheint in einem Fragment der Hinweis, dass Paperless nicht erreichbar ist.

## Tests

- `tests/test_paperless_view.py`: Namensabbildung im Client, Notizen mit und ohne Verfasser, Dokument
  ohne ASN. Namens-Cache (Lebensdauer, einmaliges Neuladen bei unbekannter ID, `_corr_map_cached`).
  `view_enabled`, `load_document_view` mit allen Angaben, ohne Korrespondent und ASN, mit unbekanntem
  Tag, bei unbekannter ID (`None`) und bei Paperless-Fehler. `fetch_document_preview` und Select-Labels.
- `tests/test_paperless_view_web.py`: Vorschau-Proxy (Header, 415, ganzzahlige ID),
  `/invoices/{id}/preview`, Seite und Fragment, Rechnungsbereich nur bei Rechnung und
  `FEATURE_PAPERLESS_SYNC`, 404-Fälle, Hinweis bei nicht erreichbarem Paperless, `ask` durchgereicht,
  alte Rechnungsadresse, Redirect-Ziele mit und ohne Kopf, Herkunftsprüfung im Modus `paperless`,
  Listen mit `?doc=` und die Dokumente-Liste.
- `tests/test_app_js_panel.py`: Seitenleiste in `app/static/app.js` gegen einen kleinen DOM-Ersatz in
  Node. Klick, schneller Wechsel, `popstate`, Tastatur, Formulare, SSE.
- `tests/test_app_js.py`, `tests/test_web.py`, `tests/test_web_auth.py`: an die neuen Adressen
  angepasst und ergänzt.

Was nur ein Browser zeigt (Layout, Fokusring, PDF-Darstellung, Kontrast), wurde am 02.11.2026 auf
dem NAS manuell abgenommen (Task 6.4 in
`openspec/changes/archive/2026-11-02-paperless-dokumentansicht/tasks.md`).

## Offen

- Manuelle Prüfung im Browser (Tasks 4.1 bis 4.4 und 5.1) und Abnahme auf dem NAS (Task 6.4) stehen
  aus.
- Nicht Teil dieses Changes: Bearbeiten von Paperless-Metadaten (Titel, Korrespondent, Tags,
  Dokumenttyp, sonstige Custom Fields) und Volltextsuche über Paperless.
- Umgesetzt im Folge-Change `scan-paperless-verknuepfung`: Verknüpfung von Scans mit Paperless über
  die Prüfsumme und die Vorschau des lokalen Originals. Siehe [scan-verknuepfung.md](scan-verknuepfung.md).
- Die Leiste blättert am Listenende nicht auf die nächste Seite weiter.
- Der Design-Entwurf sah für die Vorschau in der Leiste `flex: 1` vor. Umgesetzt ist
  `clamp(18rem, 60dvh, 48rem)`, so wie es in [DESIGN.md](../../DESIGN.md) beschrieben ist.
