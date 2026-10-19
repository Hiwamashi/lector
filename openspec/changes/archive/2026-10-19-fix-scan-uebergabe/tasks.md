# Tasks

Testbefehle (aus `ios/README.md`):
- Unit: `xcodebuild -project ios/Lector.xcodeproj -scheme Lector -destination 'platform=iOS Simulator,name=iPhone 17 Pro' test`
- UI: `xcodebuild -project ios/Lector.xcodeproj -scheme LectorUITests -destination 'platform=iOS Simulator,name=iPhone 17 Pro' test`

## 1. Fehler im Test nachstellen (vor dem Fix)

- [x] 1.1 In `ios/Lector/App/UITestStart.swift` das Startargument `-UITEST_TESTSCAN` ergänzen (nur `#if DEBUG`, Doku-Kommentar wie bei `-UITEST_TESTBILD`). Prüfen: Debug-Build kompiliert.
- [x] 1.2 In `HauptAnsicht.swift` den Menüeintrag „Testscan übergeben“ (`haupt.testscan`) ergänzen. Er öffnet per `fullScreenCover` eine einfache Ansicht mit „Speichern“ (`testscan.speichern`), die dieselbe Übergabe-Logik wie der Scanner-Callback auslöst. Prüfen: Der Eintrag erscheint im Simulator nur mit dem Startargument.
- [x] 1.3 In `ios/LectorUITests/ErfassungUITests.swift` den Test `testScanWegUebergibt` ergänzen: Testscan öffnen → „Speichern“ → `erfassung.uebergeben` erwarten. Mit dem **unveränderten** Übergabe-Code laufen lassen und das Ergebnis festhalten. Erwartet: Der Test schlägt fehl (`erfassung.abgewiesen`/`erfassung.fehler` statt `uebergeben`). Schlägt er nicht fehl, den Befund in `design.md` unter Risks vermerken und trotzdem fortfahren.

## 2. Modell absichern (`ErfassungsModell`)

- [x] 2.1 Unit-Test in `ErfassungsModellTests`: Wird die Aufgabe von `starten()` nach der PDF-Erzeugung abgebrochen, erfolgt kein Upload (Transport-Attrappe zählt 0 Uploads) und `zustand == .bereit`. Prüfen: Test schlägt vor 2.2 fehl.
- [x] 2.2 In `starten()` nach `pdfErzeugen` auf Abbruch prüfen und ohne Upload nach `.bereit` zurückkehren (Design D3). Prüfen: Test aus 2.1 grün.
- [x] 2.3 Unit-Test: Fehlt die vorbereitete Datei beim Senden, ist der Zustand `.abgewiesen("Der vorbereitete Beleg liegt nicht mehr vor. Bitte neu erfassen.")` und `kannErneutSenden == false`. Prüfen: Test schlägt vor 2.4 fehl.
- [x] 2.4 In `senden()` `UploadFehler.dateiNichtLesbar` ausdrücklich fangen und die Meldung aus D4 setzen. `vorbereitet` dabei verwerfen. Prüfen: Test aus 2.3 grün, übrige `ErfassungsModellTests` grün.

## 3. Präsentation und Aufräumen (`HauptAnsicht`, `ErfassungsAnsicht`)

- [x] 3.1 `onDisappear { modell.aufraeumen() }` aus `ErfassungsAnsicht` entfernen. Das Aufräumen in `HauptAnsicht` an das Schließen des Blatts binden (`.sheet(item:onDismiss:)` bzw. Schließen-Button), sodass genau das geschlossene Modell aufgeräumt wird (Design D2). Kommentare in `ErfassungsAnsicht`/`ErfassungsModell` zum Aufräumzeitpunkt anpassen. Prüfen: Bestehende UI-Tests in `ErfassungUITests` grün, darunter Abbruch und Erneut senden.
- [x] 3.2 Scanner-Weg umstellen: Der `fertig`-Callback merkt sich die Bilder (`ausstehenderScan`) und schließt nur den Scanner. `onDismiss` der `fullScreenCover` startet die Übergabe (Design D1). Der Testscan-Weg aus 1.2 nutzt denselben Pfad. Prüfen: `testScanWegUebergibt` aus 1.3 grün.
- [x] 3.3 Abbrechen im Scanner prüfen: `abgebrochen` setzt keinen `ausstehenderScan`, `onDismiss` öffnet dann kein Blatt. Prüfen: UI-Test `testScanAbbrechenOeffnetKeineUebergabe` (Testscan-Ansicht mit „Abbrechen“) grün.

