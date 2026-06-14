# Docker & Compose-Integration

**Dateien:** `Dockerfile`, `.dockerignore`, `docker-compose.example.yml`

## Image

- Basis `python:3.12-slim` + System-Libs für OpenCV-headless (`libglib2.0-0`, `libgl1`) und
  `tini` als Init.
- `uv` installiert Abhängigkeiten aus `pyproject.toml`/`uv.lock` (Layer-Caching: erst Deps ohne
  Projekt, dann Projektcode). `README.md` wird benötigt, weil sie Paket-Metadatum ist.
- Start: `uvicorn app.main:app --host 0.0.0.0 --port 8001` (ein Prozess für UI/API + Worker).

## Compose

`docker-compose.example.yml` skizziert Lector als zusätzlichen Service im bestehenden
Paperless-Compose. Volumes: `scan-in`, `consume` (geteilt mit Paperless), `processed`, `error`,
`data`, `secrets:ro`. ENV gemäß [konfiguration.md](konfiguration.md).

## Zwingende Paperless-Vorgabe

Am Paperless-`webserver` muss `PAPERLESS_OCR_MODE: skip` gesetzt werden, damit Tesseract den von
Lector eingebetteten Document-AI-Textlayer **nicht** überschreibt (PRD §4.1).

## Verifiziert

- `docker build -t lector:test .` erfolgreich.
- Container-Start + `GET /healthz` → `{"status":"ok"}`, Worker startet und überwacht `/scan-in`.
