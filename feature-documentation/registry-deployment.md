# Image-Auslieferung über GitHub Actions und die Scaleway Container Registry

Lector wird nicht auf dem NAS und nicht mehr auf dem Entwicklungsrechner gebaut. Der Workflow
`.github/workflows/image.yml` baut bei jedem bildrelevanten Push auf `main` ein Multi-Arch-Image
und schiebt es in die Scaleway-Registry. Er ist der **einzige** Weg in die Registry. Das NAS
rollt jedes neue `latest` automatisch aus (Komodo, Repository `nas-stacks`).

Anforderungen: Spec `image-auslieferung`. Test: `tests/test_image_workflow.py`.

```
git push main --(Pfadfilter)--> image.yml
   build-check (zentral) + lint (ruff)
        |  gruen
        v
   build amd64 (ubuntu-24.04) + build arm64 (ubuntu-24.04-arm), Push per Digest
        v
   merge: git-<sha7> als Manifest-Liste -> beide Plattformen? -> latest
        v
   Scaleway-Registry --(Komodo, Prozedur "Global Auto Update" alle 5 min)--> NAS
```

## Registry

| Feld | Wert |
|---|---|
| Endpoint | `rg.nl-ams.scw.cloud/krinke-dockersolutions` |
| Region / Projekt | `nl-ams` / `58816742-affb-4789-a04f-541ddf98e470` |
| Sichtbarkeit | öffentlich (Pull ohne Login) |
| Image | `lector` |
| Tags | `latest`, `git-<sha7>` |

Beide Tags sind Manifest-Listen über `linux/amd64` (Zettlab-NAS) und `linux/arm64`
(Entwicklungs-Mac). Jeder Host zieht seine Architektur; es gibt keine architekturspezifischen
Tags.

## Der Workflow

| Job | Läuft auf | Aufgabe |
|---|---|---|
| `build-check` | zentraler Workflow `Krinke-IT-Consulting/renovate/.github/workflows/build-check.yml` (gepinnt, derselbe SHA wie in `build-check.yml`) | `pytest`, Docker-Probebau ohne Push, Compose-Prüfung — derselbe Standard wie für Pull Requests |
| `lint` | `ubuntu-24.04` | `uv run ruff check .` (der zentrale Build-Check führt kein ruff aus) |
| `build` | Matrix `ubuntu-24.04` / `ubuntu-24.04-arm` | baut je Plattform **nativ** (keine QEMU-Emulation) und pusht per Digest |
| `merge` | `ubuntu-24.04` | legt `git-<sha7>` aus beiden Digests an, prüft per `imagetools inspect` beide Plattformen und setzt **erst dann** `latest` (nur auf `main`) |

**Auslöser:** Push auf `main`, wenn sich eine dieser Dateien ändert: `app/**`, `Dockerfile`,
`pyproject.toml`, `uv.lock`, `README.md` (wird ins Image kopiert), `.github/workflows/image.yml`.
Reine Doku-, iOS-, OpenSpec- oder Test-Commits erzeugen kein Image — jeder Neubau ergibt einen
neuen Digest (Basis-Images sind nicht per Digest gepinnt) und damit einen Neustart von Lector
auf dem NAS.

**Manueller Neubau:** `gh workflow run image.yml --ref main` (ohne Pfadfilter). Für einen
anderen Ref entsteht nur `git-<sha7>`, kein `latest`.

**Nebenläufigkeit:** feste Gruppe `image` mit `cancel-in-progress`. Ein neuerer Lauf bricht den
älteren ab; `latest` fällt so nie auf einen älteren Stand zurück. Ein Abbruch zwischen
`git-<sha7>` und `latest` hinterlässt nur ein unbenutztes SHA-Tag.

**Sicherheit:** `permissions: contents: read`, alle Actions auf Commit-SHAs gepinnt, Eingaben nur
über `env:` in Shell-Befehlen. Der Build-Check bekommt keine Secrets. Das Repository ist
öffentlich.

## Zugang der CI zur Registry

| Was | Wert |
|---|---|
| Scaleway-IAM-Application | `lector-ci` (`4e5ef4d0-7c7e-457f-8c93-6c75b866a150`) |
| Policy | `lector-ci-registry`: eine Regel, `ContainerRegistryFullAccess`, nur Projekt `58816742-…` |
| API-Key | ohne Ablaufdatum, Beschreibung „GitHub-Secret SCW_REGISTRY_SECRET_KEY“ |
| GitHub-Secret | `SCW_REGISTRY_SECRET_KEY` im Repository `Hiwamashi/lector` |
| Login | Benutzer `nologin`, Passwort = Secret Key |

