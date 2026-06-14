# Entwicklungsfortschritt — Lector

> Fortlaufend gepflegter Stand der MVP-Umsetzung (siehe `PRD_Lector.md`).
> Legende: ✅ umgesetzt · 🚧 in Arbeit · ⬜ offen

**Stand:** 2026-06-14

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
| Bildvorverarbeitung (Deskew/Auto-Rotate/Kontrast) | ✅ |
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

## Verbleibend / zu verifizieren

- **End-to-End mit echtem Document AI:** Bisher mit Fake-Adapter und über den
  E-Rechnungs-Bypass live getestet. Der OCR-Weg mit echten GCP-Credentials steht noch aus
  (benötigt `GCP_PROJECT_ID`, `DOCAI_PROCESSOR_ID`, Service-Account-JSON).
- **Auto-Rotate 180°:** heuristisch nicht von 0° unterscheidbar (dokumentierte Grenze).

## Bewusste Abweichungen vom PRD-Tech-Stack

- UI ohne HTMX/Tailwind-Laufzeit: serverseitiges Jinja2 + offline-CSS + Vanilla-JS-SSE
  (LAN-only, keine Cloud-/Node-Abhängigkeit). Funktional identisch (Live-Updates via SSE).
- `pypdfium2` ergänzt für PDF→Bild-Rasterung (keine System-Abhängigkeit).

## Nice-to-have (später)

- Weitere OCR-Adapter (Cloud Vision, AWS Textract) — Interface vorbereitet.
- Confidence-Score-Auswertung mit Qualitätswarnung im UI.
