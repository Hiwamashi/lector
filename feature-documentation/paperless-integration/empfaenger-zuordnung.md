# Empfänger-Zuordnung (+ KI-Vorschlag)

**Module:** `app/paperless.py` (Client-Helfer), `app/recipient_llm.py` (LLM),
`app/paperless_sync.py` (Orchestrierung), `app/main.py` (Routen), `app/repository.py` +
`app/db.py` (Vorschlags-Cache), Templates `recipients.html` / `partials/recipient_rows.html`.

## Zweck

Paperless-ngx kennt **kein** natives Empfänger-Feld (nur den *Korrespondenten* = Gegenpartei).
Der Empfänger (an WEN ging das Dokument) wird daher über ein in Paperless gepflegtes
**Custom Field „Empfänger" vom Typ `select`** abgebildet (z.B. Familienmitglieder als Optionen).
Lector erlaubt, diesen Empfänger an **jedem** Paperless-Dokument zu setzen — und optional per
KI vorzuschlagen.

**Kernprinzip:** Der maßgebliche Wert lebt im Paperless-Feld. Lector spiegelt das Archiv
**nicht** lokal — die Übersicht liest live über die API, lokal liegt nur der KI-Vorschlag-Cache.

## select-Feld in Paperless

- `CF_RECIPIENT` (Default „Empfänger") benennt das Feld. Lector legt es **nicht** an
  (`resolve_select_field` sucht es nur) — Feld + Optionen pflegst du in Paperless, damit die
  Auswahl kuratiert bleibt.
- Bei `select`-Feldern ist der gespeicherte Wert die **Options-ID** (z.B. `a4B0i4oDHTPB9g2M`),
  nicht das Label. `SelectField.label_to_id` / `id_to_label` übersetzen beides.
  `PaperlessClient.select_value(doc, field_id)` liest den gesetzten Wert aus einem Dokument.

## Übersicht & Routen (`/empfaenger`)

- `GET /empfaenger` — paginierte Live-Liste (`search_documents`, `RECIPIENT_PAGE_SIZE=50`).
  Volltextsuche (`query`) und Schnellfilter-Chip „Nur ohne Empfänger" (Paperless `custom_field_query`
  mit `[ "AND", [[<field_id>, "exists", false]] ]`). Korrespondentennamen aus
  `correspondent_map()` (einmal pro Prozess gecacht).
- `GET /fragment/empfaenger` — Zeilen-Fragment (SSE-Refresh über `data-fragment`).
- `POST /empfaenger/{id}` — Empfänger setzen/leeren (`set_recipient`). Wert = Options-ID,
  `""` → Feld leeren (`null`).
- `POST /empfaenger/{id}/suggest` — KI-Vorschlag für ein Dokument.
- `POST /empfaenger/suggest-batch` — Hintergrund-Lauf über Dokumente ohne Empfänger
  (`asyncio.create_task`, gegen Doppelstart über die gehaltene Task-Referenz gesichert). Die
  Menge (Formularfeld `limit`) wählt der Anwender in der Oberfläche; der Endpoint klemmt sie
  über `_clamp_batch_limit` auf `1..RECIPIENT_BATCH_MAX`. Ein fehlendes oder unlesbares Feld
  (leeres `limit`, z.B. weil der Anwender den vorbelegten Wert gelöscht hat — HTML5 blockt das
  bei `<input type="number">` ohne `required` nicht) fällt auf die konservative Vorbelegung
  zurück (höchstens 100), **nicht** auf `RECIPIENT_BATCH_MAX` — sonst löst ein leeres Feld
  einen ungewollten Maximallauf aus.
- `POST /empfaenger/suggest-batch/stop` — bittet einen laufenden Batch, nach dem aktuellen
  Dokument zu enden (`PaperlessSync.stop_batch`). Kein Fehler, zählt nicht als Fehlschlag.
- `GET /fragment/empfaenger/batch-status` — eigenes Toolbar-Fragment mit dem aktuellen
  `BatchProgress` (Start/Stop-Button, Zähler, `aborted_reason`), per SSE aktualisiert.
  Scheitert der Zählaufruf (`count_missing_recipients`, z.B. Paperless-Aussetzer), zeigt das
  Fragment „kann gerade nicht ermittelt werden" statt fälschlich `0` zu behaupten — der
  Start-Button bleibt dabei bewusst **nutzbar** (`missing_total_unknown`), sonst friert ein
  einziger Aussetzer den Button ein, bis die Seite manuell neu geladen wird.
- `GET /fragment/empfaenger` (Zeilen-Fragment) ruft `_batch_status_context` bewusst **nicht**
  auf (`with_batch_status=False`) — `partials/recipient_rows.html` nutzt weder `missing_total`
  noch `progress`, der Zählaufruf wäre dort nur verschwendet.

