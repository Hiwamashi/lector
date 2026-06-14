# Durchsuchbares Sandwich-PDF

**Modul:** `app/pdfbuilder.py` · **Funktion:** `build_sandwich_pdf(images, ocr, output_path)`

Erzeugt ein PDF mit dem vorverarbeiteten Originalbild als sichtbare Ebene und einem
**unsichtbaren** Textlayer aus den OCR-Token (PRD §3.1). reportlab als PDF-Writer.

## Verfahren je Seite

1. PDF-Seitengröße = Bildpixel (1 px = 1 pt); Bild füllt die Seite.
2. Für jedes Token: Box aus normalisierten Koordinaten (0..1) auf Seitenpunkte abgebildet.
3. Text mit **Render-Modus 3** (unsichtbar) gezeichnet, Schriftgröße ≈ Box-Höhe, horizontal so
   skaliert (`setHorizScale`), dass der Text die Box-Breite ausfüllt → bessere Text-Markierung
   im Viewer.
4. PDF-Ursprung ist unten-links: y-Koordinaten werden gespiegelt, Baseline an der Box-Unterkante.

Seiten ohne OCR-Daten werden trotzdem (nur als Bild) gerendert. Bei leerer Bildliste wird ein
`ValueError` geworfen.

> Die Zuordnung Bild↔OCR erfolgt über `OcrPage.page_index`; das Chunking großer Dokumente wird
> dadurch transparent wieder zu **einem** Gesamt-PDF zusammengeführt.
