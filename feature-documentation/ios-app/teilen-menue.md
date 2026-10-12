# Teilen-Menü — iOS-App Share Extension

**Module:** `ios/LectorShare/` (`ShareViewController`, `TeilenAnsicht`, `ItemProviderQuelle`), `ios/Shared/Capture/` (`Formatweiche`, `TeilenVorbereitung`, `TeilenModell`), `app/api.py` (`POST /api/v1/upload`)

## Zweck

Die Share Extension (auch Teilen-Erweiterung) registriert die App als Ziel im System-Teilen-Menü von iOS. Eine Person kann aus Mail, Safari, Dateien-App oder anderen Apps Dateien an Lector teilen. Die Extension prüft, ob Serveradresse und Anmeldung vorhanden sind, konvertiert Bilder zu PDF (bei Bedarf), und lädt alles zu Lector hoch.

## Aktivierungsregel

Die Extension wird durch `NSExtensionActivationRule` in der `Info.plist` aktiviert. Sie verarbeitet:

- **PDF** (`public.pdf`) — byte-genau unverändert
- **XML** (`public.xml`) — byte-genau unverändert  
- **TIFF** (`public.tiff`) — byte-genau unverändert
- **Bilder** (`public.image`) — je nach Format (siehe Formatweiche)

Die Aktivierungsregel erlaubt **maximal 20 Dateien** gleichzeitig zu teilen. Werden mehr Dateien ausgewählt, wird das Menü nicht angezeigt. Dies ist eine Schutzmaßnahme, um nicht versehentlich hunderte Fotos hochzuladen.

## Voraussetzungsprüfung

Bevor die Extension etwas hochlädt, prüft sie:

1. **Serveradresse vorhanden:** Wurde die Lector-App beim ersten Start konfiguriert? Liest aus App-Group-`UserDefaults`.
2. **Im Modus `paperless`: Zusätzlich Schlüssel vorhanden:** Ist die App angemeldet? Liest aus gemeinsamer Keychain-Gruppe.

**Sind diese Bedingungen nicht erfüllt:**

- Der Button oder die Oberfläche zeigt einen Hinweis: **„Bitte zuerst in der Lector-App anmelden"** oder ähnlich.
- Es wird **nichts hochgeladen**.
- Die Person wird zur Lector-App geleitet (oder das Menü wird geschlossen).

Im Modus `none` ist nur die Serveradresse erforderlich, nicht der Schlüssel (da keine Anmeldung stattfindet).

## Formatweiche

Die Extension entscheidet nach dem `UTType` der Datei:

### PDF, XML, TIFF — byte-genau

Diese Dateitypen werden **ohne Veränderung** hochgeladen:

- **PDF:** Byte-identisch mit dem Original. Wichtig für E-Rechnungen (ZUGFeRD, Factur-X), die sich auf die genaue Byte-Sequenz verlassen.
- **XML:** Byte-identisch. Wichtig für XRechnung-Dateien.
- **TIFF:** Byte-identisch. Mehrseitige TIFFs (Scanner, Fax) werden nicht konvertiert.

### Andere Bilder → PDF

Bilder in anderen Formaten werden zu einem PDF konvertiert (wie beim Scanner/Picker). Beispiele:

- **JPG, PNG, WebP, HEIC** → PDF mit dem Bild als Seite
- **SVG, GIF, BMP** → Abgewiesen (siehe unten)

### Alles andere — Ablehnung

Dateitypen, die nicht erkannt werden, werden **abgewiesen**. Beispiele:

- **.txt** (Textdatei)
- **.docx** (Word)
- **.zip** (Archiv)
- Beliebige unbekannte Formate

Die Datei wird **nicht hochgeladen**, und der Hinweis zeigt den Dateinamen: z. B. „Datei ‚Notiz.txt' wird nicht unterstützt".

### SVG und Rest

SVG und andere seltene Formate werden explizit abgewiesen, auch wenn sie technisch in ein Bild konvertierbar sind. Grund: Diese Formate kommen in der Praxis selten vor und würden das Testing-Spektrum unnötig vergrößern.

## Dateiname-Regel mit passender Endung

Beim Upload erhält die Datei einen eindeutigen Namen mit passendem Suffix:

- **PDF:** `Beleg_<UUID>.pdf` oder `<Originalname>.pdf` (wenn Original kein PDF war)
- **XML:** `<Originalname>.xml` (erhalten)
- **TIFF:** `<Originalname>.tiff` (erhalten)

