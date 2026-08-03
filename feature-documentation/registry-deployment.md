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
  Emulations-Build auf),
- der Worktree nicht sauber ist, oder
- HEAD auf keinem bekannten Remote-Branch liegt.

### Warum kein Push aus schmutzigem Worktree

Zwei verschiedene unkommittierte Zustände auf demselben HEAD ergäben denselben
Tag, und der zweite Push überschriebe den ersten stillschweigend. Ein Rollback
auf so ein Tag landet bei Code, der aus dem Repo nicht rekonstruierbar ist —
womit der Zweck der SHA-Tags entfällt. Für schnelle Zwischenstände ist der
lokale Build der richtige Weg, **nicht** ein Commit auf einem Wegwerf-Branch:
ein nie gepushter Branch ist per Git-Garbage-Collection löschbar, und dann
zeigt das Rollback-Tag auf Code, den es nirgends mehr gibt — dasselbe Problem
wie beim schmutzigen Worktree, nur einen Schritt später. Committen allein
reicht also nicht; siehe das dritte Gate unten. Für lokale Zwischenstände:

    docker buildx build --platform linux/arm64 -t lector:dev --load .

Wer den Commit doch behalten will, pusht ihn (`git push`) — erst dann ist er
als Rollback-Ziel brauchbar.

### Drittes Gate: HEAD muss auf einem bekannten Remote-Branch liegen

Ein sauber committeter Zustand kann trotzdem rein lokal existieren. Das Skript
prüft daher zusätzlich `git branch -r --contains HEAD`: ist das leer, bricht
es ab, denn das `git-<sha>`-Tag wäre sonst für niemanden außer dem lokalen
Rechner auflösbar — als Rollback-Ziel nutzlos, und im schlimmsten Fall (siehe
oben) sogar gar nicht mehr existent. Vor dieser Prüfung frischt das Skript die
Remote-Tracking-Refs per `git fetch --prune --quiet origin` auf. Ohne diesen
Refresh könnten veraltete lokale Refs das Gate genau in dem Fall
durchwinken, den es verhindern soll: nach einem Force-Push, einem gelöschten
Remote-Branch oder einem neu aufgesetzten Remote-Repo zeigt der lokale Ref
weiterhin auf einen Commit, den das Remote gar nicht mehr kennt. `--prune`
entfernt dabei zusätzlich Refs zu Branches, die auf dem Remote gelöscht
wurden. Schlägt der Fetch fehl (offline, Remote nicht erreichbar,
Zugangsdaten ungültig), bricht das Skript ab, statt sich auf möglicherweise
veraltete Refs zu verlassen — das kostet nichts, denn ohne Netzwerk würde der
Push ohnehin wenig später scheitern. Abhilfe bei fehlgeschlagenem Fetch:
Netzwerk und Zugangsdaten prüfen. Abhilfe bei "HEAD ist auf keinem bekannten
Remote-Branch enthalten": `git push`.

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

    image: rg.nl-ams.scw.cloud/krinke-dockersolutions/lector:git-7ffcb4c

## Fehlerbilder

| Symptom | Ursache | Behebung |
|---|---|---|
| `exec format error` beim Containerstart | Image enthält die Architektur des NAS nicht | `docker buildx imagetools inspect …:latest` — beide Plattformen müssen im Index stehen |
| Compose baut auf dem NAS statt zu pullen | `build:` steht neben `image:` | `build:` auskommentieren; `tests/test_compose_files.py` hält das fest |
| Push scheitert nach langem Build | Registry-Login fehlt | `docker login rg.nl-ams.scw.cloud -u nologin --password-stdin` |
| Skript bricht mit „Worktree ist nicht sauber" ab | offene Änderungen | committen, oder lokal ohne Push bauen (siehe oben) |
| Skript bricht mit „HEAD ist auf keinem bekannten Remote-Branch enthalten" ab | Commit ist nur lokal vorhanden (auch: ungepushter Branch) | `git push`, dann erneut ausführen |
| Skript bricht mit „'git fetch --prune origin' fehlgeschlagen" ab | Kein Netzwerk, Remote nicht erreichbar oder Zugangsdaten ungültig | Netzwerk/VPN prüfen, `git fetch origin` manuell testen, dann erneut ausführen |

## Secrets

Das Image enthält keine Secrets. Das `Dockerfile` kopiert nur
`pyproject.toml`, `uv.lock`, `README.md` und `app/`; `.dockerignore` schließt
zusätzlich `.env` und `secrets` aus. Konfiguration kommt ausschließlich über
Umgebungsvariablen und Volumes aus der Compose. Das ist wichtig, weil das
Image öffentlich abrufbar ist.
