# iOS-App „Lector“

Native SwiftUI-App zum Übergeben von Belegen an Lector und zum Verfolgen der Verarbeitung.
Minimum ist **iOS 26**, Swift 6 mit vollständiger Concurrency-Prüfung. Maßgeblich sind
`openspec/changes/ios-app/` (Design, Spec, Tasks) und der Schnittstellenvertrag v1 im Anhang
von `design.md`. Stand dieses Ordners: Gerüst, Netzwerkschicht, Einrichtung, Anmeldung,
Einstellungen, Historie mit Detail und Live-Aktualisierung, Erfassung (Scanner, Fotoauswahl, PDF,
Upload) und die Share Extension.

## Projekt erzeugen (XcodeGen)

Das Xcode-Projekt wird **nicht** eingecheckt. `ios/Lector.xcodeproj` ist generiert und per
`.gitignore` ausgeschlossen. Quelle der Wahrheit sind `project.yml` und `xcodegen/base.yml`.

```sh
brew install xcodegen      # einmalig
cd ios && xcodegen generate
```

Nach jeder Änderung an `project.yml`, an `xcodegen/base.yml` oder nach dem Hinzufügen bzw.
Entfernen von Quelldateien neu erzeugen. Einstellungen nie in Xcode von Hand ändern.

## Aufbau

| Verzeichnis | Inhalt |
|---|---|
| `Lector/App` | Einstieg (`LectorApp`, `WurzelAnsicht`), `AppAbhaengigkeiten`, Debug-Startargumente und Attrappen-Dienst (`UITestStart`), Privacy-Manifest |
| `Lector/UI` | Einrichtung, Anmeldung, Einstellungen, `HauptAnsicht` (Rahmen mit Historie, Einstellungen und Menü „Beleg übergeben“), `SitzungsModell`, `EinrichtungsModell` |
| `Lector/UI/Historie` | Historie (Liste, Zähler, Filter, Suche), Detail mit Verlauf und Freigabe; `HistorieModell`, `DetailModell`, `Anzeige` (Begriffe, Zeitzone) |
| `Lector/UI/Erfassung` | Scanner (`DokumentScanner`, `VNDocumentCameraViewController`), Fotoauswahl (`PhotosPicker` in `HauptAnsicht`), Übergabeblatt `ErfassungsAnsicht` und der Ablauf `ErfassungsModell` (Seiten → ein PDF → Upload; bereit, vorbereiten, senden, übergeben, abgewiesen, fehlgeschlagen mit „Erneut senden“; löscht beim Schließen den Arbeitsordner) |
| `Lector/Live` | `EreignisStrom`: SSE-Verbindung zu `/api/v1/events` mit Wiederaufbau, speist die Historie |
| `Lector/Design` | `Farbe` (Akzent und Signalfarben aus `DESIGN.md`), `Farben.xcassets` |
| `Lector/Config` | `Info.plist`, `Lector.entitlements` |
| `LectorShare` | Share Extension (D13): `ShareViewController`, SwiftUI-Oberfläche, `ItemProviderQuelle`; `Config/` mit Info.plist (Aktivierungsregel) und Entitlements |
| `Shared` | Code für App **und** Extension: `Network/` (`APIClient`, `AuthSession`, `TokenStore`, `ServerKonfiguration`, `ServerAdresse`, DTOs, `Upload` mit Multipart), `Capture/` (`PDFErzeuger`, `Formatweiche`, `TeilenVorbereitung`, `TeilenModell`) |
| `LectorTests` | Unit-Tests (Swift Testing) |
| `LectorUITests` | UI-Tests (XCTest): Anmeldung, Historie, Erfassung; eigenes Schema |
| `scripts/` | `farben_erzeugen.py` (Color Sets aus DESIGN.md), `icon_erzeugen.py` (vorläufiges Symbol) |

Targets: `Lector` (`me.krinke.lector`), `LectorShare` (`me.krinke.lector.share`), `LectorTests`,
`LectorUITests`. Team `J3P792SJ75`, automatisches Signing. `Shared/` ist in beide App-Targets
eingebunden (kein Framework).

Gemeinsame Ablagen von App und Extension:

- **App Group** `group.me.krinke.lector`: Serveradresse und Zugangsmodus in `UserDefaults`
  (`ServerKonfiguration`).
- **Keychain-Gruppe** `$(AppIdentifierPrefix)me.krinke.lector.shared`: der Zugangsschlüssel
  (`KeychainTokenStore`, `AfterFirstUnlockThisDeviceOnly`; Gruppe aus der Info.plist-Zeile
  `KeychainAccessGroup`).

Es gibt keine `API_BASE_URL`-Build-Einstellung: Die Adresse kommt aus der Einrichtung in der App.
`http` ist nur im lokalen Netz zulässig (`NSAllowsLocalNetworking`, kein `NSAllowsArbitraryLoads`;
die App prüft es zusätzlich selbst).

## Tests

Zwei Schemas. Als Zielgerät dient der Simulator `iPhone 17 Pro`.