Scaleway kennt für die Registry nur ReadOnly und FullAccess; die CI kann im Registry-Projekt
also auch Images löschen, aber nichts außerhalb der Registry.

**Key rotieren:** neuen API-Key für `lector-ci` erzeugen und direkt weiterreichen, ohne ihn
anzuzeigen, danach den alten Key löschen:

    scw iam api-key create application-id=4e5ef4d0-7c7e-457f-8c93-6c75b866a150 \
      default-project-id=58816742-affb-4789-a04f-541ddf98e470 -o json \
      | jq -j .secret_key | gh secret set SCW_REGISTRY_SECRET_KEY -R Hiwamashi/lector

## Renovate und automatische Auslieferung

Renovate (`renovate.json`, Basis `github>Krinke-IT-Consulting/renovate`) aktualisiert
Abhängigkeiten per Pull Request. Laut gemeinsamer Konfiguration (Stand 2026-11-01):

| Update-Art | Automerge |
|---|---|
| Patch, Digest, Pin (z. B. Patch-Versionen in `uv.lock`, Action-SHAs) | **ja**, gruppiert, Zeitplan Wochenende, nur bei grünem Build-Check |
| Minor | nein |
| Major | nein, erst nach Freigabe im Dependency Dashboard |
| Sicherheitsmeldungen (Vulnerability Alerts) | nein, PR sofort |

Folge: Ein automatisch gemergtes Patch-Update von `uv.lock` oder ein neuer Action-Pin in
`image.yml` erzeugt über den Pfadfilter ein neues Image, das das NAS **ohne weiteren Handgriff**
ausrollt. Das ist gewollt; der Test-Gate fängt kaputte Updates ab, Rollback siehe unten.

## Lokal bauen (ohne Push)

    docker buildx build --platform linux/arm64 -t lector:dev --load .

Zum Testen eines Stands auf dem NAS: committen, pushen, auf `main` mergen — oder per
`gh workflow run image.yml --ref <branch>` ein `git-<sha7>` bauen und dieses Tag auf dem NAS
eintragen.

## Ausrollen und Rollback

Ausrollen, Rollback und Benachrichtigung beschreibt das Repository `nas-stacks`
(`komodo/README.md`). Kurzfassung Rollback: im Stack `lector:latest` durch das zuletzt
funktionierende `lector:git-<sha7>` ersetzen und neu deployen. Die verfügbaren Tags zeigt
`scw registry tag list image-id=<id> region=nl-ams` bzw. die Scaleway-Konsole.

## Fehlerbilder

| Symptom | Ursache | Behebung |
|---|---|---|
| Lauf rot in `build-check` | Test, Docker-Probebau oder Compose-Prüfung fehlgeschlagen | Fehler beheben; `latest` bleibt auf dem vorherigen Stand |
| Lauf rot in `lint` | `ruff check` meldet Befunde | lokal `uv run ruff check .` |
| `build` scheitert beim Login (401/403) | Secret fehlt, Key widerrufen oder Policy geändert | Key rotieren (siehe oben), Policy prüfen |
| `merge` meldet „… fehlt im Index“ | ein Plattform-Build hat keinen Digest geliefert | Lauf neu starten; `latest` wurde nicht verändert |
| Kein Lauf nach einem Push | nur Dateien außerhalb des Pfadfilters geändert | gewollt; bei Bedarf manueller Neubau |
| `exec format error` auf dem NAS | Image ohne amd64-Teil | `docker buildx imagetools inspect …:latest` |
| Compose baut auf dem NAS statt zu pullen | `build:` neben `image:` | `build:` auskommentieren; `tests/test_compose_files.py` hält das fest |

## Secrets

Das Image enthält keine Secrets. Das `Dockerfile` kopiert nur `pyproject.toml`, `uv.lock`,
`README.md` und `app/`; `.dockerignore` schließt `.env*` und `secrets` aus. Konfiguration kommt
ausschließlich zur Laufzeit über Umgebungsvariablen und Volumes. Wichtig, weil das Image
öffentlich abrufbar ist.
