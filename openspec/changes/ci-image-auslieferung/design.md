# Design

## Context

Siehe `proposal.md` (Why). Ausgangslage im Code:

- `scripts/push-image.sh` baut auf dem Mac per `docker buildx` eine Manifest-Liste
  (`linux/amd64,linux/arm64`) mit den Tags `latest` und `git-<sha>` (7 Zeichen, z. B.
  `git-7ffcb4c`) und prüft danach den Index. Seine drei Gates (Registry-Login, sauberer
  Worktree, HEAD auf `origin`) sichern Reproduzierbarkeit ab; in CI sind sie durch den
  Auslöser (Push auf `main`, Checkout des Commits) von selbst erfüllt.
- Registry: `rg.nl-ams.scw.cloud/krinke-dockersolutions/lector`, Namespace öffentlich, Pull
  ohne Login. Push-Login: Benutzer `nologin`, Passwort = Scaleway Secret Key.
- Das Repository auf GitHub (`Hiwamashi/lector`) ist öffentlich.
- `uv run ruff check .` ist grün, `ruff format --check .` nicht (27 Dateien). Die Lint-Stufe
  in CI nutzt deshalb nur `ruff check`.
- Seit 2026-10-21 (Renovate-Onboarding) gibt es `.github/workflows/build-check.yml`: Aufruf des
  wiederverwendbaren Workflows `Krinke-IT-Consulting/renovate/.github/workflows/build-check.yml`
  (gepinnt auf `3b4129e…`) bei Pull Requests, Push auf `main` und manuell. Er erkennt die
  prüfbaren Teile selbst; für Lector laufen die Jobs `python` (`uv sync --frozen --all-extras`,
  `compileall`, `pytest`), `docker` (Build ohne Push) und `compose`. `ruff` ist nicht dabei.
  Lauf auf `main` (`59442b7`) grün. Renovate aktualisiert u. a. `uv.lock`.
- `Dockerfile` zieht `python:3.12-slim` und `ghcr.io/astral-sh/uv:latest` ohne Digest; jeder
  Neubau erzeugt daher einen neuen Image-Digest, auch ohne Codeänderung.
- Das NAS (Zettlab, Intel/amd64) betreibt einen Compose-Stack
  `/zettos/pool/1/teams/Docker/DATA/Docker/paperless-ngx-stack` mit Klartext-Zugangsdaten in
  der Compose-Datei (lokal als `.mynas.docker-compose.yml` gespiegelt, per `.gitignore`
  ausgeschlossen, nie versioniert).
- Auf der Ausrollseite pollt Komodo (geplant in `nas-stacks`) die Registry nach neuen Digests
  der `:latest`-Images und deployt nur die betroffenen Dienste neu.

## Goals / Non-Goals

**Goals:**

- Die Garantien aus `specs/image-auslieferung/spec.md` in einem GitHub-Workflow umsetzen.
- Die Garantien, auf die sich die Ausrollseite verlässt, ausdrücklich festhalten (D7).

**Non-Goals:**

- Komodo, ntfy und das Ausrollen auf dem NAS (Repository `nas-stacks`).
- `ruff format` in CI erzwingen (würde einen Massen-Reformat voraussetzen).
- Komodo per Webhook aus GitHub auslösen.
- Tests für Pull Requests. Kann später ergänzt werden, ohne die Spec zu ändern.
- Reproduzierbare Digests (Basis-Images per Digest pinnen). Der Pfadfilter genügt.

## Decisions

### D1 — Prüfen (zentraler Build-Check + Lint), Bauen pro Plattform, Zusammenführen

