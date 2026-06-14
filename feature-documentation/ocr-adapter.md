# OCR-Adapter-Interface & Document AI

**Paket:** `app/ocr/` — `base.py` (Interface), `documentai.py` (Engine), `__init__.py` (Factory)

## Interface (`OcrAdapter`)

Engine-unabhängig (PRD §4.4). Vertrag:

- `page_limit: int` — maximale Seitenzahl pro Online-Request der Engine.
- `process(pages, progress) -> OcrResult` — erkennt Text + Bounding-Boxes für alle Seiten,
  **chunkt intern** bis `page_limit` und meldet über `progress(processed_pages)` den
  kumulierten Fortschritt.

`OcrResult` enthält pro Seite (`OcrPage`) eine Liste `OcrToken` mit Text und **normalisierten**
Box-Koordinaten (0..1, Ursprung oben-links) — engine-unabhängig.

Hilfen in `base.py`: `chunked(items, size)` und `RateLimiter` (seitenbasiertes Throttling).

`get_adapter(settings)` wählt anhand `OCR_PROVIDER` die Implementierung — Einstiegspunkt für
spätere Engines (Cloud Vision, AWS Textract).

## Document-AI-Adapter

- Region-Endpoint `<DOCAI_LOCATION>-documentai.googleapis.com`; Client wird **lazy** beim
  ersten Aufruf erzeugt (Start ohne Credentials möglich).
- `page_limit` = `min(CHUNK_SIZE_PAGES, 15)` (Online-Limit der Engine).
- Pro Block: Seiten → mehrseitiges TIFF (in-memory) → `process_document`. Antwort wird über die
  **reine** Funktion `document_to_pages(document, page_offset)` in `OcrPage`/`OcrToken`
  übersetzt (duck-typed, daher ohne echte API testbar).
- **Throttling:** `RateLimiter(DOCAI_MAX_PAGES_PER_MINUTE)` hält vor jedem Block die
  Durchschnittsrate ein (PRD offene Frage 3).
