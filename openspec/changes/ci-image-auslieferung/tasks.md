# Tasks

Testbefehle: `uv run pytest`, `uv run ruff check .`. Aufgaben mit **(manuell)** führt der
Anwender aus (Konsole Scaleway/GitHub, NAS); der Agent bereitet Befehle und
Konfiguration vor und hakt erst nach Rückmeldung ab.

## 1. Zugang für die CI (manuell)

- [x] 1.1 **(manuell)** In Scaleway eine IAM-Application `lector-ci` mit einer Policy anlegen, die nur `ContainerRegistryFullAccess` im Projekt gewährt, und dazu einen API-Key erzeugen (Design D4). Prüfen: In der IAM-Übersicht hat `lector-ci` genau diese eine Regel.
- [x] 1.2 **(manuell)** Den Secret Key als Repository-Secret `SCW_REGISTRY_SECRET_KEY` in GitHub hinterlegen (`gh secret set SCW_REGISTRY_SECRET_KEY`). Prüfen: `gh secret list` zeigt den Namen.

## 2. Workflow

- [x] 2.1 Test `tests/test_image_workflow.py` schreiben, der `.github/workflows/image.yml` per YAML liest und die Spec-Invarianten festhält: Auslöser nur `push` auf `main` (mit `paths` = `app/**`, `Dockerfile`, `pyproject.toml`, `uv.lock`, `README.md`, Workflow-Datei) und `workflow_dispatch`; `concurrency` mit `cancel-in-progress: true`; `permissions: contents: read`; Job `build-check` ruft `Krinke-IT-Consulting/renovate/.github/workflows/build-check.yml` mit demselben Commit-SHA wie `.github/workflows/build-check.yml` auf; Job `lint` führt `ruff check` aus; `build` braucht `build-check` und `lint`, `merge` braucht `build`; Matrix enthält `linux/amd64` und `linux/arm64`; `latest` kommt nur im `merge`-Job vor und erst nach der Plattformprüfung; alle `uses:` auf 40-stellige SHAs gepinnt. Prüfen: Test schlägt ohne Workflow-Datei fehl.
- [x] 2.2 `.github/workflows/image.yml` nach Design D1–D3, D5 anlegen: Job `build-check` (zentraler Workflow, gepinnt, ohne Secrets), Job `lint` (`setup-uv`, `uv sync --frozen --extra dev`, `uv run ruff check .`), Matrix-Job `build` auf `ubuntu-24.04`/`ubuntu-24.04-arm` mit Push per Digest, Job `merge` mit `imagetools create` für `git-<sha7>`, Plattformprüfung per `imagetools inspect`, danach `latest` aus `git-<sha7>` (nur bei `refs/heads/main`). Registry-Login mit `nologin` und `SCW_REGISTRY_SECRET_KEY`. Prüfen: Test aus 2.1 grün; `actionlint` (falls installiert) ohne Befund.
- [x] 2.3 Gesamte Suite lokal laufen lassen. Prüfen: `uv run pytest` und `uv run ruff check .` grün.

## 3. Erster CI-Lauf

- [ ] 3.1 Änderungen committen und pushen, Workflow per `gh workflow run image.yml --ref main` auslösen. Prüfen: Lauf grün (`gh run watch`); Fehler in `build-check` oder `lint` im Workflow beheben und erneut laufen lassen.
- [ ] 3.2 Registry prüfen. Prüfen: `docker buildx imagetools inspect rg.nl-ams.scw.cloud/krinke-dockersolutions/lector:latest` listet `linux/amd64` und `linux/arm64`, und `latest` hat denselben Digest wie `git-<sha7>` des Laufs.
- [ ] 3.3 Prüfen, dass der Registry-Schlüssel nicht im Log steht. Prüfen: `gh run view --log` enthält keinen Klartext des Keys (GitHub maskiert ihn als `***`).
- [ ] 3.4 **(manuell)** Auf dem NAS einmal wie bisher `sudo docker compose pull lector && sudo docker compose up -d lector`. Prüfen: Container `healthy`, Weboberfläche erreichbar.

## 4. Push-Skript entfernen

- [ ] 4.1 `scripts/push-image.sh` und `tests/test_push_image_script.py` löschen; den Kommentar in `.gitignore` zu `.agents/`/`.opencode/` ohne Bezug auf das Push-Skript neu begründen (Design D6). Prüfen: `grep -rn push-image --exclude-dir=.git --exclude-dir=graphify-out --exclude-dir=archive --exclude-dir=docs .` findet nur noch Doku, die in Abschnitt 5 umgestellt wird; `uv run pytest` grün.

## 5. Dokumentation

- [ ] 5.1 `feature-documentation/registry-deployment.md` auf den CI-Weg umbauen: Workflow-Ablauf (zentraler Build-Check + Lint als Gate, Jobs, Tags, Reihenfolge, Pfadfilter, Nebenläufigkeit), Secret und IAM-Application, manueller Neubau, lokaler Testbuild, Verweis auf `nas-stacks` für Ausrollen und Rollback, Fehlerbilder (roter Test, fehlende Plattform, abgelaufener Key). Abschnitte zu den Gates des Push-Skripts entfernen. Prüfen: Datei nennt `image.yml` und kein `push-image.sh` mehr.
- [ ] 5.2 Prüfen, ob die gemeinsame Renovate-Konfiguration (`github>Krinke-IT-Consulting/renovate`) Automerge nutzt, und das Ergebnis in `registry-deployment.md` festhalten (gemergte Abhängigkeits-Updates werden automatisch ausgerollt). Prüfen: Abschnitt vorhanden.
- [ ] 5.3 `README.md` (Abschnitt Registry/Rollout) und `feature-documentation/README.md` (Index) auf den neuen Weg umstellen; für das Ausrollen auf das NAS auf das Repository `nas-stacks` verweisen. Prüfen: README nennt kein `push-image.sh` und keinen Mac-Login mehr.
- [ ] 5.4 `prd/PROGRESS.md` um einen Abschnitt „CI-Image-Auslieferung“ mit Stand der Aufgaben ergänzen. Prüfen: Eintrag vorhanden.
- [ ] 5.5 `graphify update .` ausführen. Prüfen: Befehl ohne Fehler.

## 6. Ende-zu-Ende-Probe

Setzt voraus, dass Komodo aus `nas-stacks` den `paperless-ngx-stack` mit Auto-Update betreibt. Bis dahin bleibt der Abschnitt offen; der Change kann ohne ihn archiviert werden, wenn die Probe in `nas-stacks` nachgeholt wird.


- [ ] 6.1 Einen kleinen Commit unter `app/` (z. B. Kommentar) auf `main` pushen. Prüfen: CI grün, nach höchstens Poll-Intervall läuft auf dem NAS der neue `git-<sha7>` (Komodo zeigt Redeploy nur für `lector`).
- [ ] 6.2 Einen reinen Doku-Commit pushen. Prüfen: Kein Workflow-Lauf, Lector auf dem NAS wird nicht neu gestartet.
- [ ] 6.3 Rollback üben: in Komodo `lector:git-<vorheriger-sha>` setzen und redeployen, danach zurück auf `latest`. Prüfen: Lector läuft jeweils `healthy` mit der erwarteten Version.
