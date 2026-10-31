# Proposal

## Why

Ein neuer Lector-Stand gelangt heute in drei Handgriffen auf das NAS: `scripts/push-image.sh`
auf dem Mac (der amd64-Teil läuft per QEMU-Emulation und dauert entsprechend), dann SSH aufs
NAS, dann `docker compose pull lector && docker compose up -d lector`. Das ist umständlich und
skaliert nicht auf weitere Stacks, die auf das NAS sollen. Ziel ist ein Ablauf ohne
Handgriffe: `git push` → GitHub Actions baut → Scaleway-Registry → Komodo deployt auf dem NAS.

## What Changes

- **Neu:** GitHub-Actions-Workflow, der bei Push auf `main` (und manuell) ausschließlich nach
  grünem `ruff` und `pytest` ein Multi-Arch-Image (`linux/amd64`, `linux/arm64`) auf nativen
  Runnern baut, als eine Manifest-Liste zusammenführt, den Index prüft und erst dann
  `git-<sha>` und zuletzt `:latest` in die Scaleway-Registry schreibt.
- **Neu:** Pfadfilter: Ein Image entsteht nur, wenn sich bildrelevante Dateien ändern
  (`app/**`, `Dockerfile`, `pyproject.toml`, `uv.lock`, `README.md`, Workflow selbst). Reine
  Doku- oder iOS-Commits starten Lector auf dem NAS nicht neu.
- **Neu:** Push-Zugang aus CI über eine eigene Scaleway-IAM-Application mit Recht nur auf die
  Registry, hinterlegt als GitHub-Secret.
- **BREAKING (Arbeitsweise):** `scripts/push-image.sh` und `tests/test_push_image_script.py`
  entfallen. CI ist der einzige Weg in die Registry; ein `docker login` auf dem Mac ist nicht
  mehr nötig. Lokale Testbuilds laufen weiter per `docker buildx build … --load`.
- Doku (`registry-deployment.md`, README, `PROGRESS.md`) auf den neuen Ablauf umstellen und
  für das Ausrollen auf das NAS auf das Repository `nas-stacks` verweisen.

Nicht Teil dieses Changes: Das Ausrollen selbst (Komodo auf dem NAS, Auto-Update des
`paperless-ngx-stack`, Benachrichtigung per ntfy) wird im privaten Repository
`Hiwamashi/nas-stacks` geplant und dokumentiert. Dieser Change liefert nur die Seite bis zur
Registry und hält fest, was die Ausrollseite von ihr erwarten darf.

## Capabilities

### New Capabilities

- `image-auslieferung`: Garantien der Image-Auslieferung: wann ein Image entsteht (Test-Gate,
  Pfadfilter, nur `main`), wie es aussieht (Multi-Arch-Manifest-Liste, Tags `git-<sha>` und
  `latest` in fester Reihenfolge), dass nur CI in die Registry schreibt und dass das Image
  keine Secrets enthält.

### Modified Capabilities

_keine_ — Verhalten des Dienstes selbst ändert sich nicht.

## Impact

- **Neu:** `.github/workflows/image.yml`.
- **Entfällt:** `scripts/push-image.sh`, `tests/test_push_image_script.py`; der Kommentar in
  `.gitignore`, der die Ausschlüsse mit dem Push-Skript begründet, wird angepasst (die
  Ausschlüsse selbst bleiben).
- **Doku:** `feature-documentation/registry-deployment.md` (umgebaut auf CI, Verweis auf
  `nas-stacks`), `README.md` (Abschnitt Registry), `prd/PROGRESS.md`.
- **Extern, einmalig manuell:** Scaleway-IAM-Application + API-Key, GitHub-Secret.
- **Abhängigkeit:** Die Ende-zu-Ende-Probe (Push → läuft auf dem NAS) setzt Komodo aus
  `nas-stacks` voraus. Bis dahin bleibt der manuelle Rollout (`pull` + `up -d`) gültig.
- **Code des Dienstes, Dockerfile, Compose-Beispiel:** unverändert.
