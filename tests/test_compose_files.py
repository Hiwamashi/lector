"""Haelt fest, dass die Beispiel-Compose das Registry-Image nutzt.

Stehen `build:` und `image:` gemeinsam im Service, baut Compose das Image bei
fehlendem lokalen Tag selbst statt es zu pullen. Auf dem NAS scheitert das,
weil dort kein Build-Kontext liegt -- ein Fehler, der leicht zurueckkehrt.
"""

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
