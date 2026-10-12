# iOS-App — Feature-Dokumentation

Diese Dokumentation beschreibt die iOS-Anwendung „Lector", eine native SwiftUI-App zum Übergeben von Belegen an den Lector-Dienst und zum Verfolgen der Verarbeitung. Sie richtet sich an KI-Coding-Agenten und Entwickler, die die Codebase verstehen oder erweitern möchten.

**Maßgebliche Quellen:**

- `openspec/changes/ios-app/design.md` — Design-Entscheidungen (D9–D14)
- `openspec/changes/ios-app/specs/ios-app/spec.md` — Anforderungen und Szenarien
- `ios/README.md` — Build, Tests, Archiv, TestFlight (verweisen statt duplizieren)

---

## Übersicht der Module

| Datei | Inhalt |
|---|---|
| [einrichtung-und-anmeldung.md](einrichtung-und-anmeldung.md) | Serveradresse (Normalisierung, `/api/info`, ATS), Anmeldung mit MFA, Zugangsschlüssel in der Keychain, Sitzungszustände, 401-Verhalten vs. Netzwerkfehler, Abmelden, Server wechseln, Modus `none` |
| [historie-und-live.md](historie-und-live.md) | `HistorieModell` (Filter, Paging, Duplikatfilter, Generationen), Zähler, Zeitzone, Begriffe; `EreignisStrom` (SSE-Parser, Backoff, Wiederaufbau, `scenePhase`), Detail mit Verlauf, Entscheidungen und 409-Handling |
| [erfassung-und-pdf.md](erfassung-und-pdf.md) | Menü „Beleg übergeben", Scanner (`VNDocumentCameraViewController`), Fotoauswahl, `ErfassungsModell` (Zustände, Erneut senden, Aufräumen), `PDFErzeuger` (JPEG 0,85, max. 3000 px, EXIF, Alphakanal), Upload-Streaming |
| [teilen-menue.md](teilen-menue.md) | Share Extension (Aktivierungsregel, max. 20 Dateien), Voraussetzungsprüfung, Formatweiche (PDF/XML/TIFF byte-genau, Bilder zu PDF, Rest abgewiesen), `TeilenModell`, Speicherlimit |
| [abnahme.md](abnahme.md) | Checkliste für manuelle Abnahme auf echtem iPhone gegen echte Lector-Instanz |

---

## Code-Struktur (Übersicht)

```
ios/
├── Lector/                          # Haupt-App
│   ├── App/
│   │   ├── LectorApp.swift          # SwiftUI-Einstieg
│   │   ├── WurzelAnsicht.swift      # Tab-Navigation
│   │   ├── AppAbhaengigkeiten.swift # Dependency Injection
│   │   ├── UITestStart.swift        # Debug-Startargumente & Attrappen
│   │   └── Info.plist, Entitlements
│   ├── UI/
│   │   ├── EinrichtungsAnsicht.swift
│   │   ├── AnmeldungAnsicht.swift
│   │   ├── EinstellungenAnsicht.swift
│   │   ├── HauptAnsicht.swift
│   │   ├── SitzungsModell.swift
│   │   ├── EinrichtungsModell.swift
│   │   └── Historie/
│   │       ├── HistorieAnsicht.swift
│   │       ├── HistorieModell.swift
│   │       ├── DetailAnsicht.swift
│   │       ├── DetailModell.swift
│   │       └── Anzeige.swift
│   ├── UI/Erfassung/
│   │   ├── ErfassungsAnsicht.swift
│   │   ├── DokumentScanner.swift
│   │   └── ErfassungsModell.swift
│   ├── Live/
│   │   └── EreignisStrom.swift
│   ├── Design/
│   │   ├── Farbe.swift
│   │   └── Farben.xcassets
│   └── Config/
│       └── Info.plist
│
├── LectorShare/                     # Share Extension
│   ├── ShareViewController.swift
│   ├── TeilenAnsicht.swift
│   ├── ItemProviderQuelle.swift
│   └── Config/
│       ├── Info.plist (Aktivierungsregel)
│       └── Entitlements.plist
│
├── Shared/                          # Code für App & Extension
│   ├── Network/
│   │   ├── APIClient.swift
│   │   ├── AuthSession.swift
│   │   ├── ServerKonfiguration.swift
│   │   ├── ServerAdresse.swift
│   │   ├── TokenStore.swift
│   │   ├── Upload.swift
│   │   └── DTOs.swift
│   └── Capture/
│       ├── PDFErzeuger.swift
│       ├── Formatweiche.swift
│       ├── TeilenVorbereitung.swift
│       └── TeilenModell.swift
│
├── LectorTests/                     # Unit-Tests (Swift Testing)
│   └── *.swift
│
├── LectorUITests/                   # UI-Tests (XCTest)
│   ├── AnmeldungUITests.swift
│   ├── HistorieUITests.swift
│   └── ErfassungUITests.swift
│
├── project.yml                      # XcodeGen-Quelle
├── xcodegen/base.yml                # XcodeGen-Basis
├── ExportOptions.plist              # TestFlight/App Store
└── scripts/
    ├── farben_erzeugen.py
    └── icon_erzeugen.py
```

