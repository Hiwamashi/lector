# Scaleway-Registry-Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Das Lector-Image liegt als Multi-Arch-Image (amd64 + arm64) in der Scaleway Container Registry, und das Zettlab NAS zieht es per `docker compose pull` ohne Repo-Kopie und ohne lokalen Build.

**Architecture:** Ein Bash-Skript auf dem Entwicklungs-Mac baut per `docker buildx` ein Multi-Arch-Image und pusht es unter zwei Tags (`latest`, `git-<sha>`) in einen bereits vorhandenen, öffentlichen Registry-Namespace. Beide Tags sind OCI-Manifest-Listen, sodass jeder Host automatisch seine Architektur zieht und die Compose-Zeile überall identisch bleibt. Build/Push und der Rollout aufs NAS sind bewusst getrennte, manuelle Schritte.

**Tech Stack:** Bash, `docker buildx` (containerd Image Store, QEMU), Scaleway Container Registry, Docker Compose v2, pytest.

**Spec:** `docs/superpowers/specs/2026-07-29-scaleway-registry-deployment-design.md`

## Global Constraints

- Registry-Endpoint: `rg.nl-ams.scw.cloud/krinke-dockersolutions` — Region `nl-ams`, Namespace-ID `e115d876-8b78-4b88-bc99-965065e27837`, `is_public: true`.
- Image-Name: `lector`. Tags: `latest` und `git-<short-sha>`. **Keine** arch-spezifischen Tags.
- Plattform-Liste: `linux/amd64,linux/arm64` — fest verdrahtet, nicht parametrisierbar.
- Nur committete Zustände werden gepusht. Kein `-dirty`-Tag, kein `--allow-dirty`.
- Der Scaleway Secret Key wird vom Skript nicht gelesen, nicht als Parameter akzeptiert und nicht aus Env-Variablen bezogen. Login ausschließlich manuell und einmalig.
- Auf dem NAS ist **kein** `docker login` nötig (öffentlicher Namespace).
- Code-Kommentare und Doku auf Deutsch, passend zum Bestand.
- ruff: `line-length = 100`, Regeln `E,F,I,UP,B`, `target-version = py312`.
- Kein Node-Buildchain, keine CI, kein Watchtower.

---

## File Structure

| Datei | Verantwortung |
|---|---|
| `scripts/push-image.sh` (neu) | Baut Multi-Arch, pusht, verifiziert den Index. Deployt **nicht**. |
| `tests/test_push_image_script.py` (neu) | Prüft Tag-Ableitung, Worktree-Gate und Login-Gate über `--dry-run` — ohne Docker-Aufruf. |
| `tests/test_compose_files.py` (neu) | Regressionstest: der `lector`-Service verweist auf die Registry und hat kein aktives `build:`. |
| `docker-compose.example.yml` (ändern, Z. 81-85) | Registry-Image als Standardweg, `build:` nur als Kommentar. |
| `.mynas.docker-compose.yml` (ändern, Z. 69) | NAS-Vorlage. **Nicht in Git** — wird nicht committet. |
| `pyproject.toml` (ändern) | `pyyaml` als dev-Dependency für den Compose-Test. |
| `feature-documentation/registry-deployment.md` (neu) | Doku des Deployment-Wegs. |
| `feature-documentation/docker-deployment.md` (ändern) | Querverweis unter `## Image`. |
| `README.md` (ändern, Z. 194-238) | Abschnitt „2. Lector-Image auf den NAS bringen" wird ersetzt — die dort beschriebenen drei Wege (NAS-Build / Docker Hub / Tar-Kopie) sind überholt. |
| `prd/PROGRESS.md` (ändern) | Fortschrittseintrag; NAS-Rollout bleibt offen. |

**Task-Reihenfolge:** Task 1 (Skript) → Task 2 (Compose) → Task 3 (echter Push + Verifikation) → Task 4 (Doku). Task 4 kommt zuletzt, weil die Doku erst nach Task 3 belegte Aussagen treffen kann statt Vermutungen.

---

### Task 1: Push-Skript mit Worktree- und Login-Gate

**Files:**
- Create: `scripts/push-image.sh`
- Test: `tests/test_push_image_script.py`