```
build-check  (uses: Krinke-IT-Consulting/renovate/.github/workflows/build-check.yml@<sha>)
             Erkennung -> python (uv sync --frozen, compileall, pytest),
                          docker (buildx build ohne Push), compose (Pruefung)
lint         (ubuntu-24.04)   uv run ruff check .
  |  beide gruen
  v
build (Matrix)                 amd64 auf ubuntu-24.04, arm64 auf ubuntu-24.04-arm
  |   je Plattform: buildx build --push-by-digest, Digest als Artefakt
  v
merge (ubuntu-24.04)           imagetools create -t git-<sha> <digest-amd64> <digest-arm64>
                               imagetools inspect git-<sha> -> beide Plattformen?  sonst Abbruch
                               imagetools create -t latest git-<sha>
```

Der Test-Gate ist der zentrale, wiederverwendbare Build-Check aus dem Renovate-Repository —
derselbe Prüfstandard wie in `build-check.yml` für Pull Requests und `main`. Er führt kein
`ruff` aus; deshalb ergänzt ein eigener Job `lint` die Prüfung (Spec: Lint und Tests). `build`
hängt von `build-check` und `lint` ab, `merge` von beiden `build`-Läufen.

*Alternativen:* eigener Test-Job (zweiter, abweichender Prüfweg; verworfen) oder Auslösung per
`workflow_run` nach grünem `build-check.yml` (keine Doppelläufe, aber `workflow_run` kennt keinen
Pfadfilter; verworfen). In Kauf genommen: Bei bildrelevanten Pushes auf `main` laufen die
Prüfungen zweimal (in `build-check.yml` und in `image.yml`). Native Runner statt QEMU:
Für öffentliche Repositorys sind arm64-Runner kostenlos, der Bau wird deutlich schneller als
die bisherige Emulation. Das Muster „push by digest + Merge“ ist der von Docker dokumentierte
Weg für Multi-Plattform-Builds auf getrennten Runnern.

*Alternative:* ein Job mit QEMU für beide Plattformen. Einfacher, aber langsam (genau das
Problem des Mac-Builds) und ohne Gewinn.

### D2 — Tag-Reihenfolge und Prüfung im Merge-Job

`latest` wird nicht in einem Schritt mit `git-<sha>` gesetzt, sondern danach aus der bereits
veröffentlichten und geprüften Liste `git-<sha>` abgeleitet. Damit zeigen beide Tags auf
dieselbe Manifest-Liste, und ein Abbruch zwischen den Schritten hinterlässt höchstens ein
unbenutztes `git-<sha>`, nie ein halbes `latest`. Die Plattformprüfung entspricht der bisherigen
Prüfung im Push-Skript (`grep` auf beide Plattformen in `imagetools inspect`).

Kurz-SHA: die ersten 7 Zeichen von `GITHUB_SHA`, passend zu den vorhandenen Rollback-Tags.

### D3 — Auslöser, Pfadfilter, Nebenläufigkeit

- `on.push.branches: [main]` mit `paths:` auf die bildrelevanten Dateien aus der Spec,
  zusätzlich `workflow_dispatch` (läuft ohne Pfadfilter; der Lauf baut den gewählten Ref, das
  Merge setzt `latest` nur, wenn `github.ref == refs/heads/main`).
- `concurrency: { group: image-main, cancel-in-progress: true }`: Ein neuerer Lauf bricht den
  älteren ab, `latest` kann nicht auf einen älteren Stand zurückfallen.

### D4 — Registry-Zugang über eigene IAM-Application

In Scaleway eine IAM-Application `lector-ci` mit einer Policy, die nur
`ContainerRegistryFullAccess` im Projekt gewährt, und einen API-Key dazu anlegen. Der Secret
Key kommt als Repository-Secret `SCW_REGISTRY_SECRET_KEY` nach GitHub; Login per
`docker/login-action` mit Benutzer `nologin`. Kein persönlicher Key in CI, Widerruf betrifft
nur die CI.

*Alternative:* den bestehenden persönlichen Key verwenden. Abgelehnt: zu weitreichende Rechte
in einem öffentlichen Repository.

### D5 — Actions auf Commit-SHAs pinnen, minimale Rechte

