# Tasks

## 1. Aufbereitung liefert ein Bildpaar

- [x] 1.1 `app/preprocessing.py`: Typ `PreparedPage(visible, ocr)` einführen; `preprocess_page` dreht einmal (wenn `PREPROCESS_DESKEW`) und leitet daraus die sichtbare Ebene (unverändert) und die OCR-Eingabe ab (Graustufen + CLAHE, wenn `PREPROCESS_CONTRAST`) (D1). Modul-Docstring anpassen. Prüfen: Tests in `tests/test_preprocessing.py`: farbige Seite → `visible.mode == "RGB"` mit erhaltenen Farbwerten, `ocr.mode == "L"`; beide Schalter aus → beide Bilder gleich dem Original; schiefe Seite → `visible.size == ocr.size` und Restwinkel beider Bilder < 2°; `test_preprocess_page_respects_flags` auf das Paar umstellen.
- [x] 1.2 `feature-documentation/bildvorverarbeitung.md`: Abschnitt „Vorverarbeitung pro Seite" auf zwei Bilder umschreiben (Deskew für beide, Kontrast nur für die OCR, Grund: Archivbild in Farbe). Prüfen: Der Satz „Die vorverarbeiteten Bilder gehen sowohl an die OCR-Engine als auch als sichtbare Ebene …" ist ersetzt.

## 2. Pipeline verdrahtet die beiden Bilder getrennt

- [x] 2.1 `app/pipeline.py` `_handle_ocr`: OCR-Bilder an `adapter.process`, sichtbare Bilder an `build_sandwich_pdf` (D2); `chunk_fingerprint` unverändert lassen (D3); Liste `images` nach der Aufbereitung freigeben, wenn ohne Umbau möglich (D4). Prüfen: neuer Test in `tests/test_pipeline.py`: Ein Fake-Adapter zeichnet die Modi der empfangenen Bilder auf (`"L"` bei aktivem Kontrast), und ein farbiges Eingangsbild (z. B. PNG mit rotem Block) erscheint im Ergebnis-PDF farbig (eingebettetes Bild über `pypdf` auslesen und einen roten Pixel bzw. `/DeviceRGB` mit ungleichen Kanälen prüfen). Bestehende Cache- und Fingerprint-Tests bleiben grün.
- [x] 2.2 `app/pdfbuilder.py`: nur Docstring („vorverarbeitetes Bild" → „Seitenbild in Farbe, schieflagenkorrigiert"). `feature-documentation/sandwich-pdf.md` entsprechend anpassen. Prüfen: `uv run pytest tests/test_pdfbuilder.py` grün, Doku nennt die Farb-Ebene.

## 3. Projektdoku und Abschluss

- [x] 3.1 `prd/PROGRESS.md`: Abschnitt für den Change mit der bewussten Abweichung vom PRD §3.1 (sichtbare Ebene = Original in Farbe, nur Deskew; Kontrast nur für die OCR). `CLAUDE.md` Architektur-Eckpunkt „Sandwich-PDF" angleichen. Prüfen: beide Dateien nennen die Trennung.
- [x] 3.2 Gesamtprüfung: `uv run pytest`, `uv run ruff check .`, `graphify update .`, `openspec validate sichtbare-ebene-in-farbe` (ohne `--strict`: die Spec-Sprache ist Deutsch, „MUSS“ löst dort nur RFC-2119-Warnungen aus). Prüfen: Ausgaben ohne Fehler.
- [ ] 3.3 Größenvergleich: drei bis vier echte Scans (farbig, grau, Handyfoto) lokal mit altem und neuem Stand veredeln, Dateigrößen in `prd/PROGRESS.md` festhalten (Risiko „größere PDFs" aus design.md). Prüfen: Tabelle mit Vorher/Nachher steht in `PROGRESS.md`; bei deutlichem Zuwachs ist ein Folgepunkt „Kodierung der sichtbaren Ebene" notiert.

## Workflow follow-up

- Nach dem Rollout auf dem NAS ein farbiges Dokument einwerfen und in Paperless die Farbe sowie die Textmarkierung prüfen.
- Change archivieren, wenn die Abnahme erfolgt ist.
