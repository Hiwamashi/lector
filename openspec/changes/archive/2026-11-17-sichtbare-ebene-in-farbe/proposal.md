# Proposal

## Why

Jedes Dokument auf dem OCR-Weg kommt in Graustufen bei Paperless an. Grund: Die Seite
wird einmal aufbereitet (Schieflage, dann Graustufen mit CLAHE), und dieses eine Bild
geht sowohl an Document AI als auch als sichtbare Ebene in das Sandwich-PDF. Die
Kontrastanhebung hilft der Texterkennung, im Archiv kostet sie aber die Farbe: Stempel,
farbige Logos, blaue Unterschriften und Textmarker gehen verloren. Kontrast soll nur die
Maschine sehen, nicht der Mensch.

## What Changes

- Die Aufbereitung liefert pro Seite zwei Bilder statt einem:
  - **Sichtbare Ebene:** das Originalbild in Farbe, nur in der Schieflage korrigiert.
  - **Eingabe für die Texterkennung:** dasselbe korrigierte Bild, zusätzlich in
    Graustufen mit Kontrastanhebung, wenn `PREPROCESS_CONTRAST` aktiv ist.
- Beide Bilder stammen aus **einer** Schieflagenkorrektur, haben also dieselbe Geometrie.
  Der unsichtbare Textlayer sitzt dadurch weiter genau über dem sichtbaren Text.
- Die Eingabe für Document AI ändert sich nicht. Bewahrte Blockergebnisse bleiben gültig,
  und die Erkennungsqualität bleibt gleich.
- `PREPROCESS_CONTRAST` wirkt nur noch auf die OCR-Eingabe. `PREPROCESS_DESKEW` wirkt
  weiter auf beide Bilder.
- Ein Eingangsdokument in Graustufen oder Schwarz-Weiß bleibt in seiner Art erhalten. Es
  wird nicht künstlich eingefärbt, nur als RGB eingebettet wie bisher.
- Bereits an Paperless übergebene Dokumente bleiben unverändert. Eine Nachverarbeitung ist
  nicht vorgesehen.
- Keine Änderung an der Kodierung der sichtbaren Ebene (weiter verlustfrei). Farbige
  Seiten machen das Ergebnis-PDF größer. Eine verlustbehaftete Kodierung wäre eine eigene
  Entscheidung (siehe design.md, Risiken).

## Capabilities

### New Capabilities

### Modified Capabilities
- `ocr-veredelung`: Die Anforderung zur Seitenaufbereitung trennt künftig die OCR-Eingabe
  von der sichtbaren Ebene. Die Anforderung zum durchsuchbaren PDF legt fest, dass die
  sichtbare Ebene die Farbe des Originals behält und nur in der Schieflage korrigiert ist.

## Impact

- `app/preprocessing.py`: `preprocess_page` liefert ein Bildpaar (sichtbar / OCR).
- `app/pipeline.py`: `_handle_ocr` gibt die OCR-Bilder an den Adapter und die sichtbaren
  Bilder an `build_sandwich_pdf`. `chunk_fingerprint` bleibt unverändert.
- `app/pdfbuilder.py`: keine Logikänderung, nur Docstring („vorverarbeitetes Bild").
- Tests: `tests/test_preprocessing.py`, `tests/test_pipeline.py` (Farbe in der Ausgabe,
  OCR-Eingabe in Graustufen, Geometrie gleich).
- Doku: `feature-documentation/bildvorverarbeitung.md`,
  `feature-documentation/sandwich-pdf.md`, `prd/PROGRESS.md` (bewusste Abweichung vom PRD
  §3.1 „vorverarbeitetes Originalbild als sichtbare Ebene"), `CLAUDE.md` (Architektur-
  Eckpunkt Sandwich-PDF).
- Keine neue Konfiguration, keine Datenbankmigration, keine Änderung an UI oder API.
- Größere Ergebnis-PDFs bei farbigen Vorlagen und dadurch mehr Speicherbedarf in Paperless.
