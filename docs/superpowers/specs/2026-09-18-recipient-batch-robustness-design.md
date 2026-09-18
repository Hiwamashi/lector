# Design: Robuster Batch-Lauf für KI-Empfänger-Vorschläge

Datum: 2026-09-18
Status: freigegeben (Design), Umsetzung offen

## Problem

Der Batch-Lauf für KI-Empfänger-Vorschläge (`POST /empfaenger/suggest-batch`) ist für
den realen Bestand von ~1500 Dokumenten ohne Empfänger nicht ausgelegt. Drei Defekte
greifen ineinander:

**1. Fester Deckel bei 1000, unsichtbar.** `RECIPIENT_BATCH_MAX = 1000`
(`app/paperless_sync.py:57`) ist eine Modulkonstante. `_collect_missing_ids` sammelt
höchstens so viele IDs (`:638`, `:651`); `suggest_recipients_batch` protokolliert die
Begrenzung als `log.warning` (`:596-600`). In der Oberfläche erscheint davon nichts —
für den Anwender sieht ein Lauf, der 504 Dokumente liegen lässt, aus wie ein
abgeschlossener Lauf.

**2. Kein Rate-Limit-Handling.** `RecipientSuggester.suggest` ruft
`resp.raise_for_status()` (`app/recipient_llm.py:118`) ohne Retry und ohne Backoff. Ein
429 oder 529 der Anthropic-API wirft sofort. `suggest_recipients_batch` fängt die
Ausnahme pro Dokument (`app/paperless_sync.py:617-620`), protokolliert sie und macht
weiter. Bei 1000 sequenziellen Aufrufen ist Throttling zu erwarten; betroffene Dokumente
bleiben still ohne Vorschlag. Da die Schleife nicht abbricht, kann ein dauerhaft
gedrosseltes Konto hunderte Dokumente wirkungslos durchlaufen.

**3. Keine Rückmeldung.** Der Zustand des Laufs ist ein einzelnes Bool
(`_batch_running`, `:79`), das die Oberfläche nur als deaktivierten Button mit dem Text
„KI-Lauf läuft…" zeigt (`app/templates/recipients.html:36-37`). Es gibt keinen
Fortschritt, keine Fehlerzahl, kein Abschlusssignal und keine Möglichkeit, einen
laufenden Vorgang zu beenden. Bei ~2-3 s pro Dokument bedeutet das bis zu 75 Minuten
ohne jede Information.

Ein vierter, bereits behobener Defekt gehört zur Vorgeschichte: Die Route
`POST /empfaenger/suggest-batch` stand hinter `POST /empfaenger/{paperless_id}` und wurde
von dieser verschluckt (422, `int_parsing`). Der Batch war dadurch nie auslösbar. Die
Reihenfolge ist korrigiert, der Regressionstest heißt
`tests/test_web.py::test_recipients_suggest_batch_route_not_shadowed`. Dieses Design fügt
zwei weitere Routen unter `/empfaenger/` hinzu und muss die Falle erneut vermeiden.

## Ziel

Ein Anwender sieht vor dem Start, wie viele Dokumente anstehen, bestimmt die Menge für
den aktuellen Lauf, verfolgt den Fortschritt live und kann jederzeit abbrechen.
Vorübergehendes Throttling der Anthropic-API kostet keine Dokumente mehr; dauerhaftes
Scheitern beendet den Lauf, statt ihn wirkungslos weiterlaufen zu lassen.

## Nicht-Ziele

Bewusst ausgeschlossen, weil der Lauf wiederholbar ist und Erledigtes überspringt:

- **Kein Persistieren des Fortschritts.** Der Zustand lebt im Prozess. Ein
  Container-Neustart verwirft ihn; bereits geschriebene Vorschläge und gesetzte
  Empfänger bleiben in der Datenbank bzw. in Paperless erhalten.
- **Keine Wiederaufnahme** nach Neustart. Der Anwender startet einen neuen Lauf.
- **Keine Parallelisierung** der LLM-Aufrufe. Seriell zu bleiben ist die einfachste
  wirksame Drosselung und hält die Fehlerzuordnung eindeutig.