**Beispiel:**

- Geteilte Datei: `Rechnung 12.03.2025` (Typ: PDF)
  → Upload-Name: `Rechnung 12.03.2025.pdf`

- Geteilte Datei: `IMG_001` (Typ: JPEG)
  → Konvertiert zu PDF
  → Upload-Name: `IMG_001.pdf` (oder `Beleg_<UUID>.pdf`, je nach Implementierung)

Dies stellt sicher, dass der Server den korrekten Dateityp erkennt, auch wenn die Endung fehlte.

## TeilenModell

Das Modell verwaltet den Upload-Prozess:

### Ergebnis je Datei

Wenn mehrere Dateien geteilt werden, gibt die Extension für **jede Datei einzeln** ein Ergebnis:

```
Datei 1 „Rechnung.pdf": ✓ Hochgeladen
Datei 2 „Foto.jpg": ✓ Hochgeladen zu PDF konvertiert
Datei 3 „Notiz.txt": ✗ Format wird nicht unterstützt
```

Die Person sieht, welche Dateien erfolgreich waren und welche abgelehnt wurden.

### Erneut senden

Wenn der Upload einer Datei fehlschlägt (Netzwerkfehler, 5xx, etc.), kann die Person „Erneut senden" tippen. Dies versucht nochmals, diese eine Datei hochzuladen.

### `401` stoppt den Rest

Wenn während des Uploads ein `401 not_authenticated` auftritt:

1. **Alle weiteren Dateien werden nicht hochgeladen.**
2. **Die Extension zeigt:** „Sitzung abgelaufen. Bitte in der Lector-App neu anmelden."

Dies ist ein Sicherheitsmaßnahme: Wenn die Authentifizierung fehlschlägt, ist kein Datei-Upload mehr möglich.

### Hochladen im Vordergrund

Das Hochladen passiert **im Vordergrund** der Extension (nicht im Hintergrund). Die Person sieht:

- Einen Fortschrittsbalken pro Datei.
- Jede hochgeladene oder abgelehnte Datei wird sofort angezeigt.

Nach abschluss kann die Person die Ergebnisse sehen und bestätigen, dass sie die Extension schließen möchte.

## Speichergrenze der Extension

Share Extensions haben eine harte Speicherlimit von etwa **120 MB RAM**. Dies ist eine iOS-Beschränkung, kein Lector-Limit.

**Auswirkungen:**

- **Speicher-intensive Operationen:** Die PDF-Erzeugung aus großen Bildern findet nicht im RAM statt, sondern nutzt Dateien-Streaming (ähnlich wie beim Upload).
- **Große PDFs:** Ein PDF >100 MB wird erkannt und die Extension zeigt einen Hinweis wie „Datei zu groß für die Extension" oder „Speicherlimit der Extension überschritten".

Im Abnahmetest wird ein PDF >100 MB getestet, um sicherzustellen, dass die Extension mit angemessener Fehlermeldung reagiert.

## Code-Orte

| Datei | Rolle |
|---|---|
| `ios/LectorShare/ShareViewController.swift` | Extension-Einstieg, Aktivierungsregel-prüfung (`NSExtensionActivationRule`), `NSItemProvider` verarbeiten |
| `ios/LectorShare/TeilenAnsicht.swift` | SwiftUI-Oberfläche (Fortschritt, Ergebnisse, Buttons) |
| `ios/LectorShare/ItemProviderQuelle.swift` | Datei-Zugriff über `NSItemProvider`, Laden aus gemeinsamer App Group |
| `ios/LectorShare/Config/Info.plist` | Aktivierungsregel, Bundle-ID `me.krinke.lector.share`, App Group, Keychain-Gruppe |
| `ios/LectorShare/Config/Entitlements.plist` | App Group, Keychain-Gruppe |
| `ios/Shared/Capture/Formatweiche.swift` | UTType-Weiche (PDF/XML/TIFF unverändert, Bilder zu PDF, Rest abgewiesen) |
| `ios/Shared/Capture/TeilenVorbereitung.swift` | Dateinamen-Regeln, Endung-Anpassung |
| `ios/Shared/Capture/TeilenModell.swift` | Upload-Verwaltung (je Datei Ergebnis, Erneut senden, 401-Stop, Speicherlimit-Handling) |
| `ios/Shared/Network/Upload.swift` | Multipart-Streaming, Datei-für-Datei-Upload |
| `app/api.py` | Route `POST /api/v1/upload` |
