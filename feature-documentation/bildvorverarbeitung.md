# Seitenextraktion & Bildvorverarbeitung

**Module:** `app/pages.py` (Extraktion), `app/preprocessing.py` (Vorverarbeitung)

## Seitenextraktion (`extract_pages`)

Wandelt die Eingangsdatei in eine Liste von PIL-Bildern (eine pro Seite):

- **PDF:** `pypdfium2`-Rendering bei `PDF_RENDER_DPI` (200 DPI).
- **TIFF:** mehrseitig via `PIL.ImageSequence`.
- **Bild:** einseitig.

## Vorverarbeitung pro Seite (`preprocess_page`)

Schaltbar über die `PREPROCESS_*`-Flags (PRD §3.1). Reihenfolge: Deskew → Kontrast.

- **Deskew:** Schieflagenwinkel über `cv2.minAreaRect` der Textpixel (Otsu-Schwelle).
  Hinweis: `np.where` liefert (row, col); `minAreaRect` interpretiert sie als (x, y), daher
  wird mit **negativem** Winkel zurückgedreht (sonst Korrektur in falsche Richtung — wurde per
  Test abgesichert).
- **Kontrast:** Graustufen + CLAHE (lokaler Kontrastausgleich).

Die vorverarbeiteten Bilder gehen sowohl an die OCR-Engine als auch als sichtbare Ebene in das
Sandwich-PDF.

## Orientierung: kein lokales Auto-Rotate (bewusste Entscheidung)

Früher gab es einen `autorotate()`-Schritt, der aus 0/90/180/270° die Drehung mit der
stärksten horizontalen Bänderung (Varianz der Zeilensummen) wählte. Dieser Schritt wurde
**entfernt**, weil er korrekt ausgerichtete Seiten zufällig verdrehte:

- Die Varianz der Zeilensummen ist für eine Seite und ihre **180°-Drehung mathematisch
  identisch** (die Zeilenreihenfolge wird nur umgekehrt). Ebenso für 90° vs. 270°.
- Die Entscheidung „aufrecht vs. Kopfstand" fiel damit allein über den **Fließkomma-Rundungsfehler
  im letzten Bit** — also praktisch per Münzwurf. In einer Stichprobe von 236 Seiten wurden so
  ~22 % gedreht (davon viele auf 180° = Kopfstand).
- Das Signal „horizontale Bänderung = aufrecht" trennt zudem Hoch-/Querformat bei Tabellen,
  Formularen und Rechnungen unzuverlässig.

**Stattdessen:** Die Seitenorientierung übernimmt die OCR-Engine (Document AI), die im
OCR-Schritt robust gegenüber gedrehten Seiten ist. Die per `pypdfium2` gerenderten Quellseiten
sind ohnehin bereits korrekt ausgerichtet (PDF-`/Rotate` wird beim Rendern berücksichtigt). Es
gibt daher **kein** `PREPROCESS_AUTOROTATE`-Flag mehr.
