# Scan-Verknüpfung: Lector-Vorgang ↔ Paperless-Dokument

**Module:** `app/paperless_link.py` (Verknüpfungsjob `PaperlessLinker`), `app/paperless.py`
(`find_documents`, `TooManyHitsError`), `app/pipeline.py` (`mark_consumed`, `_mark_link_pending`),
`app/recovery.py`, `app/decisions.py` (`original_path`), `app/repository.py` (Spalten, Abfragen),
`app/worker.py` (Task `paperless-link`), `app/config.py` (`PAPERLESS_LINK_INTERVAL_SECONDS`),
`app/main.py` (`_document_context`, `_locate_original_sync`, `/documents/{id}/original`,
Filter `paperless=missing`), Templates `partials/document_panel.html`,
`partials/document_original.html`, `partials/paperless_badge.html`, `partials/back_field.html`,
`partials/history_rows.html`, `dashboard.html`.

Change: `openspec/changes/scan-paperless-verknuepfung/` (Spec, Design, Aufgaben). Der Change ist
noch nicht archiviert; die Abnahme auf dem NAS (Aufgabe 6.3) steht aus, siehe
[Grenzen und Offenes](#grenzen-und-offenes).

## Zweck

Nach dem Scannen soll man in Lector sehen, ob ein Dokument in Paperless angekommen ist, und es
dort ansehen können, ohne Paperless zu suchen. Bei einem fehlgeschlagenen Vorgang zeigt Lector
außerdem das lokale Original.

Dafür wird jeder abgelegte Vorgang über die SHA-256-Prüfsumme der abgelegten Datei mit dem
Paperless-Dokument verbunden. Paperless speichert diese Prüfsumme als `checksum`. Laut
`openspec/changes/scan-paperless-verknuepfung/design.md` (Abschnitt „Context“) ist das an einem echten
Dokument geprüft; die Gleichheit bei einem frisch abgelegten Scan belegt erst Aufgabe 6.3. Für den Altbestand ohne gespeicherte Prüfsumme gibt es eine gekennzeichnete Ausnahme über
den Dateinamen und ein enges Zeitfenster.

Entscheidungen im Code:

- Die Verknüpfung ist ein eigener Job und keine Erweiterung von `paperless-sync`. Der läuft nur mit
  `FEATURE_PAPERLESS_SYNC`, die Verknüpfung aber auch ohne das Rechnungsfeature (`app/worker.py`).
- Der Verarbeitungsstatus und der Ablauf der Pipeline bleiben unverändert. Die Verknüpfung hat
  eigene Spalten.
- Der Job sucht nur. Er ändert keine Dokumente in Paperless.

## Datenmodell

### Neue Spalten an `documents`

Die Spalten kommen über `_MIGRATIONS` in `app/db.py` in bestehende Datenbanken. Der Index
`idx_documents_paperless_link` steht in `_POST_MIGRATION_INDEXES`.

| Spalte | Inhalt | Gesetzt von |
|---|---|---|
| `output_hash` | SHA-256 der in `consume` abgelegten Datei | `Repository.mark_consumed` (Pipeline) |
| `original_path` | aktueller Pfad des Originals in `processed` oder `error` | `move_into`-Rückgabe in `pipeline.py`, `recovery.py`, `decisions.py`; lazy in `main._locate_original_sync` |
| `consumed_at` | Zeitpunkt der Ablage (UTC, Format `YYYY-MM-DD HH:MM:SS`) | `mark_consumed` (`datetime('now')`); beim Altbestand im Job nachgetragen |
| `paperless_id` | ID des Paperless-Dokuments | Job (`set_paperless_link`); bleibt bei `missing` erhalten |
| `paperless_link` | Zustand der Verknüpfung (siehe unten) | Pipeline, Job, Ansicht, Recovery/Entscheidungen |
| `paperless_checked_at` | Zeitpunkt der letzten Suche (UTC) | `set_paperless_link`, `touch_paperless_checked` |

`output_hash` und `consumed_at` sind beim Altbestand leer. Ältere Vorgänge bekommen den Zeitpunkt
aus dem Ereignis `moved_to_consume`, sonst aus `finished_at`, sonst aus `created_at`
(`PaperlessLinker._consumed_at`). Der so ermittelte Wert wird gespeichert.

### Zustände (`PaperlessLink` in `app/models.py`)

| Wert | Anzeige | Bedeutung |
|---|---|---|
| `NULL` | „—“ | Kein Ergebnis: laufend, fehlgeschlagen, verworfen, keine Paperless-Anbindung oder noch nicht betrachtet. Die Liste zeigt „—“, der Filter „Nicht in Paperless“ nimmt `NULL` nicht auf. |
| `pending` | „wartet“ | Die Ablage ist erfolgt, das Paperless-Dokument ist noch nicht gefunden (innerhalb von 24 Stunden). |
| `linked` | „#ID“ | Über die Prüfsumme verknüpft. |
| `linked_by_name` | „#ID · über Namen“ | Altbestand, über den ursprünglichen Dateinamen verknüpft. Die Liste trägt den Zusatz „über Namen“ (Titel „Über den Dateinamen verknüpft“), die Leiste den Hinweis „über Dateinamen“. |
| `not_found` | „nicht gefunden“ | 24 Stunden nach der Ablage kein Treffer, bzw. die Namenssuche fand keinen eindeutigen Treffer. Der Verarbeitungszustand bleibt `done`. |
| `missing` | „nicht mehr vorhanden“ | Das verknüpfte Dokument ist in Paperless nicht mehr abrufbar. Wird nur beim Öffnen der Ansicht gesetzt (siehe unten). |

Die Zuordnung der Zustände zu Vorgängen (`pending` nur bei Anbindung):

- `mark_consumed` setzt den Zustand in beiden Ablagepfaden zunächst auf `NULL`. Danach setzt
  `_mark_link_pending` (`app/pipeline.py`) `pending`, aber erst, nachdem das Original verschoben
  wurde, und nur wenn `link_configured(settings)` wahr ist. Der Kommentar im Code begründet das so:
  Scheitert der Rest, endet der Vorgang nicht mit einer Verknüpfung, die nie zustande kommt.
- Endgültig fehlgeschlagene Vorgänge setzen den Zustand auf `NULL` (`_handle_failure` in
  `app/pipeline.py`, sowie die Fehlerpfade in `app/recovery.py`). Sie werden nie gesucht.
- Ohne Anbindung bleibt der Zustand `NULL`. Wird die Anbindung später eingerichtet, erfasst der
  Nachhol-Lauf diese Vorgänge über `paperless_link IS NULL`.

### Ereignis

`EventType.PAPERLESS_LINKED` (`paperless_linked`) hält jede Verknüpfung im Verlauf fest, mit der
Herkunft in der Meldung, z. B. `Mit Paperless-Dokument #1234 verknüpft (über die Prüfsumme)` bzw.
`… (über den Dateinamen)`. Der Zustand `not_found` erzeugt kein Ereignis.

## Ablage: Prüfsumme und Zeitpunkte

Die Ablage in `consume` schreibt die Prüfsumme der **abgelegten** Datei, nicht die des Eingangs.

- **E-Rechnung** (`_handle_erechnung`): `output_hash = file_hash`. Die Datei wird byte-identisch
  kopiert, deshalb genügt die vorhandene Prüfsumme und es gibt kein zweites Lesen. Fehlt `file_hash`,
  berechnet Lector die Prüfsumme aus der abgelegten Datei.
- **OCR-Weg** (`_handle_ocr`): `output_hash` wird aus dem fertigen Sandwich-PDF berechnet, bevor es
  mit `move_into` nach `consume` verschoben wird. Verschieben und `chown` ändern die Bytes nicht.
- Beide Wege rufen danach `mark_consumed` auf: Pfad in `consume`, `output_hash`, `consumed_at` und
  Zustand `NULL`. Danach wird das Original nach `processed` verschoben, `original_path` gesetzt, und
  erst dann `pending` gesetzt.
- Der Abschluss durch die Recovery (`_finish` in `app/recovery.py`) setzt `original_path`, aber
  weder `output_hash` noch den Zustand. Ein so abgeschlossener Vorgang hat `NULL` und wird vom
  Nachhol-Lauf erfasst, sofern `output_hash` gesetzt ist.

**Bekannte Grenze:** Ein Wiederholversuch nach der Ablage legt eine weitere Datei in `consume` ab
(Kommentar in `_handle_ocr`). `output_hash` gilt immer für die **zuletzt** abgelegte Datei.

## Der Verknüpfungsjob

### Start und Takt

- `app/main.py` erzeugt den `PaperlessLinker` im Lifespan und reicht ihn an den `Worker`.
- Der Task `paperless-link` startet nur, wenn `link_configured` wahr ist, also `PAPERLESS_URL` und
  `PAPERLESS_TOKEN` gesetzt sind (`app/worker.py`). Ohne Anbindung läuft kein Job.
- Der erste Lauf beginnt sofort nach dem Start, danach im Takt `PAPERLESS_LINK_INTERVAL_SECONDS`
  (Standard `300.0`).
- Ist beim Lauf ein voller Nachhol-Stapel übrig (siehe unten), beginnt der nächste Lauf nach
  `BACKLOG_SLEEP_SECONDS` (5 Sekunden) statt nach dem vollen Takt.

### Ablauf eines Laufs (`PaperlessLinker.run_once`)

1. Offene Vorgänge: bis zu 50 Vorgänge mit Status `done` oder `skipped_erechnung` und Zustand
   `pending` (`Repository.list_paperless_pending`). Die am längsten ungeprüften kommen zuerst.
2. Nachholen: bis zu 50 Vorgänge aus `Repository.list_paperless_catchup`. Das sind abgeschlossene
   Vorgänge mit Zustand `NULL`, plus `not_found`-Vorgänge, die erneut gesucht werden müssen (siehe
   „Täglicher Nachlauf“).
3. Jeder Vorgang wird in `_resolve` behandelt. Zuerst wird `consumed_at` bestimmt (und bei Bedarf
   gespeichert), dann geht es über die Prüfsumme oder über den Dateinamen weiter.

Der Client läuft mit einer einzigen `async with`-Verbindung je Lauf (`_client_factory`).

### Suche über die Prüfsumme (`_resolve_by_checksum`)

Die Prüfsumme ist `output_hash`, bei E-Rechnungen ohne `output_hash` der `file_hash`
(`PaperlessLinker._checksum`). Die Suche ist `GET /api/documents/?checksum__iexact=<hash>` über
`PaperlessClient.find_documents` (`app/paperless.py`), mit `fields=id,original_file_name,added` und
`page_size` 6.

| Ergebnis | Wirkung |
|---|---|
| genau 1 Treffer | `linked`, Ereignis `paperless_linked`. Dublette: Paperless zeigt das bereits vorhandene Dokument mit derselben Prüfsumme. |
| 2 bis 5 Treffer | Keine Verknüpfung, kein `not_found`. Der Zustand bleibt wie er war (`pending` oder `NULL`); der Vorgang wird im nächsten Lauf erneut gesucht (siehe Grenzen). |
| mehr als 5 Treffer | `TooManyHitsError`: Der Filter gilt als nicht unterstützt. Der Lauf bricht ab, ohne Zustand zu ändern. |
| 0 Treffer, Ablage jünger als 24 Stunden | `pending` bleibt bzw. wird gesetzt. |
| 0 Treffer, Ablage älter als 24 Stunden | `not_found`. Der Verarbeitungszustand bleibt unverändert. |

### Nachholen des Altbestands

Der Nachhol-Lauf nimmt Vorgänge ohne Verknüpfung auf, die vor dem Change abgeschlossen wurden.

- **E-Rechnungen** ohne Zustand: über `file_hash` (Bytes identisch), wie oben.
- **OCR-Vorgänge ohne `output_hash`** (`_resolve_by_name`): Die Suche nutzt den Dateinamen aus
  `output_path` über `original_file_name__iexact` und das Zeitfenster
  `added__gte` = `consumed_at`, `added__lte` = `consumed_at + 24 h` (ISO-Format mit `Z`, UTC).
  - Mehr als 5 Treffer: mehrdeutig, Ergebnis `not_found`. Ein häufiger Name wie `scan.pdf` blockiert
    den Lauf also nicht.
  - Die Treffer werden lokal gegengeprüft: Dateiname ohne Groß-/Kleinschreibung, `added` im Fenster.
    Paperless ignoriert unbekannte Filter lautlos (laut Befund 1.1), deshalb ist diese Prüfung nötig.
  - Treffer, deren Paperless-ID schon einem anderen Vorgang mit `linked` oder `linked_by_name`
    gehört, werden verworfen (`paperless_id_taken`).
  - Genau ein verbleibender Treffer: `linked_by_name`, Ereignis `paperless_linked`. Sonst
    `not_found`.
- Vorgänge ohne Dateinamen (`output_path` leer) und ohne Prüfsumme werden direkt `not_found`.
- Fehlgeschlagene Vorgänge werden nie gesucht. Die Abfrage nimmt nur `done` und `skipped_erechnung`.

### Täglicher Nachlauf und Wiederholung von `not_found`

`list_paperless_catchup` nimmt `not_found`-Vorgänge in den Lauf auf, unter diesen Bedingungen:

- **Nach dem Start einmal:** Alle `not_found`-Vorgänge, deren letzte Suche vor dem Start des
  Prozesses lag (`recheck_before`). Das betrifft auch Namens-Vorgänge und Vorgänge jeder Altersstufe.
- **Täglich, 14 Tage lang:** `not_found`-Vorgänge **mit Prüfsumme** (`output_hash`, bei E-Rechnungen
  `file_hash`), deren letzte Suche mehr als 24 Stunden zurückliegt und deren Ablage nicht älter als
  14 Tage ist. Das fängt einen längeren Paperless-Ausfall ab.
- Namens-`not_found` wird nach dem Start nur einmal gesucht, nicht täglich.

Ein späterer Treffer hebt `not_found` auf: Der Zustand wird `linked` oder `linked_by_name`.

### Stapel, Fristen, Konstanten

Diese Werte sind Konstanten im Code. Sie sind keine Umgebungsvariablen.

| Konstante | Wert | Wirkung |
|---|---|---|
| `BATCH_SIZE` | 50 | Stapelgröße je Liste (offene Vorgänge und Nachholen getrennt) |
| `NOT_FOUND_AFTER` | 24 Stunden | Frist ab Ablage bis `not_found`; zugleich Breite des Namens-Zeitfensters |
| `DAILY_RECHECK_INTERVAL` | 24 Stunden | Abstand der täglichen Wiederholung |
| `DAILY_RECHECK_MAX_AGE` | 14 Tage | Ablagen, die älter sind, werden nicht mehr täglich gesucht |
| `BACKLOG_SLEEP_SECONDS` | 5,0 | Pause, wenn ein voller Nachhol-Stapel ansteht |
| `FIND_MAX_HITS` (`app/paperless.py`) | 5 | Obergrenze für Treffer, darüber gilt der Filter als nicht unterstützt |

Die Prüfsummen-Suche verursacht höchstens 50 Anfragen je Lauf für offene Vorgänge plus 50 für das
Nachholen (je ein Aufruf pro Vorgang).

### Schutzregeln

- **Ignorierte Filter:** Paperless liefert bei unbekanntem Filter den ganzen Bestand (laut
  design.md, Befund 1.1). Mehr als 5 Treffer bei der Prüfsumme brechen den Lauf deshalb ab, statt
  einen falschen Treffer zu übernehmen. Bei der Namenssuche wird jeder Treffer lokal gegengeprüft
  (Name, `added` im Fenster).
- **Mehrdeutige Namen:** Mehr als 5 Namenstreffer oder mehrere passende Treffer im Fenster ergeben
  `not_found`. Der Vorgang wird nicht verknüpft.
- **Doppelbelegung:** Ein Namenstreffer, dessen ID schon einem anderen verknüpften Vorgang gehört,
  zählt nicht mit (siehe „Bewusst so entschieden“ unter Grenzen).
- **Namensfall:** Die Prüfung vergleicht Namen ohne Beachtung der Groß-/Kleinschreibung.
- **`missing` wird im Job nicht gesetzt.** Der Job prüft verknüpfte Vorgänge nicht erneut, um
  Paperless nicht mit Bestandsabfragen zu belasten. Das passiert beim Öffnen der Ansicht.

### Fehlerverhalten

- **Netzfehler, Timeouts und jede HTTP-Fehlerantwort** (z. B. 5xx oder ein ungültiger Token):
  `httpx.HTTPError` bzw. `PaperlessError` brechen den Lauf ab (`result.aborted`). Der Zustand des gerade
  geprüften Vorgangs bleibt unverändert, die restlichen Vorgänge bleiben wie sie waren. Der nächste
  Lauf nach dem vollen Takt versucht es erneut.
- **Zu viele Treffer bei der Prüfsumme:** Ebenfalls Abbruch des Laufs, ohne Zustandsänderung.
- **Unerwartete Ausnahme:** `_paperless_link_loop` im Worker protokolliert sie und läuft weiter.
- Die Protokollmeldung lautet `Paperless-Verknüpfung abgebrochen: …` (Logger
  `lector.paperless_link`).

## Health

`GET /healthz` (`app/main.py`, `_health_status`) zählt acht Prüfungen: die vier immer gestarteten
Hintergrundarbeiten, `paperless-sync`, `paperless-link`, den Watchdog-Observer und die Datenbank.
Für `paperless-link` gilt (`Worker._paperless_link_task_status`):

| Zustand | Bedeutung |
|---|---|
| `not_started` | Keine Anbindung (URL oder Token fehlt). Gilt als gesund. |
| `running` | Der Task läuft. |
| `stopped` mit Fehler | Der Task ist beendet. Wer ihn nie gestartet hat, obwohl die Anbindung besteht, sieht „Task wurde nie gestartet“. |

Die Prüfung ist rein lesend. Sie fragt Paperless nicht ab.

## Original-Auslieferung

Die Route `GET /documents/{document_id:int}/original` (`app/main.py`) liefert das lokale Original eines
Vorgangs aus. Sie liegt hinter derselben Zugangsprüfung wie die übrigen Routen.

### Welche Datei

- Quelle ist ausschließlich die Datenbank: `original_path`. Der Pfad kommt nie aus der Anfrage.
- Ist `original_path` leer und hat der Vorgang den Status `done`, `skipped_erechnung` oder `failed`,
  sucht `_locate_original_sync` einmal lazy: zuerst in `processed`, dann in `error`, über
  `_find_in_processed` (Name mit optionalem `_n`-Zusatz plus `file_hash`-Bestätigung, siehe
  `app/recovery.py`). Ein gefundener Pfad wird gespeichert.
- Vorgänge in anderen Zuständen zeigen kein Original. Das gilt besonders für Vorgänge im Eingang
  (`blocked`, `pending`, `processing`).

### Schutz gegen Pfadangriffe

- Der Pfad wird mit `Path.resolve()` aufgelöst. Er muss unter dem aufgelösten `processed_dir` oder
  `error_dir` liegen (`_inside_original_roots`). Sonst liefert die Route nichts aus.
- Symbolische Links, die aus dem Ordner hinausführen, werden so abgelehnt (`resolved` liegt außerhalb).
- Aus `consume` wird nie ausgeliefert.
- Die Datei muss existieren und eine Datei sein (`is_file()`).

### Auslieferung

| Endung | Antwort |
|---|---|
| `.pdf`, `.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`, `.tif`, `.tiff` | Vorschau über `_preview_response`, wie die Paperless-Vorschau. Der Typ kommt aus der Endung, nie aus dem Dateiinhalt. `X-Frame-Options: SAMEORIGIN`, `Content-Security-Policy: default-src 'self'; script-src 'none'; frame-ancestors 'self'`, `Cache-Control: private, max-age=300`. |
| `.xml` | Download, `application/xml`. |
| andere Endungen | Download, `application/octet-stream`. |

Downloads kommen mit `Content-Disposition: attachment` (ASCII-Rückfallname und RFC-5987-Name
in UTF-8), `X-Content-Type-Options: nosniff` und `Cache-Control: private, no-store`.

Fehlerfälle:

- Unbekannte Vorgangs-ID: 404 mit „Dokument nicht gefunden“.
- Kein auslieferbares Original (fehlt, außerhalb der Ordner, nicht lesbar): 404 mit „Original nicht
  vorhanden“.

Die Vorgangsansicht fängt das über `document_original.html` ab. Dort steht dann „Original nicht mehr
vorhanden.“, nicht eine Fehlerseite.

## Leiste: Vorgang und Dokument zusammen

### Aufbau

`partials/document_panel.html` ist der gemeinsame Baustein für die Seite `/documents/{id}`
(`detail.html`), das Fragment `/fragment/documents/{id}` und die Seitenleiste der Dokumente-Liste
(`partials/panel_aside.html`). Der Baustein enthält genau eine `panel_bar` und genau eine
`h1#panel-title`. `app.js` verlässt sich darauf.

Von oben nach unten:

1. **Kopf:** Dateiname als `h1#panel-title`, Status-Badge, bei aktiver Paperless-Ansicht der
   Paperless-Bezug. Bei `linked` und `linked_by_name` ein interner Link „in Paperless #ID“ auf
   `/paperless/{id}`, bei `linked_by_name` zusätzlich „über Dateinamen“. Bei den übrigen Zuständen
   steht die ID gedämpft dabei.
2. **Hinweise:** `failed` (Versuche ausgeschöpft, verworfen oder sonstige Ursache), `blocked` mit den
   Formularen „Freigeben und verarbeiten“ und „Verwerfen“, Fortschritt bei `processing`.
3. **Verlauf** als `<details class="doc-log">`. Offen bei `failed`, `processing`, `pending` und
   `blocked`, sonst eingeklappt. Enthält die Stammdaten des Vorgangs und den Verlauf der Ereignisse.
4. **Darunter** je nach `link_state` (siehe unten).

### `link_state`

`_document_context` setzt den Zustand. Die Werte:

| `link_state` | Bedingung | Anzeige |
|---|---|---|
| `embedded` | Verknüpft (`linked` oder `linked_by_name`), Paperless-Ansicht lädt | `partials/paperless_doc_body.html` mit `embedded=true`: Titel als `h2`, ohne eigene Leiste |
| `missing` | `paperless_link = missing`, oder beim Öffnen 404/403 von Paperless | Hinweis „In Paperless nicht mehr vorhanden (#ID).“ und darunter das lokale Original |
| `unreachable` | Paperless antwortet nicht (`httpx.HTTPError`) | Hinweis, dass der Vorgang vollständig bleibt; darunter das lokale Original |
| `original` | Alles andere (ohne Verknüpfung, auch `pending` und `not_found`) | Lokales Original |

Beim Öffnen einer verknüpften Ansicht, die Paperless nicht mehr kennt, setzt `_document_context`
den Zustand auf `missing` und speichert ihn (`set_paperless_link`). Das ist die einzige Stelle,
die `missing` setzt. Die ID bleibt erhalten.

Das lokale Original zeigt `document_original.html` mit einem der Zustände `preview` (PDF oder Bild in
einem `<object>`, mit Link als Rückfall), `download` (Link; bei `erechnung_xml` „XML-E-Rechnung
herunterladen“), `gone` (Hinweis „Original nicht mehr vorhanden.“) oder `none` (nichts anzeigen, bei
Vorgängen, die noch nicht abgeschlossen sind).

### Rückweg `back=doc:<id>`

Die Paperless-Dokumentansicht innerhalb der Leiste hat Formulare (Empfänger, KI-Vorschlag,
Rechnungsaktionen). Sie senden ein verstecktes Feld `back=doc:<Lector-ID>`
(`partials/back_field.html`). Das Feld wird nur gesetzt, wenn `back_doc` im Kontext steht, also im
eingebetteten Zustand.

- Die Redirect-Helfer `_recipient_redirect` und `_invoice_redirect` (`app/main.py`) lesen das Feld
  über `_back_doc_id`. Nur `doc:` gefolgt von höchstens 18 Ziffern wird akzeptiert.
- Mit Kopf `X-Lector-Panel: 1` geht die Antwort auf `/fragment/documents/<id>`, sonst auf
  `/documents/<id>`. Bei Rechnungsaktionen bleibt eine Rückfrage (`?ask=1`) erhalten.
- Ungültige Werte werden ignoriert. Das Ziel entsteht allein aus der Zahl.

### Live-Aktualisierung

Die Vorgangsansicht reagiert auf `doc:`-Ereignisse mit gleicher ID (siehe
[web-ui-sse.md](../web-ui-sse.md)). `set_paperless_link` sendet über `Repository._notify` ein
`doc:<id>`-Ereignis; `touch_paperless_checked` (Fortschritt ohne Zustandsänderung) sendet keines. Eine
geöffnete Leiste lädt daraufhin ihr Fragment neu.

## Liste und Filter

Die Dokumente-Liste (`dashboard.html`, `partials/history_rows.html`) hat eine Spalte „Paperless“
(`col-secondary`, Klasse `col-paperless`) und einen Schnellfilter „Nicht in Paperless“. Beides gibt es
nur bei konfigurierter Anbindung (`view_enabled`: URL und Token). Ohne Anbindung entfallen Spalte und
Chip.

- **Spalte:** Das Makro `link_badge` aus `partials/paperless_badge.html` zeigt je Zustand einen Badge.
  `NULL` ist „—“. `linked` zeigt „#ID“, `linked_by_name` „#ID · über Namen“ mit Titel-Attribut,
  alle anderen den Zustandsnamen. Bei `missing` steht nur „nicht mehr vorhanden“, ohne ID.
- **Aufleuchten:** `data-rev` der Zeile enthält Zustand und ID (`doc.paperless_link`,
  `doc.paperless_id`), damit der Zeilen-Abgleich eine Änderung zeigt (siehe
  [ui-erscheinungsbild.md](../ui-erscheinungsbild.md)).
- **Filter** `?paperless=missing`: `Repository.list_documents(paperless_missing=True)` liefert
  Vorgänge mit Status `done` oder `skipped_erechnung` und Zustand `pending`, `not_found` oder
  `missing`. Vorgänge mit `linked`, `linked_by_name` und `NULL` (noch nicht betrachtet, laufend,
  fehlgeschlagen) fallen heraus. Der Filter greift auch im Fragment `/fragment/history` (Parameter
  `paperless` im `data-fragment` der Tabelle).
- Ohne Anbindung ist der Parameter wirkungslos (`not_in_paperless = view_enabled and paperless == "missing"`).

Der Leerzustand unterscheidet „Keine Dokumente für diese Filter“ und „Noch nichts eingegangen“. Mit
aktivem Chip „Nicht in Paperless“ gilt eine leere Liste als gefiltert (`filtered` in `dashboard`).

## Konfiguration

| ENV | Default | Bedeutung |
|---|---|---|
| `PAPERLESS_URL` | leer | Adresse der Paperless-Instanz. Zusammen mit dem Token Voraussetzung für Job, Spalte und Filter. |
| `PAPERLESS_TOKEN` | leer | Zugangsschlüssel für Paperless. Zusammen mit der Adresse Voraussetzung für Job, Spalte und Filter. |
| `PAPERLESS_LINK_INTERVAL_SECONDS` | `300.0` | Takt des Verknüpfungsjobs in Sekunden. Muss größer als 0 sein, sonst Startfehler (`validate_settings`, unabhängig von den Feature-Schaltern). |

Die Tabelle steht in [../konfiguration.md](../konfiguration.md#paperless-verknüpfung). Der Standardwert
steht in `.env.example`.

Für die Freischaltung gilt dasselbe wie für die Dokumentansicht (siehe
[dokumentansicht.md](dokumentansicht.md#freischaltung)). Ohne Anbindung läuft kein Job, keine Spalte
und kein Filter sind sichtbar, und die Vorgangsansicht zeigt das lokale Original.

## Tests

- `tests/test_paperless_link.py`: Filter und Felder von `find_documents` (Query-Parameter per
  `httpx.MockTransport`), Treffer, Dublette, Frist vor und nach 24 Stunden, Netzfehler ohne
  Zustandsänderung, nicht unterstützter Filter, mehrere Prüfsummen-Treffer, fehlgeschlagene
  Vorgänge werden nie gesucht, E-Rechnung über `file_hash`, Altbestand (eindeutiger und mehrdeutiger
  Name, Zeitfenster), Wiederholung von `not_found`, Stapelgrenze, Validierung des Takts.
- `tests/test_scan_verknuepfung_web.py`: Original-Route (PDF, Bild, XML-Download, gelöschte Datei,
  Pfad außerhalb der Ordner, Symlink aus dem Ordner, lazy Suche mit Hash-Bestätigung, Original eines
  nicht abgeschlossenen Vorgangs), Leiste (verknüpft mit einem `#panel-title` und einer `panel_bar`,
  nicht verknüpft mit Original, Original fehlt, fehlgeschlagen mit offenem Verlauf, gelöscht in
  Paperless, Paperless nicht erreichbar, ohne Anbindung), `back=doc:<id>` und ungültige Werte.
- `tests/test_repository.py`: Migration mit Alt-Schema und Index, `mark_consumed`/`set_paperless_link`,
  Abfragen `list_paperless_pending`, `list_paperless_catchup` und der Filter `paperless_missing`.
- `tests/test_pipeline.py`: `output_hash` der E-Rechnung gleich `file_hash`, `output_hash` des
  OCR-Wegs, `original_path`, Zustand `NULL` ohne Anbindung, kein `pending` nach einem Fehler nach der
  Ablage.
- `tests/test_recovery.py`, `tests/test_decisions.py`: je eine Assertion auf `original_path` (nach
  Recovery bzw. nach dem Verwerfen).
- `tests/test_worker.py`: Task `paperless-link` in der Prüfung von `background_task_states` mit und
  ohne Anbindung.
- `tests/test_web.py`: Spalte, Filter und Fall ohne Anbindung der Dokumente-Liste.

## Grenzen und Offenes

- **Keine Gegenrichtung:** Paperless-Dokumente ohne Lector-Vorgang werden nicht angezeigt. Ein Abgleich
  in dieser Richtung ist nicht Teil des Changes.
- **Keine manuelle Zuordnung** nicht gefundener Dokumente und keine Abfrage über die Paperless-Tasks-API.
- **Veränderte Datei in Paperless:** Vorgänge mit Prüfsumme haben keinen Namens-Fallback. Ändert
  Paperless die Datei beim Ablegen, bleibt der Vorgang nach 24 Stunden `not_found`. Befund 1.1 prüft
  die Filter, nicht die Prüfsumme eines frisch abgelegten Scans. Dieser Nachweis steht in Aufgabe 6.3
  aus (laut `design.md`, D5).
- **Wiederholversuch:** Eine zweite Datei in `consume` ist möglich (siehe Ablage).
- **Altbestand im Filter:** Abgeschlossene Vorgänge mit `NULL` erscheinen im Filter „Nicht in Paperless“
  erst, nachdem der Nachhol-Lauf sie geprüft hat.
- **Browser-Prüfung** (Aufgabe 5.4): Leiste bei 1800 und 390 px, offen. Der Impeccable-Detector meldet
  keine neuen Befunde.
- **Abnahme auf dem NAS** (Aufgabe 6.3): Frischer Scan, Altbestand, Leiste und Filter, offen. Die
  Ergebnisse werden anonymisiert in `prd/PROGRESS.md` festgehalten.

Bewusst so entschieden (2026-11-02):

- **Belegter Namenstreffer:** Ein Treffer, dessen ID schon ein anderer verknüpfter Vorgang trägt,
  wird verworfen, bevor gezählt wird (`PaperlessLinker._resolve_by_name`). Bleibt danach genau ein
  Treffer, wird mit ihm verknüpft; der verworfene gehört nachweislich zu einem anderen Vorgang.
- **2 bis 5 Prüfsummentreffer:** Der Vorgang bleibt `pending` und wird mit Warnung weiter gesucht,
  auch nach 24 Stunden. Paperless hält Prüfsummen eindeutig, der Fall ist ein Betriebsfehler, den das
  Log sichtbar machen soll, keine Normalität.
- **Nachlauf nach dem Start:** Einmal nach jedem Start werden alle `not_found`-Vorgänge erneut
  gesucht, unabhängig vom Alter. Die Stapel begrenzen die Last; die 14-Tage-Frist gilt nur für die
  tägliche Wiederholung.

## Verwandte Dokumente

- [dokumentansicht.md](dokumentansicht.md): Paperless-Dokumentansicht, die in der Leiste eingebettet wird.
- [../web-ui-sse.md](../web-ui-sse.md): Routen und Live-Updates.
- [../konfiguration.md](../konfiguration.md): ENV-Variablen.
- [../datenhaltung.md](../datenhaltung.md): Schema der Tabelle `documents`.
- [../pipeline-lifecycle-retry.md](../pipeline-lifecycle-retry.md): Ablauf der Pipeline, in der die Ablage passiert.
