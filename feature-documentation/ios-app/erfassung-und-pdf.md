# Erfassung und PDF-Erzeugung — iOS-App

**Module:** `ios/Lector/UI/Erfassung/` (`ErfassungsAnsicht`, `DokumentScanner`, `ErfassungsModell`), `ios/Shared/Capture/` (`PDFErzeuger`, `Upload`), `app/api.py` (`POST /api/v1/upload`)

## Zweck

Die App bietet drei Wege, um Belege zu erfassen und hochzuladen:

1. **Scanner:** `VNDocumentCameraViewController` — mehrseitige Scans mit Kantenerkennung
2. **Fotoauswahl:** `PhotosPicker` — Bilder aus der Mediathek des Geräts (alle Formate)
3. **Teilen-Menü:** Share Extension — Dateien, die aus Mail, Safari, Dateien-App geteilt werden

Die Scanner-Bilder und Fotos werden **auf dem Gerät zu einem einzigen PDF zusammengefasst** und als eine Datei hochgeladen. Jedes Bild wird eine Seite; mehrere Bilder ergeben mehrere Seiten, aber einen Vorgang.

## Menü „Beleg übergeben"

In der `HauptAnsicht` (Tab-Navigation) steht ein Menü mit dem Titel „Beleg übergeben":

```
┌─────────────────────┐
│ + Beleg übergeben   │
├─────────────────────┤
│ Beleg scannen       │
│ Aus Mediathek       │
└─────────────────────┘
```

Ein Tap auf „Beleg scannen" öffnet den Scanner, ein Tap auf „Aus Mediathek" öffnet den Photo-Picker.

## Scanner (`VNDocumentCameraViewController`)

### Verfügbarkeit

Die `VNDocumentCameraViewController` ist **nicht auf allen Geräten verfügbar**. Die App prüft vor Anzeige des Menu-Eintrags mit `VNDocumentCameraViewController.isSupported`. Ist der Scanner nicht verfügbar (z. B. ältere iPad-Modelle ohne Kamera), wird der Eintrag „Beleg scannen" nicht angezeigt.

### Seiten scannen

Der Scanner bietet:

- **Mehrere Seiten:** Bilder hintereinander erfassen, jedes Bild wird eine Seite.
- **Automatische Kantenerkennung:** Vision Framework erkennt Dokumentkanten und führt perspektivische Korrektur durch.
- **Speichern/Abbrechen:** Am Ende kann die Person die Seiten speichern oder verwerfen.

Nach dem Speichern landen die Bilder im `ErfassungsModell`.

## Fotoauswahl (`PhotosPicker`)

Die App nutzt `PhotosPicker` (iOS 16+) aus SwiftUI. Die Person kann **mehrere Fotos** gleichzeitig wählen. Die App akzeptiert alle Bildformate, die iOS anbietet:

- JPEG, PNG, HEIF/HEIC, WebP, etc.
- Auch HEIC-Fotos (häufig auf neueren iPhones) werden akzeptiert und später zu JPEG konvertiert.

## ErfassungsModell

### Zustände

Das Modell verwaltet einen Zustandsautomat:

| Zustand | Beschreibung | Buttons |
|---|---|---|
| `bereit` | Wartet auf Bilder vom Scanner oder Picker | (Scanner/Picker können getappt werden) |
| `vorbereiten` | Bilder werden zu PDF verarbeitet | „Abbrechen" |
| `senden` | PDF wird hochgeladen | „Abbrechen" |
| `übergeben` | Upload erfolgreich, PDF wird verarbeitet | — |
| `abgewiesen` | Upload abgelehnt (z. B. unsupported format) | „Erneut senden", „Schließen" |
| `fehlgeschlagen` | Upload gescheitert (Netz, 5xx, etc.) | „Erneut senden", „Schließen" |

### Erneut senden

Wenn der Upload fehlschlägt, bietet das Modell „Erneut senden": Die PDF wird nochmals hochgeladen (über `APIClient.hochladen`). Dies funktioniert auch im Flugmodus-Szenario: Fehler → Person wartet → Flugmodus aus → „Erneut senden" tippt.

