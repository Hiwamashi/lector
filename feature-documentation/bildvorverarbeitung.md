# Seitenextraktion & Bildvorverarbeitung

**Module:** `app/pages.py` (Extraktion), `app/preprocessing.py` (Vorverarbeitung)

## Seitenextraktion (`extract_pages`)

Wandelt die Eingangsdatei in eine Liste von PIL-Bildern (eine pro Seite):

- **PDF:** `pypdfium2`-Rendering bei `PDF_RENDER_DPI` (200 DPI).
- **TIFF:** mehrseitig via `PIL.ImageSequence`.
- **Bild:** einseitig.

## Vorverarbeitung pro Seite (`preprocess_page`)

Schaltbar über die `PREPROCESS_*`-Flags (PRD §3.1). Reihenfolge: Auto-Rotate → Deskew →
Kontrast.

- **Deskew:** Schieflagenwinkel über `cv2.minAreaRect` der Textpixel (Otsu-Schwelle).
  Hinweis: `np.where` liefert (row, col); `minAreaRect` interpretiert sie als (x, y), daher
  wird mit **negativem** Winkel zurückgedreht (sonst Korrektur in falsche Richtung — wurde per
  Test abgesichert).
- **Auto-Rotate:** wählt aus 0/90/180/270° die Drehung mit der stärksten **horizontalen
  Bänderung** (Varianz des zeilenweisen Tintenanteils). Korrigiert zuverlässig
  Hoch-/Querformat-Verdrehungen; eine reine 180°-Drehung lässt sich ohne semantische
  Texterkennung nicht unterscheiden (dokumentierte Grenze).
- **Kontrast:** Graustufen + CLAHE (lokaler Kontrastausgleich).

Die vorverarbeiteten Bilder gehen sowohl an die OCR-Engine als auch als sichtbare Ebene in das
Sandwich-PDF.
