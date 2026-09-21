# Feature-Dokumentation — Lector

Diese Doku beschreibt die einzelnen Funktionen/Features der Codebase für KI-Coding-Agenten
und Menschen. Pro Feature eine Datei.

## Übersicht der Verarbeitung

```
scan-in → [Watch-Folder] → [Format-/E-Rechnungs-Erkennung]
                               ├─ E-Rechnung → unverändert → consume
                               └─ OCR-Weg → [Seitenextraktion] → [Bildvorverarbeitung]
                                            → [OCR-Adapter (Document AI, Chunking)]
                                            → [Sandwich-PDF] → consume
Original → processed (Erfolg) / error (endgültiger Fehler)
```

## Module ↔ Feature

| Datei | Modul | Feature |
|---|---|---|
| [konfiguration.md](konfiguration.md) | `app/config.py` | ENV-Konfiguration |
| [datenhaltung.md](datenhaltung.md) | `app/db.py`, `app/repository.py`, `app/models.py` | SQLite-Historie |
| [watch-folder.md](watch-folder.md) | `app/watcher.py`, `app/worker.py` | Watch-Folder, Queue, Worker |
| [format-erkennung-erechnung.md](format-erkennung-erechnung.md) | `app/detection.py` | Format-Routing & E-Rechnungs-Bypass |
| [bildvorverarbeitung.md](bildvorverarbeitung.md) | `app/pages.py`, `app/preprocessing.py` | Seitenextraktion & Vorverarbeitung |
| [ocr-adapter.md](ocr-adapter.md) | `app/ocr/` | OCR-Adapter-Interface & Document AI |
| [sandwich-pdf.md](sandwich-pdf.md) | `app/pdfbuilder.py` | Durchsuchbares Sandwich-PDF |
| [pipeline-lifecycle-retry.md](pipeline-lifecycle-retry.md) | `app/pipeline.py`, `app/fileops.py` | Pipeline, Lifecycle, Auto-Retry |
| [seitenobergrenze.md](seitenobergrenze.md) | `app/pages.py`, `app/pipeline.py`, `app/decisions.py` | Seitenobergrenze, Wartezustand & Freigabe |
| [chunk-teilergebnisse.md](chunk-teilergebnisse.md) | `app/ocr/base.py`, `app/ocr/documentai.py`, `app/repository.py` | Bewahrte OCR-Teilergebnisse |
| [retention.md](retention.md) | `app/retention.py` | Retention-Job |
| [web-ui-sse.md](web-ui-sse.md) | `app/main.py`, `app/events.py`, `app/templates/`, `app/static/` | Web-UI & Live-Updates |
| [ui-erscheinungsbild.md](ui-erscheinungsbild.md) | `app/static/app.css`, `app/static/app.js` (Markierung) | Farbtokens, Dunkel-Modus, Zustände, Aufleuchten |
| [paperless-integration/](paperless-integration/README.md) | `app/paperless.py`, `app/girocode.py`, `app/sevdesk.py`, `app/paperless_sync.py` | GiroCode-Anzeige & SevDesk-Export (entkoppelt) |
| [startvalidierung-und-healthcheck.md](startvalidierung-und-healthcheck.md) | `app/config.py`, `app/main.py`, `app/worker.py`, `app/repository.py` | Startvalidierung, `/healthz`, Container-`HEALTHCHECK` |
| [docker-deployment.md](docker-deployment.md) | `Dockerfile`, `docker-compose.example.yml` | Deployment |

## Bewusste Abweichungen vom PRD-Tech-Stack

- **UI ohne HTMX/Tailwind-CDN:** Da der Betrieb LAN-only und ohne Cloud-Anbindung erfolgen
  soll (PRD §3.3) und kein Node-Buildchain gewünscht ist, nutzt das UI serverseitiges Jinja2,
  ein handgeschriebenes, offline-fähiges `app/static/app.css` (im „Werkstatt"-Look) und
  schlankes Vanilla-JS für SSE-getriebene Fragment-Aktualisierungen statt einer
  HTMX-/Tailwind-Laufzeitabhängigkeit. Funktional identisch zur PRD-Vorgabe (Live-Updates via SSE).
- **PDF-Rasterung mit `pypdfium2`:** Für das Rendern von PDF-Seiten zu Bildern (Voraussetzung
  für Vorverarbeitung + Sandwich-Bau) wurde `pypdfium2` ergänzt — keine System-Abhängigkeit,
  pip-installierbar.
