# Docker & Compose-Integration

**Dateien:** `Dockerfile`, `.dockerignore`, `docker-compose.example.yml`

## Image

- Basis `python:3.12-slim` + System-Libs für OpenCV-headless (`libglib2.0-0`, `libgl1`) und
  `tini` als Init.
- `uv` installiert Abhängigkeiten aus `pyproject.toml`/`uv.lock` (Layer-Caching: erst Deps ohne
  Projekt, dann Projektcode). `README.md` wird benötigt, weil sie Paket-Metadatum ist.
- Start: `uvicorn app.main:app --host 0.0.0.0 --port 8001` (ein Prozess für UI/API + Worker).

## Compose (Full-Stack)

`docker-compose.example.yml` ist ein vollständiger, nachbaubarer Stack: `broker` (Redis), `db`
(PostgreSQL), `webserver` (Paperless-ngx), `gotenberg`, `tika`, `lector` und `paperless-gpt`.
Lector-Volumes: `scan-in`, `consume` (geteilt mit Paperless), `processed`, `error`, `data`,
`secrets:ro`. ENV gemäß [konfiguration.md](konfiguration.md).

Secrets stehen **nicht** im Compose, sondern werden per `${...}` aus einer `.env` eingesetzt
(`cp .env.example .env`). Referenzierte Variablen: `POSTGRES_PASSWORD`, `PAPERLESS_SECRET_KEY`,
`PAPERLESS_ADMIN_USER`, `PAPERLESS_ADMIN_PASSWORD`, `GCP_PROJECT_ID`, `DOCAI_PROCESSOR_ID`,
`PAPERLESS_API_TOKEN`, `ANTHROPIC_API_KEY`.

## paperless-gpt — KI-Tagging ohne OCR

`paperless-gpt` erzeugt Titel/Tags/Korrespondenten per LLM (hier `anthropic`/`claude-sonnet-4-5`).
OCR und Tagging sind getrennte Pipelines: OCR startet nur beim Tag `paperless-gpt-ocr-auto` —
dieser wird **nie** vergeben, da Lector + Document AI das OCR bereits erledigen. Daher sind keine
`OCR_*`-Variablen gesetzt. Das Tagging arbeitet auf dem von Lector eingebetteten und von Paperless
indexierten Textlayer.

Damit der Workflow ohne manuelles Zutun läuft, in Paperless einen Workflow anlegen
(Trigger „Document added" → Aktion „Assign tag: `paperless-gpt-auto`"). Der API-Token für
`PAPERLESS_API_TOKEN` wird in Paperless unter Profil → API-Token erzeugt.

**Gesamtablauf:** `scan-in` → Lector (Document-AI-OCR, Sandwich-PDF) → `consume` → Paperless
importiert/indexiert → Workflow setzt `paperless-gpt-auto` → paperless-gpt ergänzt Metadaten.

## Zwingende Paperless-Vorgabe

Am Paperless-`webserver` muss `PAPERLESS_OCR_MODE: skip` gesetzt werden, damit Tesseract den von
Lector eingebetteten Document-AI-Textlayer **nicht** überschreibt (PRD §4.1).

## Verifiziert

- `docker build -t lector:test .` erfolgreich.
- Container-Start + `GET /healthz` → `{"status":"ok"}`, Worker startet und überwacht `/scan-in`.