- **Keine Mehrfachläufe.** Es gibt weiterhin höchstens einen aktiven Lauf pro Prozess.

## Lösung

### 1. Menge pro Lauf wählbar, Bestand sichtbar

`RECIPIENT_BATCH_MAX` wird von der Modulkonstante zur Einstellung
`recipient_batch_max` in `app/config.py` (ENV `RECIPIENT_BATCH_MAX`, Default 1000). Sie
wirkt ab jetzt ausschließlich als **Obergrenze**, nicht als stiller Deckel.

`_collect_missing_ids(client, field, limit)` erhält das Limit als Parameter.
`suggest_recipients_batch(limit)` reicht es durch. Der Endpoint nimmt es als
Formularfeld entgegen und klemmt es auf `1 <= limit <= recipient_batch_max`; ungültige
oder fehlende Werte fallen auf den Default zurück, statt den Request abzulehnen.

Die Toolbar zeigt den Bestand und daneben ein Zahlenfeld für die Menge dieses Laufs.

**Achtung:** Das vorhandene `{{ count }}` (`recipients.html:30`) ist der Treffer-Zähler
der **aktuellen Suche** — bei inaktivem Filter also alle Dokumente, nicht die ohne
Empfänger. Der Batch arbeitet aber unabhängig vom Filter immer nur über Dokumente ohne
Empfänger. Der Status-Kontext ermittelt diese Zahl daher getrennt, über ein
`search_documents(page_size=1, missing_field_id=...)`, das nur den `count` auswertet.
Das Zahlenfeld ist mit `min(bestand, 100)` vorbelegt — klein genug zum Antesten, ohne
versehentlich einen Lauf über den gesamten Bestand auszulösen.

