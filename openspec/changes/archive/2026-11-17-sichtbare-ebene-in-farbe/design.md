# Design

## Context

`_handle_ocr` (`app/pipeline.py`) rastert die Seiten über `extract_pages` als RGB und ruft
`preprocess_page` je Seite auf. Daraus entsteht **eine** Liste `preprocessed`, die zweimal
verwendet wird: als Eingabe für `adapter.process(...)` und als Bildliste für
`build_sandwich_pdf(...)`.

`preprocess_page` (`app/preprocessing.py`) arbeitet in zwei Schritten:

1. `deskew(img)`: Winkel aus Graustufen und Otsu, dann wird das **Eingangsbild** gedreht. Ein
   RGB-Bild bleibt RGB.
2. `enhance_contrast(img)`: `convert("L")` und CLAHE. Hier geht die Farbe verloren.

`build_sandwich_pdf` (`app/pdfbuilder.py`) setzt die Seitengröße auf die Bildpixel und rechnet
die normalisierten Token-Koordinaten (0..1) auf diese Fläche um. Der Textlayer sitzt also nur
dann richtig, wenn die sichtbare Ebene dieselbe Geometrie hat wie das Bild, das Document AI
gesehen hat.

`chunk_fingerprint` enthält die beiden `PREPROCESS_*`-Schalter und `PDF_RENDER_DPI`, aber
keine Bildinhalte.

## Goals / Non-Goals

**Goals:**
- Die sichtbare Ebene behält die Farbe, die OCR-Eingabe bleibt bitgleich zu heute.
- Die Geometrie ist für beide Bilder garantiert gleich, weil sie aus einem einzigen
  Drehschritt stammt.
- Die Änderung bleibt auf Aufbereitung und Pipeline-Verdrahtung begrenzt. Der Adapter und der
  PDF-Bau bleiben unverändert.

**Non-Goals:**
- Keine Änderung an der Bildkodierung im PDF (Kompression, Auflösung).
- Keine farberhaltende Kontrastanhebung der sichtbaren Ebene.
- Keine Nachverarbeitung bereits übergebener Dokumente.
- Kein neuer Konfigurationsschalter.

## Decisions

**D1: `preprocess_page` liefert ein Paar statt eines Bildes.**
Rückgabe als kleiner, benannter Typ, z. B. `PreparedPage(visible: Image, ocr: Image)` (ein
`NamedTuple` oder eine `dataclass(frozen=True)`). Ablauf je Seite:
`base = deskew(img) if PREPROCESS_DESKEW else img`, dann `visible = base` und
`ocr = enhance_contrast(base) if PREPROCESS_CONTRAST else base`.
Weil `enhance_contrast` nur Pixelwerte ändert und nicht die Geometrie, sind beide Bilder
deckungsgleich.
Verworfene Alternative: Deskew zweimal laufen lassen (einmal auf Farbe, einmal auf Grau). Die
Winkelschätzung arbeitet auf Graustufen und wäre zwar meist gleich, die Interpolation beim
Drehen aber nicht zwingend. Ein einziger Drehschritt ist die einfache Garantie.
Verworfene Alternative: Den Drehwinkel zurückgeben und das Originalbild im Pipeline-Code
drehen. Das verteilt die Aufbereitungslogik auf zwei Module.

**D2: Die Pipeline trennt die Listen direkt nach der Aufbereitung.**
`prepared = [preprocess_page(...)]`, dann `ocr_images = [p.ocr for p in prepared]` für
`adapter.process` und `visible_images = [p.visible for p in prepared]` für
`build_sandwich_pdf`. Der Adapter-Vertrag (`list[Image]`) bleibt gleich, die Engine-
Unabhängigkeit aus der Spec ebenfalls.

**D3: `chunk_fingerprint` bleibt unverändert.**
Die OCR-Eingabe ist bitgleich zu heute, bewahrte Blöcke passen also weiter. Den Fingerabdruck
zu ändern würde laufende Wiederholversuche ohne Grund neu bezahlen lassen. Der vorhandene Test
`test_changed_preprocessing_invalidates_the_cache` bleibt gültig.

**D4: Speicherbedarf während der Verarbeitung.**
Bei aktiver Kontrastanpassung liegen pro Seite zwei Bilder im Speicher: das RGB-Bild und ein
Graustufenbild (ein Drittel davon). Heute liegt das RGB-Original bis zum Ende der Aufbereitung
ebenfalls im Speicher (`images`). Der Mehrbedarf beträgt also etwa ein Drittel des
Rasterspeichers, bei der Seitenobergrenze von 100 Seiten vertretbar. Die Liste `images` kann
nach der Aufbereitung freigegeben werden, falls das in der Umsetzung ohne Umbau geht.

## Risks / Trade-offs

- [Größere Ergebnis-PDFs] reportlab bettet das Bild verlustfrei (Flate) ein. Eine farbige
  Seite mit 200 DPI und Scanrauschen komprimiert deutlich schlechter als eine graue. Je nach
  Vorlage kann eine Seite mehrere MB groß werden. → In der Abnahme an drei bis vier echten
  Scans (farbig, grau, Foto vom Handy) die Größe vorher/nachher messen und in `PROGRESS.md`
  festhalten. Fällt der Zuwachs zu groß aus, folgt ein eigener Change zur Kodierung der
  sichtbaren Ebene (z. B. JPEG mit fester Qualität).
- [Graustufen-Eingang wird als RGB eingebettet] Wie bisher wandelt `build_sandwich_pdf` jede
  Seite nach RGB. Für reine Graustufenvorlagen ist das Verschwendung, ändert aber nichts am
  Aussehen. → Bewusst nicht Teil dieses Changes, gehört zur Kodierungsfrage oben.
- [Weniger Kontrast im Archivbild] Blasse Scans sehen in Paperless künftig blasser aus als
  bisher. → Gewollt: Die sichtbare Ebene zeigt das Original. Die Suche hängt am Textlayer und
  nicht am Bildkontrast.

## Migration Plan

- Kein Datenbank- oder Konfigurationsschritt. Neues Image bauen und auf dem NAS ausrollen.
- Ab dem Rollout kommen neue Dokumente in Farbe an. Bestehende Dokumente in Paperless bleiben
  grau.
- Rückweg: auf das vorherige Image zurückgehen. Bewahrte Blöcke bleiben in beide Richtungen
  gültig (D3).