**Interfaces:**
- Consumes: nichts (erste Task).
- Produces: ausführbares `scripts/push-image.sh` mit zwei Aufrufformen:
  - `./scripts/push-image.sh` — baut und pusht, Exit 0 bei Erfolg.
  - `./scripts/push-image.sh --dry-run` — führt Login- und Worktree-Gate aus, gibt den Build-Befehl als eine Zeile mit Prefix `[dry-run] ` auf stdout aus, baut **nicht**, Exit 0.
  - Exit ≠ 0 mit Meldung auf **stderr** bei fehlendem Login oder schmutzigem Worktree.
  - Env-Override `DOCKER_CONFIG` wird respektiert (Verzeichnis, in dem `config.json` liegt) — genau das macht das Login-Gate testbar.

- [ ] **Step 1: Testdatei anlegen (failing test)**

Erstelle `tests/test_push_image_script.py`:

```python
"""Prueft die Gates des Push-Skripts, ohne Docker aufzurufen.

Alle Tests laufen ueber `--dry-run`: die Gates (Login, sauberer Worktree) und
die Tag-Ableitung greifen dort vollstaendig, der eigentliche Build nicht.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "push-image.sh"
REGISTRY = "rg.nl-ams.scw.cloud/krinke-dockersolutions"
REGISTRY_HOST = "rg.nl-ams.scw.cloud"


def _git(repo: Path, *args: str) -> str:
    """Git im Testrepo, mit fixer Identitaet damit Commits ohne globale Config gehen."""
    out = subprocess.run(
        ["git", "-c", "user.email=test@example.com", "-c", "user.name=Test", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


def _make_repo(tmp_path: Path) -> Path:
    """Mini-Repo mit einer Kopie des Push-Skripts, sauber committet.

    Die zusaetzliche `nutzlast.txt` ist getrackt und dient als Objekt fuer den
    Dirty-Test: das Skript selbst darf dafuer nicht veraendert werden, denn ein
    ueberschriebenes Skript wuerde gar nichts mehr pruefen und der Test waere
    gruen, ohne das Gate zu beruehren.
    """
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, repo / "scripts" / "push-image.sh")
    (repo / "scripts" / "push-image.sh").chmod(0o755)
    (repo / "nutzlast.txt").write_text("original\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    return repo


def _docker_config(tmp_path: Path, host: str | None = REGISTRY_HOST) -> Path:
    """Docker-Config-Verzeichnis; host=None erzeugt eine Config ohne Login."""
    cfg_dir = tmp_path / "dockercfg"
    cfg_dir.mkdir()
    auths = {host: {}} if host else {}
    (cfg_dir / "config.json").write_text(json.dumps({"auths": auths}), encoding="utf-8")
    return cfg_dir


def _run(repo: Path, cfg_dir: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "DOCKER_CONFIG": str(cfg_dir)}
    return subprocess.run(
        ["bash", str(repo / "scripts" / "push-image.sh"), *args],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )


def test_dry_run_baut_beide_plattformen_und_beide_tags(tmp_path):
    repo = _make_repo(tmp_path)
    sha = _git(repo, "rev-parse", "--short", "HEAD")

    res = _run(repo, _docker_config(tmp_path), "--dry-run")

    assert res.returncode == 0, res.stderr
    assert "--platform linux/amd64,linux/arm64" in res.stdout
    assert f"{REGISTRY}/lector:latest" in res.stdout
    assert f"{REGISTRY}/lector:git-{sha}" in res.stdout
    assert "--push" in res.stdout


def test_dry_run_baut_nicht_wirklich(tmp_path):
    """Der Build-Befehl wird nur ausgegeben, nicht ausgefuehrt."""
    repo = _make_repo(tmp_path)

    res = _run(repo, _docker_config(tmp_path), "--dry-run")

    assert res.stdout.count("[dry-run]") == 1


def test_schmutziger_worktree_bricht_ab(tmp_path):
    repo = _make_repo(tmp_path)
    (repo / "neu.txt").write_text("uncommittet", encoding="utf-8")

    res = _run(repo, _docker_config(tmp_path), "--dry-run")

    assert res.returncode != 0
    assert "sauber" in res.stderr
    assert "[dry-run]" not in res.stdout


def test_geaenderte_datei_bricht_ab(tmp_path):
    """Auch eine Aenderung an einer getrackten Datei zaehlt als schmutzig.

    Geaendert wird `nutzlast.txt`, nicht das Skript: ein ueberschriebenes Skript
    wuerde nichts mehr pruefen und der Test waere aus dem falschen Grund gruen.
    """
    repo = _make_repo(tmp_path)
    (repo / "nutzlast.txt").write_text("geaendert\n", encoding="utf-8")

    res = _run(repo, _docker_config(tmp_path), "--dry-run")

    assert res.returncode != 0
    assert "sauber" in res.stderr
    assert "[dry-run]" not in res.stdout


def test_fehlender_login_bricht_ab(tmp_path):
    repo = _make_repo(tmp_path)

    res = _run(repo, _docker_config(tmp_path, host=None), "--dry-run")

    assert res.returncode != 0
    assert "docker login" in res.stderr
    assert "[dry-run]" not in res.stdout


def test_fehlende_docker_config_bricht_ab(tmp_path):
    """Gar keine config.json ist kein Crash, sondern dieselbe klare Meldung."""
    repo = _make_repo(tmp_path)
    leer = tmp_path / "leer"
    leer.mkdir()

    res = _run(repo, leer, "--dry-run")

    assert res.returncode != 0
    assert "docker login" in res.stderr
```

