# Lector — OCR-Veredelungsservice. Ein Container, ein Prozess (FastAPI/uvicorn + Worker).
FROM python:3.12-slim

# Laufzeit-Abhängigkeiten für OpenCV (headless) und Bildverarbeitung.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libglib2.0-0 \
        libgl1 \
        tini \
    && rm -rf /var/lib/apt/lists/*

# uv für reproduzierbare Installation aus pyproject/lock.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Erst nur die Abhängigkeiten installieren (Layer-Caching).
COPY pyproject.toml ./
COPY uv.lock* ./
RUN uv sync --no-dev --no-install-project

# Anwendungscode (README wird vom Projekt-Build als Paket-Metadatum benötigt).
COPY README.md ./
COPY app ./app
RUN uv sync --no-dev

# Standard-Ordner (werden i.d.R. als Volumes überschrieben).
RUN mkdir -p /scan-in /consume /processed /error /data /secrets

EXPOSE 8001

# Zustandstest gegen /healthz — über den Interpreter statt "uv run", damit nicht
# nebenbei die Projektumgebung aufgelöst wird (das soll dieser Test nicht prüfen);
# urllib.request ist Standardbibliothek und im Abbild ohnehin vorhanden. Der Aufruf
# prüft den Status ausdrücklich selbst statt sich auf urlopens Standardverhalten bei
# Fehlerstatus zu verlassen — nur 200 gilt als gesund, alles andere lässt das Assert
# fehlschlagen (und schon vorher wirft urlopen bei 503 eine HTTPError).
#
# --start-period großzügig: Der Start umfasst DB-Migrationen und die Auflösung
#   hängengebliebener Vorgänge (resolve_stale_processing), die beliebig viele
#   Vorgänge betreffen kann — während eines völlig regulären Starts soll der
#   Container nicht als ungesund gelten.
# --interval und --retries knapp: Ein echter Ausfall soll zeitnah sichtbar werden,
#   nicht erst nach mehreren Minuten.
# --timeout knapp, aber nicht knapper als die Frist, die die Datenbankprüfung im
#   Endpunkt selbst ansetzt (0,2 s, siehe app/repository.py), sonst schlüge der
#   Zustandstest bei jeder gleichzeitigen Datenbanknutzung fälschlich fehl.
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
    CMD ["python", "-c", "import urllib.request; assert urllib.request.urlopen('http://127.0.0.1:8001/healthz', timeout=5).status == 200"]

ENTRYPOINT ["tini", "--"]
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
