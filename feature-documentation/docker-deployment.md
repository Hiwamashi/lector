# Docker & Compose-Integration

**Dateien:** `Dockerfile`, `.dockerignore`, `docker-compose.example.yml`

## Image

- Basis `python:3.12-slim` + System-Libs für OpenCV-headless (`libglib2.0-0`, `libgl1`) und
  `tini` als Init.
- `uv` installiert Abhängigkeiten aus `pyproject.toml`/`uv.lock` (Layer-Caching: erst Deps ohne
  Projekt, dann Projektcode). `README.md` wird benötigt, weil sie Paket-Metadatum ist.
- Start: `uvicorn app.main:app --host 0.0.0.0 --port 8001` (ein Prozess für UI/API + Worker).
  **`PORT` (ENV, siehe [konfiguration.md](konfiguration.md)) wirkt im Container nicht:**
  `Dockerfile` verdrahtet Port `8001` fest in `EXPOSE`, `CMD` und dem `HEALTHCHECK`. Wer
  `command:` im Compose überschreibt, um `PORT` zu honorieren, bekommt einen Container, der
  auf dem neuen Port lauscht, aber dessen `HEALTHCHECK` weiter gegen `8001` prüft — und
  damit dauerhaft `unhealthy` bleibt.

Für den Betrieb auf dem NAS wird das Image nicht lokal gebaut, sondern als
Multi-Arch-Image aus der Scaleway Container Registry gezogen — siehe
[registry-deployment.md](registry-deployment.md).

## Zustandstest (`HEALTHCHECK`)

`Dockerfile` deklariert einen `HEALTHCHECK` gegen `GET /healthz`
(`--interval=30s --timeout=5s --start-period=120s --retries=3`), derselbe Block liegt am
`lector`-Service in `docker-compose.example.yml`. Er läuft über den Python-Interpreter
(`python -c` mit `urllib.request`) statt über `curl`, weil das Basis-Abbild
(`python:3.12-slim`) weder `curl` noch `wget` enthält — ein Apt-Paket allein dafür würde
das Abbild für etwas vergrößern, das der ohnehin vorhandene Interpreter erledigt.

Dockers `HEALTHCHECK` **markiert nur**: `unhealthy` wird in `docker ps`/`docker compose
ps` sichtbar, startet aber nichts neu (das täte nur Swarm oder ein Zusatzdienst).
`depends_on` bleibt unverändert, kein `condition: service_healthy`. Details zu Prüfumfang,
den einzelnen Zeitwerten und der am Container verifizierten Zustandsfolge (`starting` →
`healthy` nach ~20 s → `unhealthy` nach einem Ausfall mitten im Betrieb) stehen in
[startvalidierung-und-healthcheck.md](startvalidierung-und-healthcheck.md).

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
- Container-Start + `GET /healthz` → je Hintergrundarbeit, Observer und Datenbank ein
  Eintrag, `200` bei gesundem Dienst (Antwortform seit `startvalidierung-und-healthcheck`
  aufgeschlüsselt — vorher unbedingt `{"status":"ok"}`, siehe
  [startvalidierung-und-healthcheck.md](startvalidierung-und-healthcheck.md)), Worker
  startet und überwacht `/scan-in`.
- Der Container-`HEALTHCHECK` erreicht `healthy` am echten Container (`docker compose ps`)
  und wechselt nach dem Abbruch einer Hintergrundarbeit im laufenden Betrieb auf
  `unhealthy` — verifiziert am 2026-09-21, siehe
  [startvalidierung-und-healthcheck.md](startvalidierung-und-healthcheck.md).