Das Feature braucht nur die Paperless-Anbindung (`recipient_enabled` = URL + Token),
**unabhängig** von `FEATURE_PAPERLESS_SYNC`.

## KI-Vorschlag (`RecipientSuggester`)

- httpx-basierter Client gegen die Anthropic-Messages-API (konsistent zu `paperless.py` /
  `sevdesk.py`, keine neue Abhängigkeit). Reaktiviert die ohnehin im Stack vorhandene
  Anthropic-Anbindung (vgl. paperless-gpt).
- **Tool-Use erzwingt valide Ausgabe:** Das Modell ruft das Tool `set_recipient` mit
  `recipient` (enum aus den erlaubten Labels + `unbekannt`), `confidence` (0..1) und
  `reasoning` auf. Labels außerhalb der Optionen werden hart auf `None` gemappt — die KI
  kann **keine** neuen Empfänger erfinden.
- **Zusatzfeld `it_consulting_probability`** (Pflichtfeld, Typ `number`): Wahrscheinlichkeit
  (0 bis 1), dass das Dokument eine Ausgabe des Kontexts ist, **unabhängig** vom vorgeschlagenen
  Empfänger. Das Feld kommt nur dann ins Tool-Schema, wenn der `RecipientSuggester` ein
  Kontext-Label erhält. `PaperlessSync._suggester()` übergibt `SEVDESK_CONTEXT_LABEL`. Der
  Absatz im System-Block nennt das Label ebenfalls. Der Absatz steht fest im Prompt, damit das
  Prompt-Caching greift.
- **Parsing:** Nur echte Zahlen von 0 bis 1 gelten (`_parse_probability`). Alles andere wird
  zu `None`: Strings, Wahrheitswerte, NaN, Werte außerhalb des Bereichs und ein fehlendes Feld.
  Der Empfänger-Vorschlag bleibt in diesem Fall gültig. Das Dokument gilt dann als „nicht
  eingeschätzt“ (siehe [kontext-einstufung.md](kontext-einstufung.md)).
- **Speicherung:** Der Wert wird mit dem Vorschlag in `document_recipients.it_probability`
  geschrieben. Die Übersicht braucht dafür keinen weiteren KI-Aufruf.
- Eingabe: Titel + Korrespondent + gekürzter OCR-Text (`_MAX_CONTENT_CHARS=6000`). Der
  statische System-Block wird per Prompt-Caching wiederverwendet.

### Anwendung (`RECIPIENT_LLM_AUTO_APPLY`)

- `true` (Default): Vorschlag mit `confidence >= RECIPIENT_LLM_MIN_CONFIDENCE` (Default 0.75)
  und gültigem Label wird **direkt** ins Paperless-Feld geschrieben.
- Sonst (oder unter der Schwelle / „unbekannt"): nur Vorschlag im Cache (`document_recipients`,
  Status `suggested`/`unknown`), in der UI als Badge sichtbar.

## Datenmodell

- Tabelle `document_recipients`: `paperless_id` (PK), `suggested_label`, `confidence`,
  `reasoning`, `status` (`none|suggested|applied|unknown`), `it_probability` (REAL, `NULL` =
  nicht eingeschätzt), `updated_at`. Reiner Cache — überlebt der KI-Vorschlag einen Reload ohne
  erneuten LLM-Aufruf. Die Spalte `it_probability` kommt per `_migrate()` in bestehende
  Datenbanken.
- Schreibt Lector den Vorschlag in den Cache (also nicht im Auto-Apply-Fall), wird
  `it_probability` immer mitgeschrieben, auch als `NULL`. Ein Aufruf ohne gültige
  IT-Einschätzung löscht also einen zuvor gespeicherten Wert. Die Ausnahme ist
  `mark_recipient_applied`: Es setzt den Status auf `applied`, leert Vorschlag, Konfidenz und
  Begründung und lässt die IT-Einschätzung unverändert.
- **Automatisch angewendeter Vorschlag** (`RECIPIENT_LLM_AUTO_APPLY`): Der Vorschlag geht direkt
  in das Paperless-Feld. Dabei entsteht über `mark_recipient_applied` nur ein Status-Eintrag
  `applied`, ohne Vorschlag und ohne IT-Einschätzung. Das Dokument hat dann einen Empfänger, und
  die Einstufung nutzt den Empfänger als Quelle 1.
