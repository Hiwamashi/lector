# Proposal

## Why

Ein Beleg, der in der iOS-App mit der Kamera gescannt wird, kommt nie bei Lector an. Die App
meldet „Senden fehlgeschlagen.“, im Log des Dienstes erscheint kein `POST /api/v1/upload`,
die Fotoauswahl über denselben Upload-Weg funktioniert dagegen. Ursache ist ein
Darstellungskonflikt: Die Scanner-Ansicht schließt sich, während im selben Moment das
Übergabe-Blatt erscheint. Dabei wird das Blatt einmal abgeräumt, `onDisappear` löscht den
Arbeitsordner samt fertigem PDF, und der weiterlaufende Ablauf findet beim Hochladen keine
Datei mehr (`UploadFehler.dateiNichtLesbar`). Der Scanner ist ein Kernweg der App; er war in
der zurückgestellten Geräteabnahme noch nicht geprüft.

## What Changes

- Das Übergabe-Blatt öffnet sich nach einem Scan erst, wenn die Scanner-Ansicht vollständig
  geschlossen ist.
- Das vorbereitete PDF bleibt erhalten, solange das Übergabe-Blatt geöffnet ist. Gelöscht wird
  es erst, wenn das Blatt tatsächlich geschlossen wird, nicht schon bei einem kurzzeitigen
  Verschwinden der Ansicht.
- Ein abgebrochener Übergabe-Ablauf läuft nicht mehr bis zum Upload weiter.
- Fehlt die vorbereitete Datei beim Senden, meldet die App das mit einer eigenen, verständlichen
  Meldung statt mit der Sammelmeldung „Senden fehlgeschlagen.“.
- Ein UI-Test bildet den Weg „Vollbild-Ansicht schließt sich, Übergabe startet“ nach, damit
  der Fehler nicht zurückkehrt.
- Build-Nummer für einen neuen TestFlight-Build erhöhen, Abnahme-Checkliste und Doku nachziehen.

## Capabilities

### New Capabilities

_keine_

### Modified Capabilities

- `ios-app`: Die Anforderung „Scans und Fotos werden als ein PDF übergeben“ erhält ein Szenario
  für die Übergabe unmittelbar nach dem Scannen. Die Anforderung „Ohne Verbindung wird nichts
  zwischengespeichert“ wird präzisiert: Das vorbereitete Dokument bleibt verfügbar, solange die
  Ansicht geöffnet ist, und erst das Schließen verwirft es.

## Impact

- **iOS-Code:** `ios/Lector/UI/HauptAnsicht.swift` (Scanner-Übergabe),
  `ios/Lector/UI/Erfassung/ErfassungsAnsicht.swift` und `ErfassungsModell.swift`
  (Aufräumen, Abbruch, Fehlertext).
- **Tests:** `ios/LectorTests/ErfassungsModellTests.swift`, `ios/LectorUITests/`,
  `ios/Lector/App/UITestStart.swift` (neuer Testweg).
- **Build:** `ios/project.yml` (`CURRENT_PROJECT_VERSION`).
- **Doku:** `feature-documentation/ios-app/`, `prd/PROGRESS.md`.
- **Server, Schnittstelle, Share Extension:** unverändert. Die Share Extension nutzt einen
  eigenen Ablauf (`TeilenModell`) und ist nicht betroffen.
