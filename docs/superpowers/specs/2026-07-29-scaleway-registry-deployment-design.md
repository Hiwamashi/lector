# Design: Lector-Image über Scaleway Container Registry aufs NAS

Datum: 2026-07-29
Status: freigegeben (Design), Umsetzung offen

## Problem

`.mynas.docker-compose.yml:69` verweist auf `image: lector:latest` — ein Tag, das
nur lokal auf dem Entwicklungs-Mac existiert. Auf dem Zettlab NAS ist dieses Image
nicht auflösbar; der Stack lässt sich dort ohne Repo-Kopie und lokalen Build nicht
starten. `docker-compose.example.yml:82-83` verschärft das: dort stehen `build: .`
und `image:` gemeinsam, wodurch Compose das Image bei fehlendem lokalen Tag
**baut** statt es zu pullen — auf dem NAS ein Fehlschlag, weil der Build-Kontext
fehlt.

Zusätzlich divergieren die Architekturen: der Mac ist `arm64`, das Zettlab NAS
läuft auf Intel (`amd64`). Ein auf dem Mac ohne Plattform-Angabe gebautes Image
ist `arm64` und scheitert auf dem NAS erst beim Containerstart mit
`exec format error` — Push und Pull gelingen vorher stillschweigend.

## Ziel

Ein versioniertes, für beide Architekturen nutzbares Image liegt in einer
Registry. Das NAS zieht es per `docker compose pull`, ohne Repo-Kopie und ohne
lokalen Build. Ein fehlgeschlagenes Update lässt sich über ein Tag zurückrollen.

## Registry

Bestehender Namespace, wird nicht neu angelegt:

| Feld           | Wert                                          |
|----------------|-----------------------------------------------|
| Endpoint       | `rg.nl-ams.scw.cloud/krinke-dockersolutions`   |
| Namespace-ID   | `e115d876-8b78-4b88-bc99-965065e27837`         |
| Region         | `nl-ams`                                       |
| `is_public`    | `true`                                         |
| Inhalt bei Start | leer (`image_count: 0`)                      |