- [ ] **Step 2: Tests laufen lassen, Fehlschlag bestätigen**

Run: `uv run pytest tests/test_push_image_script.py -v`
Expected: Alle Tests FAIL — `shutil.copy` scheitert, weil `scripts/push-image.sh` noch nicht existiert (`FileNotFoundError`).

- [ ] **Step 3: Skript schreiben**

Erstelle `scripts/push-image.sh`:

```bash
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
```

- [ ] **Step 4: Skript ausführbar machen**

Run: `chmod +x scripts/push-image.sh`

- [ ] **Step 5: Tests laufen lassen, alle grün**

Run: `uv run pytest tests/test_push_image_script.py -v`
Expected: 6 Tests PASS.

Falls `test_dry_run_baut_beide_plattformen_und_beide_tags` fehlschlägt, weil `--platform linux/amd64,linux/arm64` nicht als zusammenhängender String in der Ausgabe steht: `"${BUILD_CMD[*]}"` fügt die Array-Elemente mit einem Leerzeichen zusammen, `--platform` und der Wert sind zwei Elemente — der erwartete String entsteht also korrekt. Ein Fehlschlag deutet dann auf eine geänderte `PLATFORMS`-Konstante hin.

- [ ] **Step 6: ruff über die neue Testdatei**

Run: `uv run ruff check tests/test_push_image_script.py`
Expected: `All checks passed!`

- [ ] **Step 7: Commit**

```bash
git add scripts/push-image.sh tests/test_push_image_script.py
git commit -m "feat: Push-Skript fuer Multi-Arch-Image in Scaleway-Registry

Baut amd64+arm64 als Manifest-Liste, pusht latest + git-<sha> und
verifiziert den Index. Bricht bei fehlendem Login oder schmutzigem
Worktree ab, damit jedes SHA-Tag aus dem Repo reproduzierbar bleibt."
```

---

### Task 2: Compose-Dateien auf das Registry-Image umstellen

**Files:**
- Modify: `docker-compose.example.yml:81-85`
- Modify: `.mynas.docker-compose.yml:69` (nicht in Git — **nicht** committen)
- Modify: `pyproject.toml` (dev-Dependency `pyyaml`)
- Test: `tests/test_compose_files.py`

**Interfaces:**
- Consumes: den Registry-Pfad aus Task 1 (`rg.nl-ams.scw.cloud/krinke-dockersolutions/lector:latest`).
- Produces: nichts, was spätere Tasks im Code konsumieren. Task 3 setzt aber voraus, dass `.mynas.docker-compose.yml` bereits auf das Registry-Image zeigt.

**Warum ein Test:** `build:` neben `image:` lässt Compose **bauen** statt pullen — auf dem NAS ein Fehlschlag, weil der Build-Kontext fehlt. Der Test hält diese Regression fest, die sich sonst leise wieder einschleicht.

- [ ] **Step 1: pyyaml als dev-Dependency ergänzen**

In `pyproject.toml`, Abschnitt `[project.optional-dependencies]`, `dev`-Liste — vorher:

