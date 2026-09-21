# Bewahrte OCR-Teilergebnisse

**Module:** `app/ocr/base.py` (`ChunkStore`, `SafeChunkStore`, `ProgressCallback`),
`app/ocr/documentai.py` (Blockschleife), `app/models.py`
(`ocr_pages_to_payload` / `ocr_pages_from_payload`), `app/repository.py`
(`store_chunk_result`, `load_chunk_result`, `clear_chunk_results`,
`purge_chunk_results`), `app/pipeline.py` (`chunk_fingerprint`,
`_RepositoryChunkStore`), `app/retention.py`, `app/db.py` (Tabelle `ocr_chunk_cache`).

## Wozu

Vor dieser Funktion sammelte `process()` die Blockergebnisse in einer lokalen Variable.
Wirft ein Block — Netzwerkabbruch, Quota-Antwort, eine zurückgewiesene Seite —, riss die
Ausnahme jedes bereits **bezahlte** Blockergebnis mit. Der Wiederholversuch begann bei Seite
eins und kaufte dieselben Seiten erneut. Bei einem 60-seitigen Dokument, das im letzten Block
scheitert, sind das drei vergebliche Blöcke pro Anlauf; bei `RETRY_MAX=3` bis zu neun.

## Ablauf

```
für jeden Block:
    im Zwischenspeicher nachsehen (Schlüssel: Vorgang + Blockindex, Fingerabdruck muss passen)
      ├─ Treffer → verwenden, KEINE Anfrage, KEINE Drosselung
      └─ kein Treffer → drosseln → Engine fragen → Ergebnis ablegen → weiter
Fortschritt melden (mit Kennzeichen, ob aus dem Zwischenspeicher)
```

## Woran ein bewahrter Block als gültig erkannt wird

`chunk_fingerprint()` hasht alles, was das Erkennungsergebnis beeinflusst:

| Bestandteil | Warum |
|---|---|
| Prüfsumme des Originals | anderer Inhalt → anderes Ergebnis |
| Blockgröße und Engine-Seitenlimit | andere Blockgrenzen → andere Seiten im Block |
| `PREPROCESS_DESKEW`, `PREPROCESS_CONTRAST` | andere Bilder → andere Erkennung |
| Renderauflösung | dito |
| `adapter.identity` | anderer Dienst/andere Konfiguration → anderes Ergebnis |

Passt der Fingerabdruck nicht, wird der Eintrag **nicht** gelesen — und beim nächsten Lauf
per Upsert überschrieben, statt als Müll liegen zu bleiben. Deshalb steht er *neben* dem
Primärschlüssel `(document_id, chunk_index)`, nicht darin.

**Die Prüfsumme wird pro Lauf neu gebildet**, nicht aus `doc.file_hash` der Datenbank
übernommen: `_handle_ocr` hasht die Datei, die es gerade von der Platte liest
(`app/fileops.py:file_hash`), und gibt diesen Wert in den Fingerabdruck. Ein eingeplanter
Wiederholversuch lässt das Original bis zu `RETRY_DELAY_MINUTES` im Eingang liegen — landet
in diesem Fenster eine andere Datei unter demselben Namen, weicht die frische Prüfsumme vom
gespeicherten `doc.file_hash` ab (geloggt als `log.warning`), und bewahrte Blöcke des alten
Dokuments greifen dadurch von selbst nicht mehr. Lässt sich die Datei nicht hashen (`OSError`),
wird für diesen Lauf gar kein Zwischenspeicher verwendet — wie beim fehlenden `file_hash`.

`adapter.identity` ersetzt frühere engine-spezifische Einstellungsfelder direkt im
Fingerabdruck: Der Document-AI-Adapter baut sie aus Projekt, Region und Prozessor
(`projects/{project}/locations/{loc}/processors/{id}`) — nur diese Kombination identifiziert
einen Prozessor eindeutig. So bleibt `chunk_fingerprint()` selbst engine-unabhängig; eine
künftige Engine (Textract, Cloud Vision) bringt ihre eigene `identity` mit, ohne dass die
Pipeline etwas über deren Konfiguration wissen muss.

**Bewusst nicht über die erzeugten Bilder.** Ein Schlüssel über die aufbereiteten Seiten wäre
exakter, setzte aber voraus, dass Rasterung und Schieflagenkorrektur bitgenau reproduzierbar
sind. Das ist im Projekt nirgends belegt. Wäre es auch nur um ein Pixel nicht der Fall,
griffe der Zwischenspeicher nie — die Funktion liefe mit, ohne je zu wirken.

**Ohne `file_hash` am Vorgang** wird gar kein Zwischenspeicher verwendet: Der Schlüssel trüge
nicht, und ein falsch zugeordnetes Ergebnis wäre schlimmer als eine erneute Erkennung.

## Warum die Drosselung hinter dem Nachsehen sitzt