### Aufräumen beim Schließen

Das Modell speichert die PDF temporär auf der Festplatte (in einem Arbeitsordner). Wenn die Ansicht geschlossen wird, wird dieser Ordner gelöscht. Dies verhindert, dass sich eine alte PDF bei jedem Durchlauf auf dem Gerät sammelt.

### Keine Warteschlange

Es gibt **keine Warteschlange**: Wenn die Upload-Ansicht geschlossen wird (erfolgreich, fehlgeschlagen oder abgebrochen), wird die PDF verworfen. Es gibt keinen Background-Task, der später nachtragen würde. Die Spec verlangt explizit: „Ohne Verbindung wird nichts zwischengespeichert."

## PDFErzeuger

### JPEG-Kompression und Größe

Alle Bilder (egal ob von Scanner, Picker oder Share Extension) werden als JPEG mit Qualität **0,85** in das PDF eingebettet:

```swift
let jpegData = uiImage.jpegData(compressionQuality: 0.85)
```

Dies ist ein Kompromiss zwischen Bild-qualität und Dateigröße. Bei OCR braucht es keine absolut perfekte Qualität, und 0,85 JPEG ist für die Texterkennung ausreichend.

### Skalierung auf max. 3000 px

Ist die lange Kante eines Bildes größer als 3000 Pixel, wird das Bild vor der JPEG-Konvertierung auf 3000 px skaliert:

```
Originalbild: 4000 × 3000 px
→ Skaliert auf: 3000 × 2250 px
```

Dadurch:

- **OCR braucht nicht mehr:** 3000 px ist ausreichend für die Texterkennung durch Document AI.
- **Dateigröße klein:** Ein Kassenbon mit 3000 px bleibt unter ~1 MB pro Seite.
- **Speicher beim Rendern:** Beim Umwandeln von PDF-Seiten zurück zu Bildern (z. B. für Vorverarbeitung) brauchts weniger RAM.

### EXIF-Orientierung

Die App berücksichtigt die EXIF-Orientierung von Fotos aus der Mediathek. Ein Foto mit Orientierung `3` (180°-Drehung) wird korrekt gedreht, bevor es ins PDF kommt. Ein Foto ohne EXIF wird als ist übernommen.

### Alphakanal auf Weiß

Falls ein Bild einen transparenten Alphakanal hat (z. B. PNG mit Transparenz), wird dieser **auf Weiß konvertiert**:

```
Transparente Pixel → Weiße Pixel
```

Dies verhindert schwarze Flecken oder Überraschungen beim Rendern. Das ist selten (der Scanner produziert keine Transparenz), kann aber bei Mediathek-Bildern vorkommen.

### Speicher pro Seite

Eine Seite im PDF belegt abhängig von der Größe des eingebetteten JPEG:

- **Typisch (A4-Größe, 0,85 JPEG):** 50–200 KB pro Seite.
- **Kassenbon/schmales Foto:** 20–50 KB.
- **Großes Foto (3000 × 3000):** bis ~300 KB.

Die App prüft vor dem Hochladen nicht, ob das PDF in den Speicher des Geräts passt (Spec verlangt maximal 20 Dateien, nicht dass PDF <X MB). Im Fall von RAM-Limits wirft das Rendering einen Fehler, den das `ErfassungsModell` als `fehlgeschlagen` anzeigt.

### Dateiname

Das PDF wird mit dem Namen `Scan JJJJ-MM-TT HHMMSS.pdf` erzeugt, in der **Ortszeit des Geräts**:

```
Beispiel: "Scan 2026-10-12 123045.pdf"
         (12. Oktober 2026, 12:30:45 Uhr Gerätezeit)
```

Der Name wird nicht ausgewertet (Lector macht keine Klassifizierung). Er ist nur eine lesbare Bezeichnung für den Upload und die temporäre Ablage auf dem Gerät.

### UIGraphicsPDFRenderer

