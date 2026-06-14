# Lector

Lokaler OCR-Veredelungsservice **vor** Paperless-ngx. Lector überwacht einen Eingangsordner,
veredelt eingehende Dokumente (Bilder, PDF, TIFF) per Cloud-OCR (Google Document AI) zu
durchsuchbaren „Sandwich"-PDFs und legt sie in den geteilten `consume`-Ordner für den
automatischen Import in Paperless-ngx. E-Rechnungen (XRechnung, ZUGFeRD/Factur-X) werden
deterministisch erkannt und unverändert durchgereicht.

> Vollständige Anforderungen: [`prd/PRD_Lector.md`](prd/PRD_Lector.md) ·
> Stand der Umsetzung: [`prd/PROGRESS.md`](prd/PROGRESS.md)

## Entwicklung

```bash
# Abhängigkeiten installieren (inkl. Dev-Tools)
uv sync --extra dev

# Tests
uv run pytest                     # alle Tests
uv run pytest tests/test_xy.py    # eine Datei
uv run pytest -k name             # einzelner Test nach Muster

# Linting / Formatierung
uv run ruff check .
uv run ruff format .

# Lokal starten
uv run uvicorn app.main:app --reload --port 8001
```

Konfiguration ausschließlich über Umgebungsvariablen (siehe `app/config.py` und PRD §4.5).
Für lokale Entwicklung kann eine `.env` im Projektwurzelverzeichnis genutzt werden.

## Docker

```bash
docker build -t lector .
```

Der Service ist als zusätzlicher Container im bestehenden Paperless-ngx-Compose vorgesehen
(siehe `docker-compose.example.yml`). Wichtig: am Paperless-`webserver`
`PAPERLESS_OCR_MODE: skip` setzen, damit Tesseract den Document-AI-Textlayer nicht überschreibt.