```toml
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "ruff>=0.7",
]
```

nachher:

```toml
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "ruff>=0.7",
    "pyyaml>=6.0",
]
```

`pyyaml` ist zur Laufzeit bereits transitiv über `uvicorn[standard]` vorhanden. Es hier explizit zu führen macht den Test unabhängig davon, ob uvicorn diese Abhängigkeit künftig fallen lässt.

- [ ] **Step 2: Dependency installieren**

Run: `uv sync --extra dev`
Expected: läuft durch, `pyyaml` ist im Lockfile.

- [ ] **Step 3: Testdatei anlegen (failing test)**

Erstelle `tests/test_compose_files.py`:

```python
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
```

- [ ] **Step 4: Tests laufen lassen, Fehlschlag bestätigen**

Run: `uv run pytest tests/test_compose_files.py -v`
Expected: `test_lector_nutzt_registry_image` FAIL (`assert 'lector:latest' == 'rg.nl-ams.scw.cloud/...'`), `test_lector_hat_keinen_aktiven_build_key` FAIL (`build` ist vorhanden), `test_build_alternative_bleibt_als_kommentar_dokumentiert` FAIL.

- [ ] **Step 5: `docker-compose.example.yml` anpassen**

Zeilen 81-85 — vorher:

```yaml
  lector:
    build: .                      # baut Lector aus dem Dockerfile dieses Repos
    image: lector:latest          # Tag fuer das gebaute Image
    # Liegt diese Compose ausserhalb des Repos, stattdessen den Build-Kontext
    # auf den Repo-Pfad zeigen lassen, z.B.  build: ./lector
```

nachher:

```yaml
  lector:
    image: rg.nl-ams.scw.cloud/krinke-dockersolutions/lector:latest
    # Multi-Arch-Image (amd64 + arm64) aus der Scaleway-Registry. Der Host zieht
    # automatisch seine Architektur, die Zeile ist auf NAS und Mac identisch.
    # Aktualisieren:  docker compose pull lector && docker compose up -d lector
    # Rollback:       :latest durch ein :git-<sha>-Tag ersetzen
    #
    # Nur fuer lokale Entwicklung statt des Registry-Images:
    #   build: .
    # ACHTUNG: build und image gemeinsam lassen Compose bauen statt pullen --
    # auf dem NAS scheitert das, weil dort kein Build-Kontext liegt.
```

- [ ] **Step 6: Tests laufen lassen, alle grün**

Run: `uv run pytest tests/test_compose_files.py -v`
Expected: 3 Tests PASS.

- [ ] **Step 7: Gesamte Testsuite laufen lassen**

Run: `uv run pytest -q`
Expected: alle Tests grün (Bestand war 83 Tests + 6 aus Task 1 + 3 aus dieser Task). Kein Test darf durch die Compose-Änderung brechen.

- [ ] **Step 8: ruff über die neue Testdatei**

Run: `uv run ruff check tests/test_compose_files.py`
Expected: `All checks passed!`

- [ ] **Step 9: `.mynas.docker-compose.yml` anpassen (nicht committen)**

Zeile 69 — vorher `    image: lector:latest`, nachher:

```yaml
    image: rg.nl-ams.scw.cloud/krinke-dockersolutions/lector:latest
```

Diese Datei ist per `.gitignore` **nicht** in Git und enthält Klartext-Tokens. Sie darf in keinem `git add` auftauchen.

- [ ] **Step 10: Prüfen, dass die NAS-Datei nicht im Staging landet**

Run: `git status --porcelain`
Expected: `.mynas.docker-compose.yml` erscheint **nicht** in der Ausgabe (sie ist ignoriert). Erscheint sie doch, vor dem Commit stoppen und die `.gitignore` prüfen.

- [ ] **Step 11: Commit**

```bash
git add docker-compose.example.yml pyproject.toml uv.lock tests/test_compose_files.py
git commit -m "feat: Beispiel-Compose zieht Lector aus der Scaleway-Registry

build: entfaellt als aktiver Key -- gemeinsam mit image: wuerde Compose
bauen statt pullen, was auf dem NAS ohne Build-Kontext scheitert. Ein
Test haelt das fest. pyyaml wird dafuer explizite dev-Dependency."
```

---

### Task 3: Erster echter Push und Verifikation

