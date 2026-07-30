#!/usr/bin/env bash
# Baut das Lector-Image fuer amd64 + arm64 und schiebt es in die Scaleway-Registry.
#
# Es landen ausschliesslich committete Zustaende in der Registry: die Tags
# git-<sha> muessen aus dem Repo reproduzierbar bleiben, sonst ist ein Rollback
# auf so ein Tag ein Sprung in einen unbekannten Codezustand.
#
#   ./scripts/push-image.sh              baut und pusht
#   ./scripts/push-image.sh --dry-run    prueft nur die Gates, zeigt den Build-Befehl
#
# Der Scaleway Secret Key wird hier nirgends gelesen. Einmalig manuell:
#   docker login rg.nl-ams.scw.cloud -u nologin --password-stdin
set -euo pipefail

REGISTRY="rg.nl-ams.scw.cloud/krinke-dockersolutions"
IMAGE="lector"
PLATFORMS="linux/amd64,linux/arm64"

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=1
elif [[ -n "${1:-}" ]]; then
    echo "FEHLER: unbekanntes Argument '$1' (erlaubt: --dry-run)" >&2
    exit 2
fi

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

REGISTRY_HOST="${REGISTRY%%/*}"

# --- Gate 1: Registry-Login ------------------------------------------------
# Vor dem Build, damit ein fehlendes Credential nicht erst nach Minuten
# QEMU-Emulation auffaellt.
DOCKER_CFG="${DOCKER_CONFIG:-$HOME/.docker}/config.json"
if ! python3 - "$DOCKER_CFG" "$REGISTRY_HOST" <<'PY'
import json
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as fh:
        auths = json.load(fh).get("auths", {})
except (OSError, ValueError):
    sys.exit(1)
sys.exit(0 if sys.argv[2] in auths else 1)
PY
then
    echo "FEHLER: kein Docker-Login fuer $REGISTRY_HOST gefunden." >&2
    echo "Einmalig anmelden (Passwort = Scaleway Secret Key):" >&2
    echo "  docker login $REGISTRY_HOST -u nologin --password-stdin" >&2
    exit 1
fi

# --- Gate 2: sauberer Worktree --------------------------------------------
if [[ -n "$(git status --porcelain)" ]]; then
    echo "FEHLER: Worktree ist nicht sauber." >&2
    echo "Nur committete Zustaende werden gepusht, damit jedes git-<sha>-Tag" >&2
    echo "aus dem Repo reproduzierbar bleibt. Bitte committen." >&2
    echo "Fuer einen schnellen lokalen Test ohne Push:" >&2
    echo "  docker buildx build --platform linux/arm64 -t lector:dev --load ." >&2
    exit 1
fi

SHA="$(git rev-parse --short HEAD)"
TAG_LATEST="$REGISTRY/$IMAGE:latest"
TAG_SHA="$REGISTRY/$IMAGE:git-$SHA"

# --- Bauen und pushen -----------------------------------------------------
BUILD_CMD=(
    docker buildx build
    --platform "$PLATFORMS"
    -t "$TAG_LATEST"
    -t "$TAG_SHA"
    --push
    .
)

if [[ $DRY_RUN -eq 1 ]]; then
    echo "[dry-run] ${BUILD_CMD[*]}"
    exit 0
fi

echo "Baue $PLATFORMS -> $TAG_LATEST + $TAG_SHA"
"${BUILD_CMD[@]}"

# --- Index verifizieren ---------------------------------------------------
# Ein stillschweigend auf eine Architektur reduzierter Index faellt sonst erst
# auf dem NAS auf, dort als 'exec format error'.
echo "Pruefe Manifest-Liste ..."
INSPECT="$(docker buildx imagetools inspect "$TAG_LATEST")"
for plattform in linux/amd64 linux/arm64; do
    if ! grep -q "$plattform" <<<"$INSPECT"; then
        echo "FEHLER: $plattform fehlt im Index von $TAG_LATEST." >&2
        echo "$INSPECT" >&2
        exit 1
    fi
done

echo
echo "Fertig. Beide Plattformen im Index."
echo "Compose-Zeile:"
echo "    image: $TAG_LATEST"
echo "Rollback-Tag dieses Builds:"
echo "    image: $TAG_SHA"