Die PDF wird mit `UIGraphicsPDFRenderer` erzeugt (native iOS-API). Jedes Bild wird eine Seite; die Seitengröße folgt dem Seitenverhältnis des Bildes. Beispiel:

- Bild 4:3 (z. B. 3000 × 2250) → Seite im 4:3-Format
- Bild 16:9 (z. B. 3000 × 1687) → Seite im 16:9-Format
- Quadratisch (z. B. 3000 × 3000) → Quadratische Seite

Dies verhindert unerwünschte Verformung oder Ränder beim Rendering. Der Server hat beim Sandwich-PDF-Bau keine Überraschungen.

## Upload-Baustein `APIClient.hochladen`

### Multipart gestreamt

Das PDF wird als Multipart-Request hochgeladen, nicht vollständig in den RAM geladen:

```
POST /api/v1/upload
Content-Type: multipart/form-data

----boundary123
Content-Disposition: form-data; name="files"; filename="Scan 2026-10-12 123045.pdf"
Content-Type: application/pdf

<PDF-Binärdaten aus Temp-Datei gestreamt>
----boundary123--
```

Dies ist wichtig für große PDFs (mehrere Seiten) — die App lädt das Ergebnis direkt aus der temporären Datei auf der Festplatte, nicht über einen Speicher-Puffer.

### Eine Datei je Anfrage

Die App sendet **pro Upload genau eine Datei**. Der `files`-Parameter trägt exakt ein Feld mit einer Datei. Dies unterscheidet sich von der Web-UI, die mehrere Dateien gleichzeitig akzeptiert.

Grund: Im Kontext der iOS-App ist es klarer, eine Beleg-Aktion = eine PDF-Datei zu machen.

### Ablehnung = Ergebnis

Lehnt der Server die Datei ab (z. B. `"accepted": false` mit `"reason": "unsupported_format"`), wird dies im `ErfassungsModell` als Fehlerzu „abgewiesen" interpretiert. Der `APIClient` wirft keinen Exception; der HTTP-Status ist `200`, und das `results`-Array trägt den Ablehnungsgrund.

Das `ErfassungsModell` zeigt dann einen aussagekräftigen Hinweis wie „Dateiformat wird nicht unterstützt".

## Begradigung durch VisionKit und Deskew

Der **Scanner** nutzt `VNDocumentCameraViewController`, das VisionKit-Framework. Dieses führt automatisch Perspektiv-Korrektur durch und richtet schiefe Bilder grad.

**Nach dem Upload** führt Lector noch einmal einen lokalen Deskew-Schritt durch (wenn `PREPROCESS_DESKEW=true`). Ein bereits gerades Bild ändert sich dabei nicht nennenswert — der Deskew-Algorithmus erkennt, dass das Bild schon eben ist, und lässt es unangetastet. Daher ist es sicher, beide aktiv zu lassen.

Im Abnahmetest wird geprüft, dass ein mehrseitiger Scan durchsuchbar ist und die Begradigung unauffällig wirkt.

## Code-Orte

| Datei | Rolle |
|---|---|
| `ios/Lector/UI/Erfassung/ErfassungsAnsicht.swift` | Ansicht: Menü, States, Upload-Fortschritt, Buttons |
| `ios/Lector/UI/Erfassung/DokumentScanner.swift` | `UIViewControllerRepresentable`-Wrapper um `VNDocumentCameraViewController` |
| `ios/Lector/UI/Erfassung/ErfassungsModell.swift` | Zustandsautomat, Bildverwaltung, Temp-Aufräumen, Fehlerbehandlung |
| `ios/Shared/Capture/PDFErzeuger.swift` | JPEG-Konvertierung, Skalierung auf 3000 px, EXIF, Alphakanal, `UIGraphicsPDFRenderer`, Namensvergabe |
| `ios/Shared/Network/Upload.swift` | Multipart-Streaming aus Temp-Datei, eine Datei je Anfrage, Ablehnung als Ergebnis |
| `app/api.py` | Route `POST /api/v1/upload` |
