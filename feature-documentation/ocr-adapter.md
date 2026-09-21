# OCR-Adapter-Interface & Document AI

**Paket:** `app/ocr/` — `base.py` (Interface), `documentai.py` (Engine), `__init__.py` (Factory)

## Interface (`OcrAdapter`)

Engine-unabhängig (PRD §4.4). Vertrag:

- `page_limit: int` — maximale Seitenzahl pro Online-Request der Engine.
- `process(pages, progress, store) -> OcrResult` — erkennt Text + Bounding-Boxes für alle
  Seiten, **chunkt intern** bis `page_limit` und meldet über
  `progress(processed_pages, from_cache)` den kumulierten Fortschritt. `store` ist optional
  (siehe unten); `from_cache` hat einen Vorgabewert, ein Aufruf mit nur der Seitenzahl trägt
  also weiterhin.

`OcrResult` enthält pro Seite (`OcrPage`) eine Liste `OcrToken` mit Text und **normalisierten**
Box-Koordinaten (0..1, Ursprung oben-links) — engine-unabhängig.

Hilfen in `base.py`: `chunked(items, size)`, `RateLimiter` (seitenbasiertes Throttling) und
`SafeChunkStore` (Fehlerhülle um den Zwischenspeicher).

### Was eine neue Engine erbt: der Zwischenspeicher

Ist `store` gesetzt, **muss** der Adapter vor jedem Block dort nachsehen
(`store.get(chunk_index)`) und einen Treffer verwenden, statt die Engine zu fragen; jeden
frisch erkannten Block legt er ab (`store.put(chunk_index, pages)`), **bevor** der nächste
beginnt. Damit kostet ein Wiederholversuch nur noch die fehlenden Blöcke.

Der Adapter kennt dabei nur **Blockindizes**. An welchen Vorgang und welche Bedingungen ein
Eintrag gebunden ist, entscheidet der Aufrufer, der den Ablageort fertig bestückt übergibt
(`_RepositoryChunkStore` in `app/pipeline.py`). Eine neue Engine erbt die Ersparnis also,
ohne etwas über Prüfsummen oder Einstellungen wissen zu müssen — sie muss nur die drei
Regeln oben einhalten und `store` in `SafeChunkStore` hüllen, damit ein Fehler des
Ablageorts den Lauf nicht abbricht.

Zwei Fallstricke, an denen der Document-AI-Adapter sich orientiert:

- **Die Drosselung gehört hinter das Nachsehen.** Sie schützt die Quota; ohne Anfrage gibt es
  nichts zu drosseln. Davor stehend würde sie einen Lauf aus dem Zwischenspeicher genauso
  langsam machen wie den ursprünglichen.
- **`progress` bekommt mitgeteilt, woher der Block kam.** Sonst sieht ein Lauf, der ein
  langes Dokument in Sekunden abschließt, wie eine Fehlfunktion aus.

Einzelheiten: [chunk-teilergebnisse.md](chunk-teilergebnisse.md).

`get_adapter(settings)` wählt anhand `OCR_PROVIDER` die Implementierung — Einstiegspunkt für
spätere Engines (Cloud Vision, AWS Textract).

## Document-AI-Adapter

- Region-Endpoint `<DOCAI_LOCATION>-documentai.googleapis.com`; Client wird **lazy** beim
  ersten Aufruf erzeugt (Start ohne Credentials möglich).
- `page_limit` = `min(CHUNK_SIZE_PAGES, 15)` (Online-Limit der Engine).
- Pro Block: Seiten → mehrseitiges TIFF (in-memory) → `process_document`. Antwort wird über die
  **reine** Funktion `document_to_pages(document, page_offset)` in `OcrPage`/`OcrToken`
  übersetzt (duck-typed, daher ohne echte API testbar).
- **Throttling:** `RateLimiter(DOCAI_MAX_PAGES_PER_MINUTE)` hält die Durchschnittsrate ein
  (PRD offene Frage 3) — angewandt nur auf Blöcke, die tatsächlich an die Engine gehen.
- **Zwischenspeicher:** vor jedem Block wird nachgesehen, jeder frisch erkannte Block wird
  abgelegt. Siehe [chunk-teilergebnisse.md](chunk-teilergebnisse.md).
