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

ENTRYPOINT ["tini", "--"]
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
