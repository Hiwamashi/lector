# Spec Delta

## Purpose

Bestimmt für jedes aufgenommene Dokument deterministisch den Dateityp und ob eine E-Rechnung
vorliegt, und entscheidet damit zwischen unverändertem Durchreichen und OCR-Veredelung.

## ADDED Requirements

### Requirement: Erkennung erfolgt deterministisch ohne KI und ohne Texterkennung

Der Dienst MUSS den Dokumenttyp und die E-Rechnungs-Eigenschaft ausschließlich anhand von
Dateiendung, Dokumentstruktur und eingebetteten Metadaten bestimmen. Es DARF dafür weder eine
Texterkennung noch ein Sprachmodell noch eine Heuristik über den Dokumentinhalt herangezogen
werden.

#### Scenario: Erkennung läuft vor jeder Veredelung

- **WHEN** ein Vorgang in die Verarbeitung geht
- **THEN** wird der Typ bestimmt, bevor irgendein Inhalt an eine Texterkennung übergeben wird

### Requirement: XML mit Rechnungs-Wurzelelement gilt als E-Rechnung

Der Dienst MUSS eine XML-Datei als E-Rechnung einstufen, wenn ihr Wurzelelement `Invoice`
(UBL) oder `CrossIndustryInvoice` (UN/CEFACT CII) ist. Die Prüfung MUSS unabhängig vom
XML-Namensraum und von Groß-/Kleinschreibung erfolgen.

#### Scenario: XRechnung im UBL-Format

- **WHEN** eine XML-Datei mit Wurzelelement `Invoice` vorliegt
- **THEN** gilt sie als E-Rechnung vom Typ `erechnung_xml`

#### Scenario: XRechnung im CII-Format

- **WHEN** eine XML-Datei mit Wurzelelement `CrossIndustryInvoice` vorliegt
- **THEN** gilt sie als E-Rechnung vom Typ `erechnung_xml`

#### Scenario: XML ohne Rechnungs-Wurzelelement

- **WHEN** eine XML-Datei ein anderes Wurzelelement hat
- **THEN** wird sie als Typ `erechnung_xml` geführt, gilt aber **nicht** als E-Rechnung und
  geht damit nicht in den Bypass

#### Scenario: Unlesbare XML-Datei

- **WHEN** eine XML-Datei nicht geparst werden kann
- **THEN** gilt sie nicht als E-Rechnung

### Requirement: PDF mit eingebetteter Rechnung gilt als E-Rechnung

Der Dienst MUSS ein PDF als E-Rechnung einstufen, wenn es eine eingebettete Rechnungs-XML
unter einem bekannten Dateinamen enthält oder seine Metadaten eine ZUGFeRD-/Factur-X-Kennung
tragen.

#### Scenario: PDF mit bekannter eingebetteter Rechnungs-XML

- **WHEN** ein PDF eine eingebettete Datei mit einem der bekannten Rechnungs-Dateinamen enthält
- **THEN** gilt es als E-Rechnung vom Typ `erechnung_pdf`

#### Scenario: PDF mit ZUGFeRD-/Factur-X-Metadaten

- **WHEN** die Metadaten eines PDFs eine ZUGFeRD- oder Factur-X-Kennung enthalten
- **THEN** gilt es als E-Rechnung vom Typ `erechnung_pdf`

#### Scenario: Gewöhnliches PDF

- **WHEN** ein PDF weder eine bekannte eingebettete Rechnungs-XML noch eine entsprechende
  Metadaten-Kennung hat
- **THEN** gilt es als Typ `pdf` und geht in die OCR-Veredelung

#### Scenario: Beschädigtes PDF

- **WHEN** ein PDF für die Prüfung nicht geöffnet werden kann
- **THEN** gilt es nicht als E-Rechnung und geht in die OCR-Veredelung, wo ein Fehler der
  Fehlerbehandlung unterliegt

### Requirement: Bildhafte Formate gehen in die OCR-Veredelung

Der Dienst MUSS TIFF-Dateien als Typ `tiff` und Einzelbilder als Typ `image` einstufen. Eine
Datei, die den Eingang passiert hat, aber keiner bekannten Kategorie zugeordnet werden kann,
MUSS als Bild behandelt werden; scheitert ihre Verarbeitung, greift die reguläre
Fehlerbehandlung.

#### Scenario: TIFF-Datei

- **WHEN** eine Datei mit Endung `.tif` oder `.tiff` vorliegt
- **THEN** gilt sie als Typ `tiff`

#### Scenario: Einzelbild

- **WHEN** eine Datei mit Endung `.jpg`, `.jpeg`, `.png`, `.bmp` oder `.webp` vorliegt
- **THEN** gilt sie als Typ `image`

### Requirement: Das Erkennungsergebnis wird im Verlauf festgehalten

Der Dienst MUSS nach der Erkennung einen Verlaufseintrag anlegen, der den ermittelten Typ und
die E-Rechnungs-Eigenschaft benennt, und den Typ am Vorgang speichern.

#### Scenario: Erkennung abgeschlossen

- **WHEN** Typ und E-Rechnungs-Eigenschaft eines Dokuments bestimmt sind
- **THEN** ist der Typ am Vorgang gespeichert und ein Verlaufseintrag vom Typ `detected`
  benennt beides