| Schema | Inhalt | Befehl |
|---|---|---|
| `Lector` | Unit-Tests (`LectorTests`) | `xcodebuild -project ios/Lector.xcodeproj -scheme Lector -destination 'platform=iOS Simulator,name=iPhone 17 Pro' test` |
| `LectorUITests` | UI-Tests (`AnmeldungUITests`, `HistorieUITests`, `ErfassungUITests`), nicht im Standard-Schema | `xcodebuild -project ios/Lector.xcodeproj -scheme LectorUITests -destination 'platform=iOS Simulator,name=iPhone 17 Pro' test` |

Die UI-Tests laufen ohne Server, Netz und Keychain: Startargumente (nur Debug, siehe
`Lector/App/UITestStart.swift`) schalten einen Attrappen-Dienst (`UITestTransport`), einen
Schlüsselspeicher im Arbeitsspeicher und eine eigene `UserDefaults`-Suite ein. Die Unit-Tests
nutzen `TransportAttrappe` (`LectorTests/TransportAttrappe.swift`). `xcodebuild test` meldet
„Executed 0 tests“ für Swift Testing; die Zahl steht in der Zeile „Test run with N tests“.

Erfassung in den UI-Tests: Kamera und Fotoauswahl lassen sich nicht automatisieren. `-UITEST_TESTBILD`
blendet im Menü „Beleg übergeben“ den Eintrag „Testbild übergeben“ ein (drei erzeugte Bilder);
`-UITEST_UPLOAD_FEHLER` lässt den ersten Upload scheitern, `-UITEST_UPLOAD_ABGELEHNT` lässt den
Dienst jede Datei ablehnen.

**Scanner auf dem Gerät prüfen** (der Simulator hat keine Kamera; `VNDocumentCameraViewController`
ist dort nicht brauchbar): Menü „+“ → „Beleg scannen“, mehrseitigen Beleg aufnehmen und sichern →
Bestätigung „An Lector übergeben“ → in Historie und Weboberfläche entsteht genau ein Vorgang mit der
Seitenzahl des Scans. Ohne Netz (Flugmodus) erscheint der Fehler mit „Erneut senden“; nach dem
Schließen wird nichts nachgeholt.

Bekannte Simulator-Eigenheit: `xcodebuild test` hängt gelegentlich oder meldet „failed to
launch“ — `xcrun simctl shutdown all` und wiederholen. Nach der Anmeldung kann iOS im Simulator
den Dialog „Passwort sichern?“ über die App legen; er fängt dann Taps ab.

Vor einem Merge auch den Release-Build prüfen, denn `#if DEBUG`-Code fällt in den Tests nicht auf:
`cd ios && xcodebuild -scheme Lector -configuration Release -destination 'generic/platform=iOS Simulator' SWIFT_TREAT_WARNINGS_AS_ERRORS=YES build`

## Farben und Symbol

Farben ausschließlich über `Farbe` (`Lector/Design/Farbe.swift`), keine Hex-Werte im Swift-Code.
Die Color Sets erzeugt `python3 ios/scripts/farben_erzeugen.py` aus den Werten von `DESIGN.md`
(vom Repo-Root aus ausführen). Das App-Symbol ist ein Platzhalter
(`python3 ios/scripts/icon_erzeugen.py`) und wird vor der Verteilung ersetzt.

## Archiv und TestFlight

Bundle-IDs `me.krinke.lector` und `me.krinke.lector.share` (endgültig), Team `J3P792SJ75`,
automatisches Signing. Verteilung über TestFlight.

**Voraussetzung:** In Xcode angemeldet und die aktuelle Programmlizenzvereinbarung im
Developer-Portal akzeptiert. Beim ersten Archiv legt `-allowProvisioningUpdates` beide Bundle-IDs,
die App Group, die Keychain-Fähigkeit, das Distribution-Zertifikat und die Profile selbst an.

```sh
cd ios && xcodegen generate

# 1. Archiv
xcodebuild -project Lector.xcodeproj -scheme Lector -configuration Release \
  -destination 'generic/platform=iOS' -archivePath build/Lector.xcarchive \
  -allowProvisioningUpdates archive

# 2. Export und Upload nach App Store Connect (destination "upload" in ExportOptions.plist)
xcodebuild -exportArchive -archivePath build/Lector.xcarchive \
  -exportOptionsPlist ExportOptions.plist -allowProvisioningUpdates
```

`ExportOptions.plist` setzt `manageAppVersionAndBuildNumber` auf `false`: **Vor jedem Upload die
Buildnummer hochzählen.** `CURRENT_PROJECT_VERSION` in `project.yml` um 1 erhöhen, dann
`xcodegen generate`. `MARKETING_VERSION` nur bei einer neuen sichtbaren Version ändern; die
Extension übernimmt beide Werte aus den Projekteinstellungen.

- Verschlüsselung: `ITSAppUsesNonExemptEncryption = NO` steht in beiden Info.plist.
- Nur Hochformat und nur iPhone: `TARGETED_DEVICE_FAMILY: "1"` muss am **Target** stehen.
- **Privacy-Manifeste** `Lector/App/PrivacyInfo.xcprivacy` und `LectorShare/PrivacyInfo.xcprivacy`
  sind Pflicht (`UserDefaults` der App Group, Grund `1C8F.1`); sonst verwirft App Store Connect den
  Build nach dem Upload (ITMS-91053). Neue Required-Reason-APIs dort nachtragen.
- Beim allerersten Upload ist die Bundle-ID erst nach einem **Export** registriert.