- Repository: `get_recipient_cache(s)`, `set_recipient_cache`, `mark_recipient_applied`,
  `notify_recipient` (SSE-Token `rec:<id>`), `notify_batch` (SSE-Token `batch:recipient`,
  gedrosselt auf höchstens alle `BATCH_PUBLISH_INTERVAL=2.0` Sekunden; Start und Ende des
  Laufs werden immer gemeldet). `set_recipient_cache`/`mark_recipient_applied` akzeptieren
  `notify: bool = True` — der Batch-Lauf ruft sie mit `notify=False` auf (intern über
  `guard_concurrent`), damit nicht zusätzlich zum gedrosselten `batch:recipient` **pro
  Dokument** ein eigenes ungedrosseltes `rec:<id>` feuert. Der nutzerinitiierte
  Einzel-Vorschlag (`guard_concurrent=False`) meldet weiterhin sofort.
- `PaperlessSync.batch_progress` liefert die Dataclass `BatchProgress` (`running`, `total`,
  `done`, `failed`, `skipped`, `remaining`, `stopped`, `aborted_reason`, `finished_at`) — lebt
  nur im Prozess, überlebt keinen Neustart. `skipped` zählt Dokumente, die der Lauf wegen
  eines zwischenzeitlich gesetzten Empfängers/Vorschlags überspringt (weder `done` noch
  `failed`); `remaining` ist nach Laufende der tatsächliche offene Rest — Dokumente jenseits
  des Limits **plus** eingeplante, aber wegen Stopp/Fehlerserie/Ausnahme nicht mehr erreichte
  Dokumente (nicht nur der Limit-Rest, siehe Fallstricke unten).
- `PaperlessSync.shutdown()` bricht einen laufenden Batch beim Herunterfahren des Prozesses ab
  (`task.cancel()` + `asyncio.gather(..., return_exceptions=True)`) und wird im Lifespan
  **vor** `repo.close()` aufgerufen — sonst könnte der Task bei einem SIGTERM mitten im Lauf
  auf die bereits geschlossene SQLite-Verbindung zugreifen.

## Batch-Auswahl und IT-Einschätzung

`_collect_missing_ids(client, field, limit)` (`app/paperless_sync.py`) bestimmt die Menge eines
Batch-Laufs:

- Berücksichtigt werden nur Dokumente **ohne** gesetzten Empfänger (Paperless-Filter
  `missing_field_id`).
- **Übersprungen** wird ein Dokument mit vollständigem Cache-Eintrag: Status ungleich `none` **und**
  `it_probability` gesetzt (`_recipient_cache_complete`).
- **Aufgenommen** werden alle übrigen, also auch Einträge aus der Zeit vor dem Change, die einen
  Vorschlag, aber keine IT-Einschätzung haben. Der Batch ergänzt die Einschätzung dann nach.
- Die Auswahl läuft über alle Seiten. Ist das Limit erreicht, zählt sie die übrigen passenden
  Dokumente als `rest`.

Ein Dokument mit Vorschlag **und** Einschätzung, aber ohne Empfänger, wird also übersprungen. Ein
Dokument ohne Vorschlag wird bearbeitet.

### Fallstrick: ungültiger KI-Wert führt zu erneuter Anfrage

Liefert die KI keine gültige IT-Einschätzung (Wert außerhalb 0 bis 1, Text, fehlend), wird
`it_probability` als `NULL` gespeichert. Der Eintrag gilt dann als **unvollständig**. Der nächste
Batch-Lauf wählt das Dokument erneut aus und stellt die KI-Anfrage nochmals. Das wiederholt sich
bei jedem Lauf, solange der Wert ungültig bleibt, und kostet jedes Mal Tokens.

Lector hat dafür keinen Zähler und keinen Sperrvermerk. Das ist **bewusst unverändert**: Eine
Gegenmaßnahme (Zählung, Sperrvermerk oder Wiederholgrenze) ist nicht umgesetzt. Der Kostenhinweis
gilt weiterhin.

TODO: Wie oft die KI in der Praxis ungültige Werte liefert, ist nicht gemessen.

## Konfiguration (ENV)

`CF_RECIPIENT`, `FEATURE_RECIPIENT_LLM`, `ANTHROPIC_API_KEY`, `RECIPIENT_LLM_MODEL`
(Default `claude-sonnet-4-6`), `RECIPIENT_LLM_AUTO_APPLY`, `RECIPIENT_LLM_MIN_CONFIDENCE`,
`RECIPIENT_BATCH_MAX` (Default 1000, Obergrenze für einen Batch-Lauf — die tatsächliche Menge
wählt der Anwender pro Lauf in der Oberfläche). Für die IT-Einschätzung zusätzlich
`SEVDESK_CONTEXT_LABEL` (Default `IT-Consulting`, siehe [konfiguration.md](../konfiguration.md)).

## Fallstricke

- **`follow_redirects=True`** im Paperless-Client: paginierte `next`-URLs kommen teils mit
  `http`-Schema und lösen hinter dem HTTPS-Proxy einen 308 aus — muss verfolgt werden.