---

## Wichtige Entscheidungen

- **D9–D14 aus `design.md`:** Projektaufbau, XcodeGen, Ziele (Lector-App + Share Extension), gemeinsam genutzter Code, Serveradresse und ATS, Netzwerk & Sitzung, PDF-Erzeugung, Share Extension, Gestaltung
- **Keine Warteschlange:** Gescheiterte Uploads werden nicht automatisch nachgeholt (Spec verlangt explizites „Erneut senden")
- **Ein PDF pro Erfassung:** Scanner und Picker erzeugen ein PDF mit mehreren Seiten, nicht mehrere PDFs
- **Byte-Genauität für E-Rechnungen:** PDF, XML, TIFF werden unverändert durchgereicht

---

## Abhängigkeiten zu anderen Features

- **Anmeldung & Zugang:** `feature-documentation/web-zugang.md`, `feature-documentation/app-schnittstelle.md`
- **UI-Texte & Begriffe:** `feature-documentation/ui-texte.md` (Zustandsnamen, Ereignistypen)
- **Server-API:** `/api/info`, `/api/v1/login`, `/api/v1/logout`, `/api/v1/documents`, `/api/v1/documents/{id}`, `/api/v1/upload`, `/events`

---

## Build & Tests

Siehe `ios/README.md` für:

- **Projekt erzeugen:** XcodeGen, `xcodegen generate`
- **Tests:** Unit-Tests (Swift Testing) und UI-Tests (XCTest)
- **Archiv & TestFlight:** Build-Nummern, `ExportOptions.plist`, Privacy-Manifeste
- **Scanner auf echtem Gerät:** Simulator-Beschränkung, Flugmodus-Test

---

## Bekannte Grenzen & Heuristiken

- **MFA-Erkennung:** Die Unterscheidung zwischen „MFA-Code fehlt" und „Code ist falsch" basiert auf dem Antworttext von Paperless (heuristisch, siehe `web-zugang.md`).
- **Tokenablauf:** Der Token wird nach 90 Tagen ungültig (Server-seitig), die App erneuert ihn nicht automatisch.
- **Speicherlimit der Extension:** Share Extension darf max. ~120 MB RAM verbrauchen; große PDFs können abgelehnt werden.
- **Netzwerk-Klassifikation:** 401 vs. Netzwerkfehler — nur 401 löscht den Token.

---

## Prüfung der Implementierung

Die Abnahme-Checkliste (`abnahme.md`) deckt folgende Szenarien ab:

✓ Einrichtung mit Produktivadresse  
✓ Anmeldung mit MFA  
✓ Live-Aktualisierung durch Proxy  
✓ Mehrseitiger Scan (Durchsuchbarkeit, Begradigung)  
✓ HEIC-Fotos und Mehrfach-Auswahl  
✓ Flugmodus + Erneut senden  
✓ E-Rechnungen unverändert  
✓ Teilen-Menü mit mehreren Dateitypen  
✓ Teilen vor Anmeldung  
✓ Speicherlimit der Extension  
✓ Angehaltene Vorgänge und Freigabe  

---

## Weitere Ressourcen

- **Referenz-App:** Smoking Tracker (Team `J3P792SJ75`, Bundle `me.krinke`, Swift 6 mit strikter Concurrency)
- **Design-Farbwerte:** `feature-documentation/ui-erscheinungsbild.md` (DESIGN.md)
- **OpenSpec-Tickets:** `openspec/changes/ios-app/tasks.md` (Aufgaben 1–7)
