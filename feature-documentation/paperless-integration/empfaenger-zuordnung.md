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
  Volltextsuche (`query`) und Filter „nur ohne Empfänger" (Paperless `custom_field_query`
  mit `[ "AND", [[<field_id>, "exists", false]] ]`). Korrespondentennamen aus
  `correspondent_map()` (einmal pro Prozess gecacht).
- `GET /fragment/empfaenger` — Zeilen-Fragment (SSE-Refresh über `data-fragment`).
- `POST /empfaenger/{id}` — Empfänger setzen/leeren (`set_recipient`). Wert = Options-ID,
  `""` → Feld leeren (`null`).
- `POST /empfaenger/{id}/suggest` — KI-Vorschlag für ein Dokument.
- `POST /empfaenger/suggest-batch` — Hintergrund-Lauf über Dokumente ohne Empfänger
  (`asyncio.create_task`, gegen Doppelstart über die gehaltene Task-Referenz gesichert). Die
  Menge (Formularfeld `limit`) wählt der Anwender in der Oberfläche; der Endpoint klemmt sie
  über `_clamp_batch_limit` auf `1..RECIPIENT_BATCH_MAX`.
- `POST /empfaenger/suggest-batch/stop` — bittet einen laufenden Batch, nach dem aktuellen
  Dokument zu enden (`PaperlessSync.stop_batch`). Kein Fehler, zählt nicht als Fehlschlag.
- `GET /fragment/empfaenger/batch-status` — eigenes Toolbar-Fragment mit dem aktuellen
  `BatchProgress` (Start/Stop-Button, Zähler, `aborted_reason`), per SSE aktualisiert.

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
- Eingabe: Titel + Korrespondent + gekürzter OCR-Text (`_MAX_CONTENT_CHARS=6000`). Der
  statische System-Block wird per Prompt-Caching wiederverwendet.

### Anwendung (`RECIPIENT_LLM_AUTO_APPLY`)

- `true` (Default): Vorschlag mit `confidence >= RECIPIENT_LLM_MIN_CONFIDENCE` (Default 0.75)
  und gültigem Label wird **direkt** ins Paperless-Feld geschrieben.
- Sonst (oder unter der Schwelle / „unbekannt"): nur Vorschlag im Cache (`document_recipients`,
  Status `suggested`/`unknown`), in der UI als Badge sichtbar.

## Datenmodell

- Tabelle `document_recipients`: `paperless_id` (PK), `suggested_label`, `confidence`,
  `reasoning`, `status` (`none|suggested|applied|unknown`), `updated_at`. Reiner Cache —
  überlebt der KI-Vorschlag einen Reload ohne erneuten LLM-Aufruf.
- Repository: `get_recipient_cache(s)`, `set_recipient_cache`, `mark_recipient_applied`,
  `notify_recipient` (SSE-Token `rec:<id>`), `notify_batch` (SSE-Token `batch:recipient`,
  gedrosselt auf höchstens alle `BATCH_PUBLISH_INTERVAL=2.0` Sekunden; Start und Ende des
  Laufs werden immer gemeldet).
- `PaperlessSync.batch_progress` liefert die Dataclass `BatchProgress` (`running`, `total`,
  `done`, `failed`, `remaining`, `stopped`, `aborted_reason`, `finished_at`) — lebt nur im
  Prozess, überlebt keinen Neustart.

## Konfiguration (ENV)

`CF_RECIPIENT`, `FEATURE_RECIPIENT_LLM`, `ANTHROPIC_API_KEY`, `RECIPIENT_LLM_MODEL`
(Default `claude-sonnet-4-6`), `RECIPIENT_LLM_AUTO_APPLY`, `RECIPIENT_LLM_MIN_CONFIDENCE`,
`RECIPIENT_BATCH_MAX` (Default 1000, Obergrenze für einen Batch-Lauf — die tatsächliche Menge
wählt der Anwender pro Lauf in der Oberfläche).

## Fallstricke

- **`follow_redirects=True`** im Paperless-Client: paginierte `next`-URLs kommen teils mit
  `http`-Schema und lösen hinter dem HTTPS-Proxy einen 308 aus — muss verfolgt werden.
- Der Batch-Lauf ist auf `RECIPIENT_BATCH_MAX` (Default 1000) Dokumente pro Durchlauf gedeckelt
  und überspringt bereits gecachte/gesetzte Dokumente — damit gefahrlos wiederholbar. Bleiben
  wegen des Limits Dokumente offen, zählt `BatchProgress.remaining` sie; das erscheint in der
  Toolbar, nicht nur im Log. Der Lauf muss dann erneut gestartet werden.
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