**Files:** keine Änderungen — diese Task führt aus und belegt.

**Interfaces:**
- Consumes: `scripts/push-image.sh` (Task 1), angepasste Compose-Dateien (Task 2).
- Produces: die Tatsache, dass beide Tags mit beiden Architekturen in der Registry liegen und der arm64-Container startet. Task 4 dokumentiert diese Ergebnisse — ohne sie wären die Doku-Aussagen Vermutungen.

**Diese Task hat keinen pytest-Anteil.** Sie prüft Docker-Build, Registry und Containerstart; das lässt sich nur durch Ausführen belegen, nicht durch Unit-Tests.

- [ ] **Step 1: Registry-Login sicherstellen**

Run: `docker login rg.nl-ams.scw.cloud -u nologin --password-stdin`
Der Scaleway **Secret Key** ist das Passwort. Bei `--password-stdin` wird er eingegeben bzw. eingefügt und mit Strg-D abgeschlossen — so landet er nicht in der Shell-History.

Expected: `Login Succeeded`.

Ist kein Secret Key vorhanden, in der Scaleway-Konsole unter *IAM → API-Schlüssel* einen erzeugen. Er wird nur bei der Erstellung angezeigt.

- [ ] **Step 2: Dry-Run gegen das echte Repo**

Run: `./scripts/push-image.sh --dry-run`
Expected: eine `[dry-run]`-Zeile mit `--platform linux/amd64,linux/arm64`, beiden Tags und dem aktuellen Short-SHA. Bricht es mit „Worktree ist nicht sauber" ab, sind noch Änderungen offen — committen und erneut versuchen.

- [ ] **Step 3: Echten Build und Push ausführen**

Run: `./scripts/push-image.sh`
Expected: Exit 0, Abschluss mit „Beide Plattformen im Index."

Der `amd64`-Teil läuft per QEMU-Emulation und dauert deutlich länger als der native `arm64`-Teil; beim ersten Build ohne Cache sind mehrere Minuten normal. Bricht der Build im `amd64`-Zweig ab, weil ein Paket kein amd64-Wheel liefert und die Quell-Kompilierung scheitert, ist das ein echter Befund — dann in Task 4 dokumentieren und die Plattformwahl neu bewerten, **nicht** stillschweigend auf arm64-only zurückfallen.

- [ ] **Step 4: Manifest-Liste unabhängig prüfen**

Run: `docker buildx imagetools inspect rg.nl-ams.scw.cloud/krinke-dockersolutions/lector:latest`
Expected: die Ausgabe listet `MediaType: application/vnd.oci.image.index.v1+json` und **zwei** Einträge, `linux/amd64` und `linux/arm64`.

Das prüft dasselbe wie das Skript, aber mit eigenen Augen — bei einem Gate, dessen Verletzung erst auf dem NAS auffällt, ist die doppelte Prüfung angemessen.

- [ ] **Step 5: Tags in der Registry prüfen**

Prüfe über die Scaleway-API (Region `nl-ams`, Namespace-ID `e115d876-8b78-4b88-bc99-965065e27837`), dass das Image `lector` existiert und die Tags `latest` sowie `git-<sha>` vorhanden sind. Der SHA muss dem aus Step 2/3 entsprechen.

Expected: beide Tags vorhanden.

- [ ] **Step 6: arm64-Container lokal starten**

```bash
docker run --rm --platform linux/arm64 \
  -e OCR_PROVIDER=documentai \
  -p 8099:8001 \
  rg.nl-ams.scw.cloud/krinke-dockersolutions/lector:latest
```

Expected: uvicorn startet und lauscht auf Port 8001 im Container.

- [ ] **Step 7: arm64-Container beantwortet Anfragen**

In einer zweiten Shell: `curl -sS -o /dev/null -w '%{http_code}\n' http://localhost:8099/`
Expected: eine HTTP-Antwort (`200`, oder ein anderer Code, aber **keine** Verbindungsverweigerung).

Damit ist belegt, dass Lector unter arm64 wirklich läuft. Dass für numpy, opencv-headless und pypdfium2 arm64-Wheels existieren, ist allein kein Beweis — der Prozess muss gestartet sein. Container danach mit Strg-C beenden.

- [ ] **Step 8: Ergebnisse für Task 4 notieren**

