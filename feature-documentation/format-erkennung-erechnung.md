# Format-Routing & E-Rechnungs-Bypass

**Modul:** `app/detection.py` · **Funktion:** `detect(path) -> Detection`

Rein deterministische Erkennung (keine KI/OCR), PRD §4.4.

## Format-Routing nach Endung

- `.pdf` → `PDF` (oder `ERECHNUNG_PDF`, siehe unten)
- `.tif/.tiff` → `TIFF`
- `.jpg/.jpeg/.png/.bmp/.webp` → `IMAGE`
- `.xml` → `ERECHNUNG_XML` (nur dann weiterverarbeitet, wenn als E-Rechnung erkannt)

`is_supported(path)` / `SUPPORTED_SUFFIXES` gaten den Watch-Folder-Intake.

## E-Rechnungs-Erkennung

- **XRechnung (XML):** `is_erechnung_xml` liest nur das Root-Element (streamend via
  `iterparse`). Akzeptiert namespace-agnostisch die Lokalnamen `Invoice` (UBL) bzw.
  `CrossIndustryInvoice` (UN/CEFACT CII).
- **ZUGFeRD/Factur-X (PDF):** `pdf_has_embedded_invoice` prüft eingebettete Dateien
  (`factur-x.xml`, `zugferd-invoice.xml`, `xrechnung.xml`, `cii.xml`) sowie XMP-Metadaten auf
  `factur-x`/`zugferd`.

## Verhalten

Erkannte E-Rechnungen nehmen den Bypass-Weg in der Pipeline: **unverändert** nach `consume`,
Original nach `processed`, Status `skipped_erechnung`. **Keine** OCR, **keine** Umbenennung,
**keine** Paperless-Tags (PRD §3.1).
