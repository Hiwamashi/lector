# Proposal

## Why

Belege entstehen meist unterwegs: ein Kassenbon, eine Rechnung, die per Mail kommt. Heute
gelangen sie nur über die Dateifreigabe oder den Upload in der Weboberfläche in Lector. Eine
native iOS-App soll Belege direkt vom Handy einspeisen, also scannen oder über das
Teilen-Menü übergeben. Sie soll außerdem den Stand der Verarbeitung so zeigen wie das
Dashboard. Seit der Anmeldung über Paperless ist Lector öffentlich hinter HTTPS erreichbar.
Damit ist die Grundlage für einen Zugriff von unterwegs vorhanden.

## What Changes

- **Neue App-Schnittstelle (JSON) unter `/api/`** als schmale Schicht über die bestehenden
  Repository-Funktionen. Sie umfasst:
  - Selbstauskunft des Dienstes (ist das ein Lector, welcher Zugangsmodus gilt), ohne Anmeldung
  - Anmelden und Abmelden
  - Vorgangsliste mit Zählern und denselben Filtern wie im Dashboard
  - Detail eines Vorgangs mit Verlauf
  - Freigeben und Verwerfen angehaltener Vorgänge
  - Datei-Upload mit maschinenlesbarer Rückmeldung je Datei
  - der bestehende Ereignisstrom `/events` für die Live-Aktualisierung
- **Anmeldung per Zugangsschlüssel:** Die App meldet sich wie die Weboberfläche über
  Paperless an, also mit Nutzername, Passwort und optionalem MFA-Code. Sie erhält dieselbe
  Sitzung (`web_sessions`, 30 Tage gleitend, 90 Tage absolut, gleiche Bremse bei
  Fehlversuchen). Den Schlüssel schickt sie im `Authorization`-Header statt als Cookie mit.
  Anfragen mit Schlüssel sind von der Herkunftsprüfung ausgenommen. Diese schützt nur vor
  Cookies, die der Browser automatisch mitschickt.
- **Native iOS-App** (SwiftUI, iOS 26, Swift 6) im Unterordner `ios/`. Aufbau, Signierung und
  Verteilung über TestFlight folgen dem Muster der bestehenden App „Smoking Tracker“. Die App
  umfasst:
  - Anmeldebildschirm mit Eingabe der Serveradresse; die Adresse wird gespeichert
  - Historie mit Zählern und Filtern, Detail mit Verlauf, Freigeben und Verwerfen
  - Live-Aktualisierung
  - Dokumentenscanner; Scans und Fotos werden auf dem Gerät zu **einem PDF** umgewandelt
  - Share Extension: PDF- und XML-Dateien werden **byte-genau unverändert** übergeben, damit
    E-Rechnungen erkannt bleiben
- Die App arbeitet nur mit Verbindung zum Server. Es gibt keine Warteschlange auf dem Gerät.
- **Nicht im Umfang:** Rechnungen (GiroCode, SevDesk, bezahlt), Empfänger-Zuordnung,
  Offline-Betrieb, iPad, Push-Mitteilungen.

## Capabilities

### New Capabilities

- `app-schnittstelle`: JSON-Schnittstelle für die App. Umfasst Selbstauskunft, Anmelden und
  Abmelden, Vorgangsliste mit Zählern und Filtern, Vorgangsdetail mit Verlauf, Freigeben und
  Verwerfen, Ereignisstrom sowie Fehlerantworten.
- `ios-app`: Verhalten der iOS-App. Umfasst Serveradresse und Anmeldung, Aufbewahrung des
  Zugangsschlüssels, Historie und Detail, Entscheidungen, Scannen mit Umwandlung zu PDF,
  Übergabe über das Teilen-Menü und den Umgang mit fehlender Verbindung oder abgelaufener
  Sitzung.

### Modified Capabilities

- `web-zugang`: Neben dem Cookie wird ein Zugangsschlüssel als Nachweis einer Sitzung
  anerkannt. Die Anmeldung ist auch über die Schnittstelle möglich, mit derselben Prüfung,
  Bremse und Protokollierung. Anfragen mit Zugangsschlüssel sind von der Herkunftsprüfung
  ausgenommen. Die Selbstauskunft gehört zu den offenen Pfaden.
- `datei-upload`: Die Übergabe ist zusätzlich über die Schnittstelle möglich, mit denselben
  Übergaberegeln und einer maschinenlesbaren Rückmeldung je Datei.

## Impact

- **Server-Code:**
  - `app/auth.py`: Zugangsschlüssel aus dem `Authorization`-Header, Ausnahme von der
    Herkunftsprüfung, offener Pfad für die Selbstauskunft
  - `app/main.py` oder ein neues Modul `app/api.py`: JSON-Routen
  - `app/fileops.py` und `app/decisions.py` werden wiederverwendet und nicht geändert
- **Datenbank:** keine Schemaänderung. Die App-Sitzungen liegen in `web_sessions`.
- **Neuer Code:** `ios/` mit XcodeGen-Projekt (`project.yml`), App-Target, Share-Extension-
  Target, Unit- und UI-Tests. Dazu kommen eine App Group und eine gemeinsame Keychain-Gruppe.
- **Konfiguration:** keine neuen Umgebungsvariablen. Der Zugangsmodus und
  `LECTOR_SECRET_KEY` gelten unverändert für App und Weboberfläche.
- **Abhängigkeiten:**
  - Server: keine neuen
  - iOS: nur Systemframeworks (SwiftUI, VisionKit, PDFKit, Security, URLSession)
- **Betrieb:** Der Reverse Proxy muss den Ereignisstrom und `Authorization`-Header
  unverändert durchreichen. Bei der bestehenden Einrichtung ist das bereits der Fall und wird
  nur zu prüfen sein.
- **Dokumentation:**
  - `feature-documentation/`: neue Dateien für App-Schnittstelle und iOS-App
  - Anpassung von `web-zugang.md` und `datei-upload.md`
  - `prd/PROGRESS.md` nachziehen