Halte fest: den gepushten SHA, die tatsächliche Build-Dauer und ob Step 6/7 auf Anhieb funktionierten. Diese Werte gehen in die Doku und sind später nicht rekonstruierbar.

Kein Commit — diese Task ändert keine Dateien.

---

### Task 4: Dokumentation

**Files:**
- Create: `feature-documentation/registry-deployment.md`
- Modify: `feature-documentation/docker-deployment.md` (Abschnitt `## Image`, Z. 5-12)
- Modify: `README.md:194-238` — bestehender Abschnitt „2. Lector-Image auf den NAS bringen" wird **ersetzt**, nicht ergänzt
- Modify: `prd/PROGRESS.md`

**Interfaces:**
- Consumes: die belegten Ergebnisse aus Task 3 (SHA, Build-Dauer, arm64-Start).
- Produces: nichts für den Code.

**Vorgabe aus CLAUDE.md:** Neue Funktionen gehören als eigene `.md` in `feature-documentation/`; der Entwicklungsfortschritt wird in `prd/PROGRESS.md` fortgeschrieben.

- [ ] **Step 1: `feature-documentation/registry-deployment.md` anlegen**

```markdown
# Deployment über die Scaleway Container Registry

Lector wird nicht auf dem NAS gebaut, sondern als fertiges Multi-Arch-Image aus
einer Registry gezogen. Der Build läuft auf dem Entwicklungs-Mac.

## Registry

| Feld | Wert |
|---|---|
| Endpoint | `rg.nl-ams.scw.cloud/krinke-dockersolutions` |
| Region | `nl-ams` |
| Sichtbarkeit | öffentlich |
| Image | `lector` |
| Tags | `latest`, `git-<short-sha>` |

Weil der Namespace öffentlich ist, braucht das **NAS keine Zugangsdaten**.
`docker compose pull` funktioniert dort ohne `docker login`.

## Architektur: eine Manifest-Liste, zwei Plattformen

Beide Tags sind OCI-Manifest-Listen über `linux/amd64` und `linux/arm64`:

    lector:latest
      ├── linux/amd64   → Zettlab NAS (Intel)
      └── linux/arm64   → Entwicklungs-Mac (Apple Silicon)

Jeder Host zieht automatisch seine Architektur, die Compose-Zeile ist überall
identisch. Es gibt **keine** arch-spezifischen Tags — die würden die
Architekturwahl in eine manuell gepflegte Textstelle verlagern.

## Einmalige Einrichtung auf dem Mac

    docker login rg.nl-ams.scw.cloud -u nologin --password-stdin

Benutzername ist bei Scaleway konstant `nologin`, das Passwort ist der
**Secret Key** eines API-Schlüssels (Scaleway-Konsole → IAM → API-Schlüssel).
Das Credential landet im Docker-Credential-Store; das Push-Skript liest den
Key niemals selbst.

Voraussetzung für Multi-Arch-Builds ist der containerd Image Store in Docker
Desktop. Ist er aktiv, genügt der Default-Builder — ein eigener
`docker-container`-Builder ist nicht nötig. Prüfen mit:

    docker buildx ls          # muss linux/amd64 und linux/arm64 listen

## Bauen und pushen

    ./scripts/push-image.sh              # baut, pusht, verifiziert den Index
    ./scripts/push-image.sh --dry-run    # zeigt nur, was passieren würde

Das Skript bricht **vor** dem Build ab, wenn

- kein Registry-Login vorliegt (sonst fiele das erst nach Minuten
  Emulations-Build auf), oder
- der Worktree nicht sauber ist.

### Warum kein Push aus schmutzigem Worktree

Zwei verschiedene unkommittierte Zustände auf demselben HEAD ergäben denselben
Tag, und der zweite Push überschriebe den ersten stillschweigend. Ein Rollback
auf so ein Tag landet bei Code, der aus dem Repo nicht rekonstruierbar ist —
womit der Zweck der SHA-Tags entfällt. Für schnelle Zwischenstände ist der
lokale Build der richtige Weg:

    docker buildx build --platform linux/arm64 -t lector:dev --load .

Der `amd64`-Teil des Multi-Arch-Builds läuft auf Apple Silicon per
QEMU-Emulation und dauert daher merklich länger als der native `arm64`-Teil.

## Rollout auf dem NAS

Im Ordner des Paperless-Stacks (`Teams/Docker/paperless-ngx-stack`):

    ssh sascha@<NAS-IP>
    cd Teams/Docker/paperless-ngx-stack
    docker compose pull lector
    docker compose up -d lector

Ein `docker login` ist hier nicht nötig — der Namespace ist öffentlich.

## Rollback

`:latest` in der Compose des NAS durch den zuletzt funktionierenden
`:git-<sha>` ersetzen, dann erneut `pull` und `up -d`:

    image: rg.nl-ams.scw.cloud/krinke-dockersolutions/lector:git-759da7f

## Fehlerbilder

| Symptom | Ursache | Behebung |
|---|---|---|
| `exec format error` beim Containerstart | Image enthält die Architektur des NAS nicht | `docker buildx imagetools inspect …:latest` — beide Plattformen müssen im Index stehen |
| Compose baut auf dem NAS statt zu pullen | `build:` steht neben `image:` | `build:` auskommentieren; `tests/test_compose_files.py` hält das fest |
| Push scheitert nach langem Build | Registry-Login fehlt | `docker login rg.nl-ams.scw.cloud -u nologin --password-stdin` |
| Skript bricht mit „Worktree ist nicht sauber" ab | offene Änderungen | committen, oder lokal ohne Push bauen (siehe oben) |

## Secrets

Das Image enthält keine Secrets. Das `Dockerfile` kopiert nur
`pyproject.toml`, `uv.lock`, `README.md` und `app/`; `.dockerignore` schließt
zusätzlich `.env` und `secrets` aus. Konfiguration kommt ausschließlich über
Umgebungsvariablen und Volumes aus der Compose. Das ist wichtig, weil das
Image öffentlich abrufbar ist.
```