Bleibt nach einem Lauf ein Rest offen, sagt die Oberfläche das ausdrücklich
(„800 von 1504 bearbeitet — erneut starten für den Rest") statt es nur zu protokollieren.

### 2. Retry mit Backoff im LLM-Client

Der Retry gehört in `RecipientSuggester`, nicht in die Batch-Schleife: Dort liegt das
Wissen über HTTP-Statuscodes, und der Einzelvorschlag über
`POST /empfaenger/{id}/suggest` profitiert unmittelbar mit.

Um den Aufruf in `suggest` (`app/recipient_llm.py:117-119`) kommt eine Schleife mit
maximal drei Versuchen:

- Wiederholt wird bei **429**, **529** und **5xx** sowie bei `httpx.TimeoutException`.
- Die Wartezeit ist exponentiell (1 s, 2 s, 4 s). Ein `retry-after`-Header hat Vorrang
  vor diesem Wert.
- **4xx außer 429** werden nicht wiederholt — ein 400 oder 401 wird durch Warten nicht
  besser.
- Sind alle Versuche verbraucht, fliegt `RecipientSuggesterError` mit dem letzten Status.

Die Anzahl der Versuche und die Basiswartezeit sind Konstanten im Modul, keine ENV — sie
sind Implementierungsdetail, kein Betriebsparameter.

### 3. Fortschritt, Abbruch und Fehlerserien-Erkennung

`_batch_running: bool` wird durch ein Dataclass `BatchProgress` ersetzt:

| Feld | Bedeutung |
|---|---|
| `running` | Lauf aktiv |
| `total` | Anzahl der zu bearbeitenden Dokumente (nach dem Sammeln bekannt) |
| `done` | erfolgreich verarbeitet |
| `failed` | nach erschöpften Retries fehlgeschlagen |
| `remaining` | beim Sammeln festgestellter, nicht eingeplanter Rest |
| `stopped` | durch Anwender abgebrochen |
| `aborted_reason` | gesetzt, wenn der Lauf wegen einer Fehlerserie endete |
| `finished_at` | Ende des letzten Laufs; trägt die Abschlussmeldung |

Das Objekt ist über die Property `batch_progress` lesbar. Die bisherige Property
`batch_running` **entfällt**: Sie hat genau zwei Konsumenten (`main.py:414` und
`recipients.html:36-37`), die beide in dieser Änderung ohnehin angefasst werden. Eine
Kompatibilitätsschicht für null externe Aufrufer wäre toter Code.

**Abbruch:** `POST /empfaenger/suggest-batch/stop` setzt ein Flag, das die Schleife vor
jedem Dokument prüft. Der Lauf endet nach dem gerade laufenden Dokument; alles bereits
Verarbeitete bleibt. Ein Abbruch ist kein Fehler und wird als solcher auch nicht gezählt.

**Fehlerserie:** Zehn aufeinanderfolgende Fehlschläge beenden den Lauf mit gesetztem
`aborted_reason`. Ein einzelner erfolgreicher Vorschlag setzt den Zähler zurück. Damit
läuft ein gedrosseltes oder fehlkonfiguriertes Konto nicht durch hunderte Dokumente.

**Live-Anzeige:** Der Lauf meldet Fortschritt über den bestehenden Event-Bus
(`app/events.py`) mit dem Token `batch:recipient` — passend zur Konvention
`<typ>:<kennung>` neben `doc:`, `inv:` und `rec:`. Gemeldet wird **höchstens alle zwei
Sekunden**, zusätzlich immer beim Start und beim Ende. Ohne diese Drosselung erzeugt ein
Lauf über 1500 Dokumente ebenso viele Ereignisse, die der Bus an jeden verbundenen
Client verteilt.

Die Toolbar wird zu einem eigenen Fragment `GET /fragment/empfaenger/batch-status`.
`app/static/app.js` lädt bislang nur `table.history[data-fragment]` und `#detail`
(`app.js:8-22`) und bekommt einen dritten Block für `#batch-status[data-fragment]`. Die
im Frontend vorhandene Entprellung von 250 ms (`app.js:47`) greift dabei unverändert.

### Routen-Reihenfolge

Beide neuen Routen liegen unter `/empfaenger/` und müssen **vor**
`POST /empfaenger/{paperless_id}` registriert werden:

```
POST /empfaenger/suggest-batch        (2 Segmente — kollidiert mit /empfaenger/{id})
POST /empfaenger/suggest-batch/stop   (3 Segmente — kollidiert mit /empfaenger/{id}/suggest)
GET  /fragment/empfaenger/batch-status (kollisionsfrei, eigener Präfix)
```

`suggest-batch/stop` kollidiert mit `{paperless_id}/suggest` nur, wenn beide Segmente
passen — das dritte Segment (`stop` vs. `suggest`) unterscheidet sich, ein echter
Konflikt besteht also nicht. Verlassen wird sich darauf nicht: Ein generischer Test
prüft **alle** Routen der Anwendung paarweise darauf, ob eine früher registrierte,
parametrisierte Route eine später registrierte, statische verdeckt. Damit ist die Klasse
von Fehlern abgedeckt, nicht nur der bekannte Einzelfall.

## Datenfluss

```
Anwender klickt „KI-Vorschlag" (Menge n)
  → POST /empfaenger/suggest-batch (limit=n, geklemmt auf 1..recipient_batch_max)
  → start_batch(limit) legt asyncio-Task an, hält Referenz
  → _collect_missing_ids(client, field, limit)
       paginiert über Paperless (nur Dokumente ohne Empfänger),
       überspringt bereits gecachte  → Liste[int], plus Rest-Zähler
  → BatchProgress(total=len(ids), remaining=Rest) → publish "batch:recipient"
  → pro Dokument:
       Stopp-Flag? → Abbruch
       Cache erneut prüfen (kann sich während des Laufs geändert haben)
       get_document → _suggest_for_doc → RecipientSuggester.suggest
            ├─ 429/529/5xx/Timeout → bis zu 3 Versuche mit Backoff
            └─ erschöpft → RecipientSuggesterError → failed += 1
       done/failed fortschreiben
       Fehlerserie == 10? → Abbruch mit aborted_reason
       publish "batch:recipient", höchstens alle 2 s
  → finally: running=False, finished_at setzen, publish "batch:recipient"

Browser: EventSource /events → Token "batch:recipient"
  → 250 ms Entprellung → GET /fragment/empfaenger/batch-status → Toolbar ersetzt
```

## Fehlerbehandlung

| Fall | Verhalten |
|---|---|
| 429 / 529 / 5xx / Timeout | bis zu 3 Versuche mit Backoff, `retry-after` bevorzugt |
| 4xx außer 429 | kein Retry, Dokument zählt als `failed` |
| Retries erschöpft | Dokument zählt als `failed`, Lauf geht weiter |
| 10 Fehler in Folge | Lauf endet, `aborted_reason` gesetzt, Anzeige in der Oberfläche |
| Paperless nicht erreichbar | wie bisher: Ausnahme pro Dokument, protokolliert, `failed` |
| Anwender bricht ab | Lauf endet nach dem laufenden Dokument, `stopped=True`, kein Fehler |
| Zweiter Start bei laufendem Lauf | wie bisher abgewiesen; die Oberfläche zeigt den Grund statt stillschweigend zu verwerfen |
| Container-Neustart | Fortschritt verloren, Daten konsistent, neuer Lauf nötig |

## Testkonzept

Alle Tests laufen ohne Netz. Der LLM-Client wird über einen
`httpx.MockTransport` bedient, Wartezeiten über ein gepatchtes `asyncio.sleep` geprüft,
damit die Suite schnell bleibt.

| Bereich | Test |
|---|---|
| Retry | 429 → 200 ergibt ein Ergebnis; Anzahl der Versuche stimmt |
| Retry | `retry-after` schlägt den exponentiellen Wert |
| Retry | 400 wird nicht wiederholt |
| Retry | drei Fehlschläge ergeben `RecipientSuggesterError` |
| Limit | `_collect_missing_ids` liefert höchstens `limit` IDs und meldet den Rest |
| Limit | Endpoint klemmt auf `1..recipient_batch_max`, fällt bei Unsinn auf Default |
| Abbruch | Stopp nach dem ersten Dokument, `done` bleibt bei 1, `stopped=True` |
| Fehlerserie | 10 Fehlschläge in Folge beenden den Lauf, `aborted_reason` gesetzt |
| Fehlerserie | ein Erfolg dazwischen setzt den Zähler zurück |
| Fortschritt | `BatchProgress` nach dem Lauf trägt `total`/`done`/`failed` korrekt |
| Drossel | ein Lauf über viele Dokumente meldet deutlich weniger Ereignisse als Dokumente |
| Routen | generischer Shadowing-Test über alle Routen der Anwendung |
| Endpoints | Stopp- und Status-Fragment antworten auch ohne Paperless-Anbindung sauber |

## Berührte Dateien

| Datei | Änderung |
|---|---|
| `app/config.py` | `recipient_batch_max` als Einstellung (ENV `RECIPIENT_BATCH_MAX`) |
| `app/recipient_llm.py` | Retry mit Backoff um den API-Aufruf |
| `app/paperless_sync.py` | `BatchProgress`, Limit-Parameter, Stopp-Flag, Fehlerserie, gedrosseltes Publish |
| `app/main.py` | `limit` im Batch-Endpoint, Stopp-Route, Status-Fragment, Kontext |
| `app/templates/recipients.html` | Toolbar als eingebundenes Fragment |
| `app/templates/partials/batch_status.html` (neu) | Bestand, Mengenfeld, Fortschritt, Stopp |
| `app/static/app.js` | dritter Fragment-Block für `#batch-status` |
| `tests/test_recipients.py` | Retry, Limit, Abbruch, Fehlerserie, Fortschritt |
| `tests/test_web.py` | Endpoints, generischer Shadowing-Test |
| `.env.example` | `RECIPIENT_BATCH_MAX` dokumentiert |
| `feature-documentation/paperless-integration/empfaenger-zuordnung.md` | Fallstricke und Betrieb nachziehen |
| `prd/PROGRESS.md` | Fortschrittseintrag |

## Offene Punkte

Keine. Die Kostenfrage eines Laufs über den gesamten Bestand (~1500 LLM-Aufrufe) ist
bewusst nicht Teil dieses Designs — die wählbare Menge pro Lauf gibt dem Anwender die
Kontrolle darüber. Eine Schätzung kann bei Bedarf getrennt erstellt werden.
