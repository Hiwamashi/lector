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

Lector schiebt sich als Veredelungsschritt **vor** Paperless-ngx: Er überwacht einen
Eingangsordner, macht aus Bildern, PDFs und TIFFs per Cloud-OCR (Google Document AI)
durchsuchbare Sandwich-PDFs und legt sie in den `consume`-Ordner. E-Rechnungen (XRechnung,
ZUGFeRD/Factur-X) werden deterministisch erkannt und unverändert durchgereicht.

Erfolg heißt: Jedes eingeworfene Dokument kommt mit sauberem, durchsuchbarem Text in
Paperless an, ohne dass man sich darum kümmern muss — und wenn doch etwas hängt, sieht man
sofort was, warum und in welchem Schritt.

## Positioning

Lector ist die Oberfläche für den Alltag mit Dokumenten, Paperless-ngx ist das Backend für
Details und Pflege. Der Kern bleibt ein Veredelungsschritt vor Paperless: Lector verbessert die
Texterkennung schwieriger Vorlagen (schlechte Scans, Fotos, gemischte Formate), bei der die
eingebaute Tesseract-OCR an Grenzen stößt. Die OCR-Engine ist über ein Adapter-Interface
austauschbar.

Daneben zeigt Lector Paperless-Dokumente, damit man für den Alltag nicht zwischen den Systemen
wechseln muss. Die Grenze:

- **Lesend:** Vorschau, Metadaten (Titel, Korrespondent, Dokumenttyp, Datum, Tags, Custom
  Fields, Archivnummer) und Notizen.
- **Bearbeitbar, nur soweit es zu Lector-Abläufen gehört:** Empfänger, Rechnungsdaten (Betrag,
  IBAN, Verwendungszweck, „überwiesen“) und der SevDesk-Export.
- **Bleibt in Paperless:** Tags, Korrespondenten, Dokumenttypen, Regeln und Berechtigungen.
  Klassifizierung im Sinn von Dokumenttyp, Tags und Korrespondent macht Lector nicht.

Hinweis zur Sichtbarkeit: Die Dokumentansicht zeigt jedes Dokument, das Lectors Paperless-Token
lesen darf. Bei `AUTH_MODE=paperless` sehen damit alle angemeldeten Nutzer alle diese Dokumente,
nicht nur die von Lector verarbeiteten. Eine Freigabe pro Dokument gibt es nicht.

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
  5. **Dokumente ansehen** — Dokumentansicht eines Paperless-Dokuments (Vorschau, Metadaten,
     Notizen) als Seitenleiste neben den Listen oder als eigene Seite, ohne in Paperless zu
     wechseln. Braucht nur die Paperless-Anbindung (`PAPERLESS_URL` und Token), nicht
     `FEATURE_PAPERLESS_SYNC`.
- Die meiste Zeit arbeitet Lector unbeobachtet. Die UI ist Kontroll- und Nacharbeitsinstrument
  und, seit der Dokumentansicht, der Ort für den Alltag mit Paperless-Dokumenten. Pflege und
  Sonderfälle bleiben bei Paperless.

## Capabilities and Constraints

- Seiten: Dokumente (Dashboard mit Status-Kacheln, filterbare Historie, Detailansicht mit
  Live-Fortschritt via SSE), Rechnungen, Empfänger.
- Dokumentansicht eines Paperless-Dokuments: eigene Seite `/paperless/{id}` und Seitenleiste in
  Rechnungen, Empfänger und Dokumenten. Die Vorschau läuft über Lector. Der Rechnungsbereich in
  der Ansicht erscheint nur mit `FEATURE_PAPERLESS_SYNC`.
- Status: `pending | processing | done | skipped_erechnung | failed`; Auto-Retry nach 15 min,
  max. 3 Versuche, **kein** manueller Retry-Button.
- **Anmeldung optional:** Standard `AUTH_MODE=none` (anmeldefrei, LAN-Betrieb wie bisher);
  wahlweise `AUTH_MODE=paperless` für öffentlichen Betrieb hinter HTTPS-Proxy. Upload ist
  jeweils uneingeschränkt (ohne Größenbegrenzung), unterliegt aber demselben Zugangsschutz
  wie die Oberfläche. Einzelnutzer oder alle Paperless-Nutzer der Instanz.
- UI-Stack: serverseitige Jinja2-Templates, offline-CSS, Vanilla-JS — **kein**
  Node-Buildchain, keine CDN-Abhängigkeiten zur Laufzeit.
- Oberflächensprache Deutsch.
- Explizit ausgeschlossen: Klassifizierung im Sinn von Dokumenttyp, Tags und Korrespondent
  (bleibt bei Paperless) und eigenes Scannen.
- Inhaltliche Auswertung nur für Lector-eigene Abläufe: Zahldaten für den GiroCode
  (deterministisch aus E-Rechnungen, heuristisch aus dem OCR-Text, vom Nutzer korrigierbar),
  Empfänger-Vorschlag und Kontext-Einstufung „IT-Consulting“ für den SevDesk-Export sowie der
  Abgleich mit SevDesk-Belegen.
- Externe Dienste: Google Document AI für die OCR (Kern). Nur wenn konfiguriert und
  eingeschaltet zusätzlich die SevDesk-API (Belegexport und -abgleich) und die Anthropic-API
  (KI-Empfänger-Vorschlag). Ohne diese Zusätze verlässt nur der OCR-Aufruf das lokale Netz.
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
3. **Lector ist die Alltags-UI, Paperless der Ort für Details und Pflege.** Lector zeigt
   Paperless-Dokumente lesend und bearbeitet nur, was zu Lector-Abläufen gehört. Tags,
   Korrespondenten, Dokumenttypen, Regeln und Berechtigungen bleiben in Paperless.
4. **Deterministisch vor clever.** Erkennung und Routing sind nachvollziehbar; nichts wird
   geraten.
5. **Für Fremde betreibbar.** Konfiguration und UI setzen kein Wissen über das
   Setup des Autors voraus.

## Accessibility & Inclusion

- Tastaturbedienung mit `:focus-visible`; Kontraste in Hell- und Dunkelmodus nach WCAG AA
  (siehe `feature-documentation/ui-erscheinungsbild.md`). Darüber hinaus keine
  produktspezifischen Anforderungen festgelegt.
