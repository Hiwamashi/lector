# Entwicklungsfortschritt — Lector

> Fortlaufend gepflegter Stand der MVP-Umsetzung (siehe `PRD_Lector.md`).
> Legende: ✅ umgesetzt · 🚧 in Arbeit · ⬜ offen

**Stand:** 2026-06-15

## Getroffene Entscheidungen (vormals offene Fragen)

1. **Watch-Folder-Vollständigkeit:** kombiniert — Rename aus `.tmp`/`.part`/`.crdownload` bevorzugt, Größenstabilität über N Sekunden als Fallback.
2. **Bereits durchsuchbare PDFs:** Es laufen **immer** alle PDFs durch Document AI (einheitliches Ergebnis).
3. **Document-AI-Throttling:** seitenbasiertes Rate-Limit im Worker (`DOCAI_MAX_PAGES_PER_MINUTE`).

## MVP-Features

| Feature | Status |
|---|---|
| Projektgerüst, ENV-Config | ✅ |
| SQLite-Historie (`documents`, `document_events`) | ✅ |
| Watch-Folder + Vollständigkeitsprüfung | ✅ |
| Serielle Verarbeitungs-Queue / Worker | ✅ |
| Format-Erkennung & Routing | ✅ |
| E-Rechnungs-Bypass (deterministisch) | ✅ |
| Bildvorverarbeitung (Deskew/Kontrast; Orientierung via Document AI) | ✅ |
| OCR-Adapter-Interface | ✅ |
| Document-AI-Adapter (Region eu) | ✅ |
| Chunking ≤15 Seiten | ✅ |
| Sandwich-PDF (Bild + Textlayer) | ✅ |
| Ablage nach consume (UID/GID 1000) | ✅ |
| Datei-Lifecycle (processed/error) | ✅ |
| Auto-Retry (15 min, max 3) | ✅ |
| Retention-Job (30 Tage) | ✅ |
| Web-UI Dashboard + Historie + Detail | ✅ |
| Live-Updates via SSE | ✅ |
| Docker / Compose-Integration | ✅ |

**MVP vollständig umgesetzt.** 41 Tests grün, `ruff` sauber, Docker-Image baut und startet.
Feature-Doku unter `feature-documentation/`.

## Zusatz-Feature: Paperless-Integration (GiroCode & SevDesk) — entkoppelt

Unabhängig vom OCR-Veredelungspfad. Lector liest Rechnungen über den Paperless-Dokumententyp,
erzeugt GiroCodes und exportiert getaggte Belege nach SevDesk; Status wird ans Paperless-
Dokument zurückgeschrieben. Standardmäßig deaktiviert (`FEATURE_PAPERLESS_SYNC=false`).

| Feature | Status |
|---|---|
| Paperless-REST-Client (lesen/zurückschreiben, `app/paperless.py`) | ✅ |
| GiroCode-Extraktion E-Rechnung (UBL/CII) + OCR-Heuristik (`app/girocode.py`) | ✅ |
| EPC069-12-QR-Erzeugung (segno, SVG) | ✅ |
| SevDesk-Beleg-Upload (`app/sevdesk.py`) | ✅ |
| Periodischer Sync + UI-Aktionen (`app/paperless_sync.py`, Worker-Loop) | ✅ |
| Neue Tabellen `paperless_invoices` / `invoice_events` | ✅ |
| Rückschrieb: Custom Fields + Tags + Notiz (Auto-Anlage) | ✅ |
| Web-UI „Rechnungen" + GiroCode-Anzeige + Aktionen + SSE | ✅ |
| Rechnungs-UI: Dokumentdatum, sortierbare Spalten, Dokumentvorschau/-Sprung | ✅ |
| Empfänger-Zuordnung pro Dokument (Paperless select-Feld, `/empfaenger`) | ✅ |
| KI-Empfänger-Vorschlag (Anthropic, `app/recipient_llm.py`) — einzeln + Batch, Auto-Apply | ✅ |
| Tabelle `document_recipients` (KI-Vorschlag-Cache) | ✅ |

82 Tests grün. `ruff` sauber.
Feature-Doku unter `feature-documentation/paperless-integration/`
(neu: `rechnungs-ui.md`, `empfaenger-zuordnung.md`).
Empfänger-Feature **live gegen die Paperless-Instanz verifiziert**: select-Feld-Auflösung,
`custom_field_query`-Filter „ohne Empfänger" (1504 Dok.), Setzen/Leeren des Feldes (reversibel)
und KI-Vorschlag (korrekte Zuordnung bzw. „unbekannt") end-to-end getestet. Dokumentdatum (`created`) und Vorschau-Endpoint
(`/preview/`, liefert `application/pdf` mit `X-Frame-Options: SAMEORIGIN`) gegen die
Live-Paperless-Instanz verifiziert — daher wird die Vorschau über einen Lector-Proxy
ausgeliefert.

**Zu verifizieren (benötigt Zugangsdaten):** End-to-End gegen echte Paperless-Instanz
(Token/URL/Dokumententyp-Name) und echtes SevDesk-Konto (API-Token, Systemversion 2.0 für
E-Rechnungs-Belege). Bisher offline + via TestClient verifiziert.

## Verbleibend / zu verifizieren

- **End-to-End mit echtem Document AI:** Bisher mit Fake-Adapter und über den
  E-Rechnungs-Bypass live getestet. Der OCR-Weg mit echten GCP-Credentials steht noch aus
  (benötigt `GCP_PROJECT_ID`, `DOCAI_PROCESSOR_ID`, Service-Account-JSON).

## Bewusste Abweichungen vom PRD-Tech-Stack

- UI ohne HTMX/Tailwind-Laufzeit: serverseitiges Jinja2 + offline-CSS + Vanilla-JS-SSE
  (LAN-only, keine Cloud-/Node-Abhängigkeit). Funktional identisch (Live-Updates via SSE).
- `pypdfium2` ergänzt für PDF→Bild-Rasterung (keine System-Abhängigkeit).
- **Kein lokales Auto-Rotate** (PRD §3.1 nennt es als Vorverarbeitungsschritt): Die Heuristik
  über die Varianz der Zeilensummen kann 0° nicht von 180° (bzw. 90° nicht von 270°)
  unterscheiden — die Werte sind mathematisch identisch, die Entscheidung fiel nur über den
  Fließkomma-Rundungsfehler und drehte ~22 % korrekt ausgerichteter Seiten zufällig (oft auf
  den Kopf). Schritt entfernt; Orientierung übernimmt Document AI. `PREPROCESS_AUTOROTATE`
  entfällt. Siehe `feature-documentation/bildvorverarbeitung.md`.

## Nice-to-have (später)

- Weitere OCR-Adapter (Cloud Vision, AWS Textract) — Interface vorbereitet.
- Confidence-Score-Auswertung mit Qualitätswarnung im UI.
