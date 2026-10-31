"""Haelt fest, dass die Beispiel-Compose das Registry-Image nutzt.

Stehen `build:` und `image:` gemeinsam im Service, baut Compose das Image bei
fehlendem lokalen Tag selbst statt es zu pullen. Auf dem NAS scheitert das,
weil dort kein Build-Kontext liegt -- ein Fehler, der leicht zurueckkehrt.
"""

import re
from pathlib import Path

import yaml

COMPOSE = Path(__file__).resolve().parents[1] / "docker-compose.example.yml"
REGISTRY = "rg.nl-ams.scw.cloud/krinke-dockersolutions"


def _lector_service() -> dict:
    with COMPOSE.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)["services"]["lector"]


def test_lector_nutzt_registry_image():
    assert _lector_service()["image"] == f"{REGISTRY}/lector:latest"


def test_lector_hat_keinen_aktiven_build_key():
    assert "build" not in _lector_service()


def test_build_alternative_bleibt_als_kommentar_dokumentiert():
    """Der lokale Build-Weg soll auffindbar bleiben, nur nicht aktiv sein."""
    text = COMPOSE.read_text(encoding="utf-8")
    assert "#   build: ." in text


def test_lector_deklariert_healthcheck():
    """Ohne diesen Block zeigt `docker ps` nie mehr als "Up", obwohl das Abbild
    laut Dockerfile einen HEALTHCHECK mitbringt."""
    assert "healthcheck" in _lector_service()


def test_lector_healthcheck_prueft_healthz_endpunkt():
    """Der Compose-Block ueberschreibt den HEALTHCHECK aus dem Dockerfile komplett und
    ist damit die driftanfaelligere der beiden Stellen: ein auf einen falschen Pfad
    verdrehtes test-Kommando wuerde `docker compose ps` nie mehr "healthy" erreichen
    lassen, ohne dass die blosse Anwesenheitspruefung oben das bemerkt."""
    test_cmd = _lector_service()["healthcheck"]["test"]
    assert "/healthz" in " ".join(test_cmd)


# --- paperless-mcp (Agenten-Zugang, Spec agenten-zugang) ---------------------
#
# Der Stack wird per Komodo mit Auto-Update aller :latest-Images betrieben. Ein
# ungepinnter Community-Dienst mit Zugriff auf Agent-Tokens wuerde dabei ungeprueft
# aktualisiert; ein echter Dienst-Token oder eingeschaltete Embeddings wuerden ihm
# Vollzugriff auf Paperless geben (Design D1, D2, D5).

MCP_IMAGE = "ghcr.io/orellbuehler/paperless-mcp"


def _mcp_service() -> dict:
    with COMPOSE.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)["services"]["paperless-mcp"]


def _mcp_env() -> dict:
    return _mcp_service().get("environment") or {}


def test_mcp_image_ist_auf_exakte_version_gepinnt():
    image = _mcp_service()["image"]
    name, _, tag = image.rpartition(":")
    assert name == MCP_IMAGE
    assert re.fullmatch(r"\d+\.\d+\.\d+", tag), f"kein exakter Versions-Tag: {tag!r}"


def test_mcp_hat_keinen_build_key():
    assert "build" not in _mcp_service()


def test_mcp_spricht_paperless_intern_an():
    assert _mcp_env()["PAPERLESS_URL"] == "http://webserver:8000"


def test_mcp_dienst_token_kommt_aus_platzhalter_variable():
    """Nie ein echter Token in der Vorlage, nie der Paperless-Token von Lector/paperless-gpt."""
    token = str(_mcp_env()["PAPERLESS_TOKEN"])
    assert token == "${PAPERLESS_MCP_SERVICE_TOKEN}"


def test_mcp_semantische_suche_bleibt_aus():
    wert = str(_mcp_env().get("EMBEDDINGS_ENABLED", "false")).strip().lower()
    assert wert not in {"1", "true", "yes"}


def test_mcp_bindet_an_eigene_domain():
    assert str(_mcp_env().get("MCP_ALLOWED_HOSTS", "")).strip()


def test_mcp_laesst_keine_fremden_browser_origins_zu():
    assert not str(_mcp_env().get("MCP_ALLOWED_ORIGINS", "")).strip()