Verifiziert am 2026-07-29 per Scaleway-API. Weil der Namespace **öffentlich** ist,
braucht das NAS **keine** Registry-Zugangsdaten — `docker compose pull` funktioniert
ohne `docker login`. Der Namespace war leer, die Öffentlichkeit betrifft also keine
bereits vorhandenen fremden Images. Der Anwendungscode ist über das öffentliche
GitHub-Repo `Hiwamashi/lector` ohnehin einsehbar; das Image enthält keine Secrets
(siehe „Secret-Hygiene").

Image-Referenz:

```
rg.nl-ams.scw.cloud/krinke-dockersolutions/lector:latest
rg.nl-ams.scw.cloud/krinke-dockersolutions/lector:git-<short-sha>
```

## Architektur-Strategie: eine Manifest-Liste, zwei Plattformen

Beide Tags sind **Manifest-Listen** (OCI-Image-Index) über `linux/amd64` und
`linux/arm64`. Es gibt keine arch-spezifischen Tags.

```
lector:latest                      (Manifest-Liste)
  ├── linux/amd64   → Zettlab NAS zieht das
  └── linux/arm64   → Mac zieht das
```

Begründung: Die Compose-Zeile bleibt auf jedem Host identisch. Getrennte Tags
(`latest-amd64` / `latest-arm64`) würden die Architekturwahl in eine manuell
gepflegte Textstelle verlagern und damit genau die Fehlerklasse ermöglichen, die
dieses Design ausschließen soll. Für einen gezielten Arch-Test genügt lokal
`docker run --platform linux/amd64`.

Voraussetzungen sind auf dem Mac erfüllt und verifiziert (2026-07-29): Docker nutzt
den containerd Image Store (`io.containerd.snapshotter.v1`), und der Default-Builder
`desktop-linux` listet `linux/amd64` und `linux/arm64`. Ein zusätzlicher
buildx-Builder mit `docker-container`-Driver ist **nicht** erforderlich.

Kosten: `amd64` wird auf dem arm64-Mac per QEMU emuliert. Das Image installiert
über `uv sync` überwiegend fertige Wheels (numpy, opencv-headless, pypdfium2),
kompiliert also kaum — der amd64-Teil dauert dennoch deutlich länger als der
native arm64-Teil. Das ist akzeptiert, kein Optimierungsziel.

## Komponente: `scripts/push-image.sh`

Der einzige neue Baustein. Ein Bash-Skript mit `set -euo pipefail`, das lokal auf
dem Mac läuft.

Verantwortung: aus dem aktuellen Worktree ein Multi-Arch-Image bauen, mit
nachvollziehbaren Tags in die Registry pushen und das Ergebnis prüfen. Es
deployt **nicht** — der Rollout aufs NAS bleibt ein getrennter, manueller Schritt.

Ablauf:

1. **Login prüfen.** Ist in `~/.docker/config.json` kein `auths`-Eintrag für
   `rg.nl-ams.scw.cloud` vorhanden, bricht das Skript **vor** dem Build ab und gibt
   den Login-Befehl aus. Grund: ein erst beim Push scheiternder Login verwirft
   mehrere Minuten Emulations-Build.
2. **Worktree-Zustand prüfen, dann Tag ableiten.** Ist der Worktree schmutzig
   (`git status --porcelain` nicht leer), bricht das Skript ab. Nur committete
   Zustände gelangen in die Registry. Andernfalls ergibt
   `git rev-parse --short HEAD` das Tag `git-<sha>`.

   Ein `-dirty`-Suffix wäre die naheliegende, aber falsche Alternative: zwei
   verschiedene unkommittierte Zustände auf demselben HEAD ergeben denselben Tag
   `git-<sha>-dirty`, und der zweite Push überschreibt den ersten stillschweigend.
   Ein Rollback auf so ein Tag landet bei einem Codezustand, der aus dem Repo
   nicht rekonstruierbar ist — womit genau der Zweck entfällt, für den die
   SHA-Tags existieren. Ein Rollback-Ziel muss aus Git reproduzierbar sein; ein
   nicht-committeter Zustand ist das nie.

   Für schnelle Zwischenstände ist deshalb der lokale Build der richtige Weg,
   nicht der Push:
   ```
   docker buildx build --platform linux/arm64 -t lector:dev --load .
   ```
   Soll ein Zwischenstand tatsächlich aufs NAS, ist ein Commit (notfalls auf
   einem Wegwerf-Branch) der vorgesehene Schritt.
3. **Bauen und pushen**, in einem Aufruf:
   ```
   docker buildx build \
     --platform linux/amd64,linux/arm64 \
     -t <registry>/lector:latest \
     -t <registry>/lector:git-<sha> \
     --push .
   ```
   Die Plattform-Liste ist **fest verdrahtet**, nicht parametrisierbar.
4. **Verifizieren.** `docker buildx imagetools inspect <registry>/lector:latest`
   muss beide Plattformen im Index zeigen. Fehlt eine, bricht das Skript mit
   Fehler ab — ein stillschweigend auf eine Architektur reduzierter Index wäre
   sonst schwer zu bemerken.
5. **Compose-Zeile ausgeben** zum Kopieren.

Der Scaleway Secret Key wird vom Skript **nicht** gelesen, nicht als Parameter
akzeptiert und nicht aus Env-Variablen bezogen. Er wird einmalig manuell gesetzt:

```
docker login rg.nl-ams.scw.cloud -u nologin --password-stdin
```

(Benutzername ist bei Scaleway konstant `nologin`, das Passwort ist der Secret Key.)
Danach liegt das Credential im Docker-Credential-Store des Mac.

## Compose-Änderungen

`.mynas.docker-compose.yml:69` (nicht in Git getrackt, lokale NAS-Vorlage mit
Klartext-Tokens):

```yaml
image: rg.nl-ams.scw.cloud/krinke-dockersolutions/lector:latest
```

`docker-compose.example.yml:82-83` — `build: .` muss weichen, sonst baut Compose
statt zu pullen:

```yaml
image: rg.nl-ams.scw.cloud/krinke-dockersolutions/lector:latest
# Nur für lokale Entwicklung statt des Registry-Images:
#   build: .
# Achtung: build und image gemeinsam lassen Compose bauen, nicht pullen.
```

Kein `pull_policy: always` — es wird explizit gepullt. Kein Watchtower, keine CI.

## Deploy-Ablauf

```bash
# Mac
./scripts/push-image.sh

# NAS (per SSH), im Ordner des Paperless-Stacks
docker compose pull lector
docker compose up -d lector
```

Rollback bei einem defekten Update: in der Compose des NAS `:latest` durch den
zuletzt funktionierenden `:git-<sha>` ersetzen, dann `pull` + `up -d`.

## Secret-Hygiene (Ist-Zustand, verifiziert)

- `.env` und `.mynas.docker-compose.yml` sind **nicht** in Git getrackt, obwohl das
  Repo öffentlich ist.
- `.dockerignore` schließt `.env` und `secrets` aus.
- Das `Dockerfile` kopiert ausschließlich `pyproject.toml`, `uv.lock`, `README.md`
  und `app/` — `.mynas.docker-compose.yml` gelangt nicht ins Image, obwohl es
  nicht in `.dockerignore` steht.

Es besteht damit kein Handlungsbedarf; der Punkt ist dokumentiert, weil ein
öffentliches Image die Folgen eines künftigen Fehlers hier vergrößern würde.

## Fehlerbilder

| Symptom | Ursache | Gegenmaßnahme im Design |
|---|---|---|
| `exec format error` beim Start auf dem NAS | Image nur für arm64 gebaut | Plattform-Liste fest verdrahtet, Index nach Push verifiziert |
| Compose baut auf dem NAS statt zu pullen | `build:` neben `image:` | `build:` in beiden Compose-Dateien auskommentiert |
| Push scheitert nach langem Build | fehlender `docker login` | Login-Prüfung vor dem Build |
| Rollback-Tag enthält anderen Code als erwartet | Push aus schmutzigem Worktree; mehrere Zustände teilen sich einen Tag | Abbruch bei schmutzigem Worktree — nur committete Zustände werden gepusht, jeder Tag ist aus Git reproduzierbar |
| Push überschreibt stillschweigend ein bestehendes Tag | zweiter Build auf demselben HEAD | folgt aus dem Worktree-Abbruch: ein unveränderter HEAD ergibt ein bit-gleiches Ergebnis, ein geänderter einen neuen SHA |

## Verifikation

Lokal belegbar:

1. `./scripts/push-image.sh` läuft fehlerfrei durch.
2. `docker buildx imagetools inspect …/lector:latest` zeigt `linux/amd64` **und**
   `linux/arm64`.
3. Scaleway-API listet beide Tags im Namespace.
4. Der **arm64**-Container startet lokal und `/health` antwortet. Damit ist belegt,
   dass Lector unter arm64 tatsächlich läuft — dass für numpy/opencv/pypdfium2
   arm64-Wheels existieren, ist allein noch kein Beweis.

Nicht lokal belegbar, erfordert den Anwender:

5. Auf dem NAS `docker compose pull lector && docker compose up -d lector`,
   danach Port 8001 erreichbar. Kein Zugriff auf das NAS aus der
   Entwicklungsumgebung — dieser Schritt wird als offen gemeldet, bis er
   bestätigt ist.

## Dokumentation

- **neu** `feature-documentation/registry-deployment.md`: Registry-Koordinaten,
  Login, Skript, Deploy-Ablauf, Rollback, Fehlerbilder.
- `feature-documentation/docker-deployment.md`, Abschnitt `## Image`:
  Querverweis, damit die bestehende Datei nicht veraltet.
- `README.md`: Deploy-Abschnitt.
- `prd/PROGRESS.md`: Eintrag unter den Zusatz-Features.

## Bewusst ausgeschlossen

- **CI-Build (GitHub Actions):** würde den Scaleway Secret Key als GitHub-Secret
  erfordern; der lokale Build genügt für einen Einzelnutzer-Stack.
- **Watchtower:** automatische Updates würden unbeobachtet einen defekten Build
  live nehmen.
- **Arch-spezifische Tags:** siehe Architektur-Strategie.
- **Ein `--allow-dirty`-Opt-out für das Push-Skript:** würde die Mehrdeutigkeit
  wieder einführen, die der Worktree-Abbruch gerade verhindert. Wäre es doch
  gewünscht, müsste ein solches Tag zwingend eindeutig sein (z.B. um einen
  Zeitstempel ergänzt) **und** dürfte `latest` nicht mitverschieben — sonst zeigt
  der Standard-Tag des NAS auf einen nicht reproduzierbaren Zustand.
- **Deploy per SSH aus dem Push-Skript:** Build/Push und Rollout bleiben getrennt,
  damit ein Push nie unbeabsichtigt den laufenden Paperless-Stack verändert.