- Der Batch-Lauf ist auf `RECIPIENT_BATCH_MAX` (Default 1000) Dokumente pro Durchlauf gedeckelt
  und überspringt Dokumente mit vollständigem Cache-Eintrag (Vorschlag und IT-Einschätzung) sowie
  gesetzte Dokumente — damit gefahrlos wiederholbar. Bleiben
  wegen des Limits Dokumente offen, zählt `BatchProgress.remaining` sie; das erscheint in der
  Toolbar, nicht nur im Log. Der Lauf muss dann erneut gestartet werden.
- **Angezeigter Bestand ≠ Arbeitsmenge des Laufs:** `missing_total` (Toolbar) zählt Dokumente
  ohne gesetzten Empfänger, per `count_missing_recipients`. `_collect_missing_ids` überspringt
  zusätzlich Dokumente mit vollständigem Cache-Eintrag (Vorschlag und IT-Einschätzung vorhanden;
  ein Vorschlag unter der Konfidenzschwelle oder „unbekannt" setzt das Paperless-Feld nicht) — die
  tatsächliche Arbeitsmenge eines Laufs kann daher kleiner sein als der angezeigte Bestand.
  Einträge ohne IT-Einschätzung zählen dagegen wieder zur Arbeitsmenge. Ein exakter
  Abgleich bräuchte bei jedem Seitenaufruf einen Vollscan und ist bewusst nicht implementiert;
  die Toolbar benennt daher präzise „ohne gesetzten Empfänger" statt eine 1:1-Deckung zu
  suggerieren. Endet ein Lauf mit `total == 0` (nichts Neues zu tun), zeigt die Oberfläche das
  ausdrücklich statt „0 verarbeitet".
- **Ausnahme vor/während der Dokumentschleife** (z.B. `_recipient_field_cached` oder
  `_collect_missing_ids` scheitert, weil Paperless gerade neu startet) wird gefangen, geloggt
  und setzt `BatchProgress.aborted_reason` — ohne das würde der Hintergrund-Task mit einer nie
  abgeholten Ausnahme sterben und die Oberfläche „0 verarbeitet" ohne jeden Hinweis zeigen.
  Derselbe Weg gilt für den frühen Ausstieg, wenn das Empfänger-Feld fehlt oder keine
  Auswahloptionen hat.
- **`retry-after` ist gedeckelt** (`recipient_llm._MAX_RETRY_AFTER`, 60 s): Ohne Obergrenze
  könnte ein serverseitiges `retry-after: 600` den Lauf zehn Minuten in einem Dokument hängen
  lassen, während „Abbrechen" so lange wirkungslos bliebe.
- **Kontext-Schlüssel des Zeilen-Fragments:** `/fragment/empfaenger` rendert
  `partials/recipient_rows.html` **ohne** Batch-Status (spart einen Paperless-Zählaufruf).
  Alles, was dieses Template braucht — `filters`, `page` —, muss deshalb im Grundkontext von
  `_recipient_context` liegen, nicht in `_batch_status_context`. Vorsicht bei Tests: Ohne
  Paperless-Anbindung antwortet die Route mit 404, das Template wird dann **gar nicht**
  gerendert. Ein fehlender Schlüssel fällt sonst erst im Betrieb als 500 auf. Regressionstest:
  `tests/test_web.py::test_recipient_row_fragment_renders_with_paperless`.
- **Routen-Reihenfolge:** `POST /empfaenger/suggest-batch` und `POST /empfaenger/suggest-batch/stop`
  müssen in `app/main.py` **vor** `POST /empfaenger/{paperless_id}` registriert sein. Starlette
  matcht in Registrierungsreihenfolge — andernfalls fängt die parametrisierte Route den
  statischen Pfad ab und der Batch-Klick endet in einem 422 (`int_parsing`,
  `input="suggest-batch"`) statt den Lauf zu starten. Regressionstests:
  `tests/test_web.py::test_recipients_suggest_batch_route_not_shadowed` sowie der generische
  `tests/test_web.py::test_no_route_is_shadowed_by_a_parametrised_one`, der jede
  Routen-Registrierung der App gegen dieses Muster prüft.
- **Retry im LLM-Client:** `recipient_llm.py` wiederholt 429/529/5xx und Timeouts bis zu
  dreimal mit exponentiellem Backoff; ein `retry-after` des Servers hat Vorrang. 4xx außer
  429 werden nicht wiederholt. Erst danach zählt der Batch ein Dokument als Fehler.
- **Fehlerserie beendet den Lauf:** Zehn Fehlschläge in Folge (`BATCH_ERROR_STREAK`) brechen
  den Batch ab und setzen `aborted_reason`, sichtbar in der Toolbar.
- **Fortschritt ist nicht persistent:** `BatchProgress` lebt im Prozess. Ein Neustart
  verwirft ihn; geschriebene Vorschläge und gesetzte Empfänger bleiben erhalten.
