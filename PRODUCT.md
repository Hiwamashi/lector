# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- **Primär:** der Betreiber selbst — Einzelnutzer mit privatem NAS (Zettlab/ZettOS) und
  Paperless-ngx im LAN. Er scannt Papierpost, prüft danach kurz, ob alles durchgelaufen
  ist, geht Fehlern nach und arbeitet eingegangene Rechnungen ab.
- **Sekundär:** andere Paperless-Selbsthoster, die Lector aus dem öffentlichen
  GPL-3-Repository (`github.com/Hiwamashi/lector`) selbst betreiben. Sie müssen den Dienst
  ohne Vorwissen über dieses Setup verstehen, konfigurieren und im Betrieb lesen können.

## Product Purpose

Lector schiebt sich als reiner Veredelungsschritt **vor** Paperless-ngx: Er überwacht einen
Eingangsordner, macht aus Bildern, PDFs und TIFFs per Cloud-OCR (Google Document AI)
durchsuchbare Sandwich-PDFs und legt sie in den `consume`-Ordner. E-Rechnungen (XRechnung,
ZUGFeRD/Factur-X) werden deterministisch erkannt und unverändert durchgereicht.

Erfolg heißt: Jedes eingeworfene Dokument kommt mit sauberem, durchsuchbarem Text in
Paperless an, ohne dass man sich darum kümmern muss — und wenn doch etwas hängt, sieht man
sofort was, warum und in welchem Schritt.

## Positioning

Lector ersetzt Paperless nicht, sondern verbessert genau einen Schritt davor: die
Texterkennung schwieriger Vorlagen (schlechte Scans, Fotos, gemischte Formate), bei der die
eingebaute Tesseract-OCR an Grenzen stößt. Klassifizierung, Tags und Korrespondenten bleiben
vollständig bei Paperless. Die OCR-Engine ist über ein Adapter-Interface austauschbar.

## Operating Context

- Läuft als zusätzlicher Docker-Container im bestehenden Paperless-Compose-Stack, ein
  Prozess für Web-UI, API und Hintergrund-Worker.
- Web-UI wird überwiegend am **Desktop-Browser im LAN** genutzt; Smartphone nur ausnahmsweise.
- Typische Anlässe, die UI zu öffnen:
  1. **Kontrolle nach dem Scannen** — Status-Kacheln und Historie: durchgelaufen oder hängt es?
  2. **Fehler nachgehen** — Detailansicht mit Verlaufs-Log, Fehlermeldung, Retry-Stand.
  3. **Rechnungen abarbeiten** (Paperless-Integration, per `FEATURE_PAPERLESS_SYNC`
     standardmäßig aus) — Rechnungsliste, GiroCode mit der Banking-App scannen,
     SevDesk-Export, Empfänger-Zuordnung.
  4. **Dateien hochladen** — Browser-Upload in den Eingangsordner als Alternative zum Scan-Ordner.
- Die meiste Zeit arbeitet Lector unbeobachtet; die UI ist ein Kontroll- und
  Nacharbeitsinstrument, kein Ort für tägliche Dauerarbeit.

## Capabilities and Constraints

- Seiten: Dokumente (Dashboard mit Status-Kacheln, filterbare Historie, Detailansicht mit
  Live-Fortschritt via SSE), Rechnungen, Empfänger.
- Status: `pending | processing | done | skipped_erechnung | failed`; Auto-Retry nach 15 min,
  max. 3 Versuche, **kein** manueller Retry-Button.
- **Keine Authentifizierung**, LAN-only, Einzelnutzer; Upload ohne Größenbegrenzung.
- UI-Stack: serverseitige Jinja2-Templates, offline-CSS, Vanilla-JS — **kein**
  Node-Buildchain, keine CDN-Abhängigkeiten zur Laufzeit.
- Oberflächensprache Deutsch.
- Explizit ausgeschlossen: inhaltliche Datenextraktion/Klassifizierung/Tags, eigenes Scannen,
  Cloud-Anbindung außer der OCR-Engine.
- E-Rechnungs-Erkennung ist deterministisch — nie per KI/OCR geraten.
- Fachbegriffe: Sandwich-PDF, Watch-Folder / `scan-in`, `consume`, `processed`, `error`,
  E-Rechnung, Chunk, GiroCode, Empfänger.

## Brand Commitments

- Name **Lector**; Favicon unter `app/static/favicon.svg`.
- Bisheriger Ton: sachlich, knapp, deutschsprachig; der Dienst soll ruhig und verlässlich
  wirken statt aufmerksamkeitsheischend.

## Evidence on Hand

- Produktiv auf dem NAS im Einsatz; OCR-Weg mit echten Document-AI-Credentials verifiziert.
- Anforderungen und Stand: `prd/PRD_Lector.md`, `prd/PROGRESS.md`;
  Feature-Dokumentation in `feature-documentation/`.
- Keine Nutzerzahlen, Testimonials, Benchmarks oder Screenshots für Dritte vorhanden —
  nicht erfinden.

## Product Principles

1. **Unsichtbar, solange alles läuft.** Lector arbeitet im Hintergrund; die UI bestätigt
   Erfolg mit einem Blick und drängt sich nicht auf.
2. **Fehler sind erklärbar.** Wenn etwas hängt oder scheitert, zeigt die UI Schritt, Grund
   und nächsten Retry — ohne Logs auf dem NAS lesen zu müssen.
3. **Paperless bleibt der Ort für Inhalte.** Lector beansprucht keine Aufgaben, die
   Paperless gehören.
4. **Deterministisch vor clever.** Erkennung und Routing sind nachvollziehbar; nichts wird
   geraten.
5. **Für Fremde betreibbar.** Konfiguration und UI setzen kein Wissen über das
   Setup des Autors voraus.

## Accessibility & Inclusion

- Tastaturbedienung mit `:focus-visible`; Kontraste in Hell- und Dunkelmodus nach WCAG AA
  (siehe `feature-documentation/ui-erscheinungsbild.md`). Darüber hinaus keine
  produktspezifischen Anforderungen festgelegt.