- [ ] **Step 2: Querverweis in `feature-documentation/docker-deployment.md`**

Am Ende des Abschnitts `## Image` (vor `## Compose (Full-Stack)`) einfügen:

```markdown
Für den Betrieb auf dem NAS wird das Image nicht lokal gebaut, sondern als
Multi-Arch-Image aus der Scaleway Container Registry gezogen — siehe
[registry-deployment.md](registry-deployment.md).
```

- [ ] **Step 3: README-Abschnitt „2. Lector-Image auf den NAS bringen" ersetzen**

**Kein neuer Abschnitt** — `README.md:194-238` beschreibt bereits drei Wege („Es gibt (noch) kein veröffentlichtes Lector-Image …": A auf dem NAS bauen, B Registry mit Docker Hub/GHCR, C Tar-Datei kopieren). Diese Zeilen werden **vollständig ersetzt**. Sie stehen im Widerspruch zum neuen Weg, und drei parallel gepflegte Varianten veralten unweigerlich — zwei davon würde niemand mehr benutzen.

Ersetze `README.md:194-238` (von `### 2. Lector-Image auf den NAS bringen` bis einschließlich `Bei B und C im Compose ... eintragen.`) durch:

````markdown
### 2. Lector-Image auf den NAS bringen

Das Image liegt als Multi-Arch-Image (amd64 + arm64) in der Scaleway Container
Registry und wird auf dem NAS nur noch gezogen — der Build läuft auf dem
Entwicklungsrechner. Da der Namespace öffentlich ist, braucht das NAS **keine**
Zugangsdaten.

Einmalig auf dem Entwicklungsrechner anmelden (Passwort = Scaleway Secret Key):

```bash
docker login rg.nl-ams.scw.cloud -u nologin --password-stdin
```

Bauen und pushen:

```bash
./scripts/push-image.sh
```

Das Skript baut für `linux/amd64` und `linux/arm64`, pusht die Tags `latest` und
`git-<sha>` und prüft, dass beide Architekturen in der Manifest-Liste stehen. Es
bricht ab, wenn der Registry-Login fehlt oder der Worktree nicht sauber ist —
in die Registry gelangen nur committete Zustände, damit jedes `git-<sha>`-Tag
aus dem Repo reproduzierbar bleibt und als Rollback-Ziel taugt.

Auf dem NAS:

```bash
ssh sascha@<NAS-IP>
cd Teams/Docker/paperless-ngx-stack
docker compose pull lector
docker compose up -d lector
```

Rollback auf einen früheren Stand: in der Compose `:latest` durch das
gewünschte `:git-<sha>` ersetzen, dann erneut `pull` und `up -d`.

Details, Fehlerbilder und die Begründung der Architekturwahl:
[feature-documentation/registry-deployment.md](feature-documentation/registry-deployment.md).
````

Prüfe nach dem Ersetzen, dass der Registry-Pfad im README mit dem im Skript übereinstimmt und der folgende Abschnitt `### 3. Lector-Service in den Paperless-Compose aufnehmen` unbeschädigt anschließt.

- [ ] **Step 4: `prd/PROGRESS.md` fortschreiben**

Füge nach dem Abschnitt „Zusatz-Feature: Paperless-Integration …" (vor „## Verbleibend / zu verifizieren") ein — Tabellenformat wie im Bestand:

