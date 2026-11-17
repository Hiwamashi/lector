# Seitenextraktion & Bildvorverarbeitung

**Module:** `app/pages.py` (Extraktion), `app/preprocessing.py` (Vorverarbeitung)

## Seitenextraktion (`extract_pages`)

Wandelt die Eingangsdatei in eine Liste von PIL-Bildern (eine pro Seite):

- **PDF:** `pypdfium2`-Rendering bei `PDF_RENDER_DPI` (200 DPI).
- **TIFF:** mehrseitig via `PIL.ImageSequence`.
- **Bild:** einseitig.

## Vorverarbeitung pro Seite (`preprocess_page`)

Schaltbar über die `PREPROCESS_*`-Flags (PRD §3.1). `preprocess_page` liefert pro Seite ein
Bildpaar `PreparedPage(visible, ocr)` (`app/preprocessing.py`). Reihenfolge: Deskew → Bildpaar.

- **Deskew** (`PREPROCESS_DESKEW`): Schieflagenwinkel über `cv2.minAreaRect` der Textpixel
  (Otsu-Schwelle). Läuft **einmal** auf dem Farbbild; das Ergebnis gilt für beide Bilder.
  Hinweis: `np.where` liefert (row, col); `minAreaRect` interpretiert sie als (x, y), daher
  wird mit **negativem** Winkel zurückgedreht (sonst Korrektur in falsche Richtung — wurde per
  Test abgesichert).
- **`visible`** (sichtbare Ebene): das schieflagenkorrigierte Originalbild **in Farbe**. Es geht
  als sichtbare Ebene in das Sandwich-PDF (`build_sandwich_pdf`).
- **`ocr`** (Eingabe für die Texterkennung): bei `PREPROCESS_CONTRAST` Graustufen + CLAHE
  (lokaler Kontrastausgleich) auf dem korrigierten Bild. Ohne den Schalter ist `ocr` dasselbe
  Farbbild wie `visible`. Es geht nur an die OCR-Engine.

**Warum zwei Bilder:** Kontrastanhebung hilft der Texterkennung, kostet im Archivbild aber die
Farben (Stempel, Logos, Unterschriften, Textmarker). Das Archivbild soll die Farben des
Originals behalten; der Kontrast ist für die Maschine gedacht.

**Geometrie:** Beide Bilder stammen aus demselben Drehschritt und haben dieselben Abmessungen.
CLAHE ändert nur Pixelwerte, nicht die Geometrie. Der unsichtbare Textlayer aus den
OCR-Koordinaten liegt daher deckungsgleich über der sichtbaren Ebene.

**Auswirkung auf die Flags:** `PREPROCESS_CONTRAST` wirkt nur auf die OCR-Eingabe.
`PREPROCESS_DESKEW` wirkt auf beide Bilder. Der Chunk-Fingerabdruck (`chunk_fingerprint`) bleibt
unverändert, weil die OCR-Eingabe bitgleich zu vorher ist; bewahrte Blockergebnisse bleiben
gültig.

**Speicher:** Bei aktiver Kontrastanpassung liegen pro Seite zwei Bilder im Speicher (Farbe und
Graustufen). Die Rohseiten werden nach der Aufbereitung in `_handle_ocr` freigegeben.

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