## 4. Gesamtprüfung

- [x] 4.1 Unit- und UI-Testsuite vollständig laufen lassen. Prüfen: beide Befehle oben ohne Fehlschlag. Die Testzahl aus „Test run with N tests“ notieren.
- [x] 4.2 Release-Build mit Warnungen als Fehler bauen (`cd ios && xcodebuild -scheme Lector -configuration Release -destination 'generic/platform=iOS Simulator' SWIFT_TREAT_WARNINGS_AS_ERRORS=YES build`). Prüfen: Build erfolgreich, Testscan-Weg nicht im Release-Code (`#if DEBUG`).

## 5. Build, Doku, Fortschritt

- [x] 5.1 `CURRENT_PROJECT_VERSION` in `ios/project.yml` erhöhen und `xcodegen` ausführen. Prüfen: `Lector.xcodeproj` übernimmt die neue Build-Nummer.
- [x] 5.2 `feature-documentation/ios-app/` aktualisieren: Ablauf der Scanner-Übergabe (Blatt nach Schließen des Scanners, Aufräumzeitpunkt, neue Fehlermeldung, Startargument `-UITEST_TESTSCAN`). In `abnahme.md` beim Scanner einen Hinweis auf den behobenen Fehler ergänzen. Prüfen: Die Dateien nennen den neuen Ablauf.
- [x] 5.3 `prd/PROGRESS.md` um den Fix ergänzen (Befund, Ursache, Stand der Geräteabnahme). Prüfen: Eintrag vorhanden.
- [x] 5.4 `graphify update .` ausführen. Prüfen: Befehl ohne Fehler.

## 7. Nacharbeit aus dem Review

- [x] 7.1 Unit-Test für `ErfassungsModell.verwaisteAufraeumen(ausser:)`: Zwei angelegte `erfassung-*`-Ordner, einer ausgenommen. Danach existiert nur noch der ausgenommene, andere Einträge im temporären Ordner bleiben unberührt. Funktion umsetzen (Design D6). Prüfen: Test grün.
- [x] 7.2 `HauptAnsicht`: `uebergeben` räumt ein vorgemerktes `offeneErfassung` vor dem Überschreiben auf, `.task` ruft `verwaisteAufraeumen(ausser: offeneErfassung?.arbeitsordner)` (Design D6). Prüfen: `ErfassungUITests` grün.
- [x] 7.3 Unit-Test in `UploadTests`: Ist der Rumpf nicht schreibbar, die Quelldatei aber lesbar, wirft `hochladen` `UploadFehler.rumpfNichtSchreibbar`. Bei fehlender Quelldatei bleibt es `dateiNichtLesbar`. Unterscheidung in `Upload.swift` umsetzen (Design D7). Prüfen: Tests grün.
- [x] 7.4 `ErfassungsModell.senden()`: `rumpfNichtSchreibbar` ergibt `.fehlgeschlagen` mit der Meldung aus D7, `kannErneutSenden == true`. Unit-Test dazu. Prüfen: `ErfassungsModellTests` grün.
- [x] 7.5 Unit-, UI-Suite und Release-Build mit Warnungen als Fehler erneut laufen lassen. Doku (`feature-documentation/ios-app/erfassung-und-pdf.md`, `prd/PROGRESS.md`) um D6/D7 ergänzen, `graphify update .`. Prüfen: alles grün, Doku nennt beide Punkte.

## 6. Geräteabnahme (manuell, nach TestFlight-Upload)

- [x] 6.1 Auf dem iPhone einen dreiseitigen Beleg scannen. Prüfen: „An Lector übergeben“ erscheint, im Lector-Log steht `POST /api/v1/upload` mit 200, und in der Historie entsteht ein Vorgang mit drei Seiten.
- [x] 6.2 Scan im Flugmodus → Fehlschlag → Flugmodus aus → „Erneut senden“. Prüfen: Die Übergabe gelingt mit demselben PDF.