Fremde Actions (`actions/checkout`, `astral-sh/setup-uv`, `docker/setup-buildx-action`,
`docker/login-action`, `docker/build-push-action`, `actions/upload-artifact`,
`actions/download-artifact`) werden auf vollständige Commit-SHAs mit Versionskommentar
gepinnt, ebenso der eingebundene Build-Check (Commit-SHA wie in `build-check.yml`). Renovate
(`renovate.json`, Basis `Krinke-IT-Consulting/renovate`) hält diese Pins aktuell. Workflow-Rechte:
`permissions: contents: read`; der Build-Check bekommt keine Secrets. Grund: Der Workflow hält
einen Registry-Schlüssel, aus dem automatisch Produktion wird.

### D6 — Push-Skript entfernen

`scripts/push-image.sh` und `tests/test_push_image_script.py` werden gelöscht, `scripts/`
behält `diag_rotation.py`. Die `.gitignore`-Einträge `.agents/` und `.opencode/` bleiben (sie
sind generierte Spiegel), nur der Begründungskommentar wird angepasst. Lokale Testbuilds:
`docker buildx build --platform linux/arm64 -t lector:dev --load .`.

### D7 — Schnittstelle zur Ausrollseite (`nas-stacks`)

Das Ausrollen auf das NAS (Komodo, ntfy) wird im privaten Repository `Hiwamashi/nas-stacks`
geplant. Dieser Change hält nur fest, worauf sich die Ausrollseite verlassen darf und was sie
dafür tun muss:

- `latest` zeigt immer auf eine vollständige, geprüfte Manifest-Liste des neuesten
  bildrelevanten `main`-Stands; die Ausrollseite darf `latest` per Digest-Abfrage pollen und
  bei Änderung automatisch neu deployen.
- Jeder Stand bleibt als `git-<sha7>` abrufbar; Rollback = Image-Zeile auf dieses Tag setzen
  und neu deployen.
- Neue Digests entstehen nur bei bildrelevanten Änderungen oder manuellem Neubau; ein
  unerwarteter Neustart von Lector deutet daher auf einen dieser beiden Fälle hin.

## Risks / Trade-offs

- [Ein grüner, aber fehlerhafter Commit geht ohne Halt live] → Test-Gate; Rollback per
  `git-<sha>` auf der Ausrollseite.
- [Abbruch per `cancel-in-progress` zwischen `git-<sha>` und `latest`] → hinterlässt nur ein
  unbenutztes SHA-Tag; harmlos.
- [Image-Digest ändert sich bei jedem Neubau] → Pfadfilter verhindert Neubauten ohne
  Codeänderung; ein manueller Lauf startet Lector bewusst neu.
- [Gemergte Renovate-Updates von `uv.lock` oder `Dockerfile` landen ohne weiteren Halt auf dem
  NAS] → gewollt (Sicherheitsupdates), abgesichert durch den Test-Gate; ob die gemeinsame
  Renovate-Konfiguration Automerge nutzt, ist bei der Umsetzung zu prüfen und in der Doku zu
  nennen.
- [Der zentrale Build-Check ändert sich im Renovate-Repository] → per Commit-SHA gepinnt;
  ein neuer Pin kommt als Renovate-PR und wird dort geprüft.

## Migration Plan

1. Scaleway-IAM-Application anlegen, Secret nach GitHub (manuell).
2. Workflow mergen; erster Lauf per `workflow_dispatch`; prüfen, dass `latest` und
   `git-<sha>` mit beiden Plattformen in der Registry stehen.
3. Einmal manuell auf dem NAS `pull` + `up -d` (wie bisher), um den CI-Build zu verifizieren.
4. Push-Skript entfernen (gleicher Change, nach erfolgreichem CI-Lauf).
5. Sobald Komodo aus `nas-stacks` läuft: Probe mit einem kleinen Commit unter `app/` → nach
   höchstens einem Poll-Intervall läuft der neue `git-<sha>`.

Rollback des Changes: Der alte Weg lässt sich aus der Git-Historie wiederherstellen
(`git checkout <vorher> -- scripts/push-image.sh`).