`DOCAI_MAX_PAGES_PER_MINUTE` schützt die Quota der Engine. Ohne Anfrage an die Engine gibt es
nichts zu drosseln. Stünde `acquire()` weiterhin vor dem Nachsehen, wäre ein
Wiederholversuch, der jede Seite aus dem Zwischenspeicher bedient, **genauso langsam** wie der
ursprüngliche Lauf — bei 120 Seiten/Minute eine halbe Minute Wartezeit für Anfragen, die nie
stattfinden.

## Sichtbarkeit im Verlauf

Der `ocr_chunk`-Eintrag eines wiederverwendeten Blocks trägt den Zusatz „aus
Zwischenspeicher, keine erneute Erkennung". Ohne das sähe ein Lauf, der ein langes Dokument
in Sekunden abschließt, wie eine Fehlfunktion aus.

## Wann Einträge verschwinden

Zwei Wege, bewusst beide:

- **Sofort** beim Übergang in einen Endzustand (`done`, `skipped_erechnung`, `failed`) — es
  kommt kein Wiederholversuch mehr. `set_status` erledigt das; `transition_from_blocked`
  umgeht `set_status` und ruft die Freigabe eigens auf.
- **Als Netz** im stündlichen Aufbewahrungsjob (`purge_chunk_cache`): Einträge zu Vorgängen in
  einem Endzustand und Einträge älter als `CHUNK_CACHE_RETENTION_DAYS` (Standard 7).
  `0` schaltet nur das Verfallen ab, nicht das Aufräumen abgeschlossener Vorgänge.

Ein eingeplanter Wiederholversuch lässt die Einträge stehen — gerade dann werden sie
gebraucht. Ebenso eine Freigabe aus dem Wartezustand `blocked` zurück nach `pending`.

Die Historie bleibt in jedem Fall unangetastet: Entfernt werden nur die Zwischenergebnisse,
nie der Vorgang oder sein Verlauf.

## Ein bewahrter Block muss zur Blocklänge passen

Ein Lauf, der von der Engine ein Document mit null oder zu wenigen Seiten zurückbekommt
(HTTP 200, aber leerer Inhalt), darf das nicht als gültiges Ergebnis ablegen — sonst gälte
beim nächsten Lauf `[]` als Treffer, und der fehlende Textlayer würde nie mehr geheilt. Zwei
unabhängige Prüfungen fangen das ab:

- `Repository.load_chunk_result` verwirft jeden Eintrag mit `page_count <= 0` — eine
  vollständig leere Antwort ist nie ein gültiger Treffer, unabhängig vom erwarteten Umfang.
- `DocumentAiAdapter.process()` vergleicht zusätzlich `len(cached)` mit der tatsächlichen
  Länge des Blocks, den es gerade bearbeitet — nur die Engine-Schleife kennt diese Länge. Ein
  bewahrter Block mit zu wenigen (aber mehr als null) Seiten fällt so ebenfalls durch.

Ein nicht passender Eintrag gilt als **nicht vorhanden**, nicht als Fehler: Der Block wird
regulär neu erkannt und das (nun korrekte) Ergebnis überschreibt den alten Eintrag per Upsert.

## Fehlertoleranz

`SafeChunkStore` verschluckt jeden Fehler des Ablageorts — beim Lesen wie beim Schreiben. Die
Pipeline hüllt den Store bereits damit ein, **bevor** sie ihn an den Adapter übergibt; der
Adapter selbst bleibt undefensiv und verlässt sich darauf (siehe
[ocr-adapter.md](ocr-adapter.md)). Die Verhältnismäßigkeit ist eindeutig: Ein nicht bewahrter
Block kostet einen erneuten Aufruf, ein wegen des Zwischenspeichers abgebrochener Lauf kostet
alle. Eine unlesbare oder nicht deutbare Zeile wird behandelt, als gäbe es sie nicht
(`load_chunk_result` fängt den Rückbaufehler ab und protokolliert ihn).

Der Rückbau in `ocr_pages_from_payload` prüft Feld für Feld und wirft bei allem, was nicht
passt. Eine generische Deserialisierung würde halbe Objekte durchlassen, deren Fehler erst im
fertigen PDF auffiele.

## Format

JSON-Text, unkomprimiert. Komprimierung spräche rechnerisch für sich (grob zwei Drittel),
aber die Einträge sind kurzlebig und lesbarer Text ist bei einem Zwischenspeicher, den man im
Fehlerfall ansehen will, mehr wert. Falls die Datenbankgröße je auffällt, ist die Umstellung
auf ein komprimiertes Blob eine lokale Änderung an `store_chunk_result` und
`load_chunk_result`.

Kein Pickle: Es würde beliebige Objekte wiederherstellen und wäre an die Python-Version
gebunden — für Daten, die einen Neustart und womöglich ein Image-Update überdauern sollen,
die falsche Wahl.