```markdown
## Zusatz-Feature: Image-Deployment über Scaleway Container Registry

Das Image wird nicht mehr auf dem NAS gebaut, sondern als Multi-Arch-Image
(amd64 + arm64) aus `rg.nl-ams.scw.cloud/krinke-dockersolutions` gezogen. Build
und Push laufen auf dem Entwicklungsrechner, der Rollout aufs NAS bleibt ein
getrennter manueller Schritt.

| Feature | Status |
|---|---|
| Push-Skript Multi-Arch amd64+arm64 als Manifest-Liste (`scripts/push-image.sh`) | ✅ |
| Tags `latest` + `git-<sha>`, Index nach dem Push verifiziert | ✅ |
| Gate: kein Push ohne Registry-Login | ✅ |
| Gate: kein Push aus schmutzigem Worktree (SHA-Tags reproduzierbar) | ✅ |
| Compose auf Registry-Image umgestellt, `build:` deaktiviert + Regressionstest | ✅ |
| arm64-Lauffähigkeit lokal belegt (Container gestartet, HTTP-Antwort) | ✅ |
| Rollout auf dem NAS (`compose pull` + `up -d`) | ⏳ offen — nur vom Anwender prüfbar |
```

Ergänze zusätzlich unter „## Verbleibend / zu verifizieren" eine Zeile im dort verwendeten Format:

```markdown
- Registry-Deployment: `docker compose pull lector && docker compose up -d lector`
  auf dem NAS (`Teams/Docker/paperless-ngx-stack`) ausführen und Port 8001 prüfen.
  Aus der Entwicklungsumgebung nicht verifizierbar.
```

Setze den Rollout-Eintrag **nicht** auf ✅, solange keine Bestätigung vom Anwender vorliegt.

- [ ] **Step 5: Doku gegen die Realität prüfen**

Lies die neue `registry-deployment.md` und vergleiche jeden Befehl mit dem, was in Task 3 tatsächlich ausgeführt wurde. Weicht etwas ab (Pfade, Optionen, Ausgaben), korrigiere die Doku — nicht die Erinnerung.

- [ ] **Step 6: Knowledge Graph aktualisieren**

Run: `graphify update .`
Expected: läuft durch. (Vorgabe aus CLAUDE.md nach Code-Änderungen; AST-only, keine API-Kosten.)

- [ ] **Step 7: Commit**

```bash
git add feature-documentation/registry-deployment.md \
        feature-documentation/docker-deployment.md \
        README.md prd/PROGRESS.md
git commit -m "docs: Deployment ueber die Scaleway Container Registry

Neue Feature-Doku mit Registry-Koordinaten, Login, Multi-Arch-Begruendung,
Rollback und Fehlerbildern; Querverweis aus docker-deployment.md,
README-Abschnitt und PROGRESS-Eintrag."
```

Sollte `graphify update .` Dateien in `graphify-out/` verändert haben, in einem getrennten Commit erfassen — Doku und generierte Artefakte nicht vermischen.

---

## Offen nach Abschluss dieses Plans

Der Rollout auf dem NAS (`docker compose pull lector && docker compose up -d lector`, danach Port 8001 prüfen) ist aus der Entwicklungsumgebung **nicht** verifizierbar — es besteht kein Zugriff auf das Zettlab NAS. Dieser Schritt ist als offen zu melden, bis der Anwender ihn bestätigt. Er darf nicht als erledigt dargestellt werden.
