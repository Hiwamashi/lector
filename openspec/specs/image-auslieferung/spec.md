# image-auslieferung Specification

## Purpose

Legt fest, wann und in welcher Form ein Lector-Image in die Registry gelangt, aus der das NAS
automatisch ausrollt. Weil jedes neue `latest` ohne weiteren Handgriff produktiv wird, sichert
diese Capability ab, dass nur geprüfte, vollständige und nachvollziehbare Stände dort ankommen.

## Requirements

### Requirement: Nur ein geprüfter Stand von `main` wird zum Image

Ein Image MUSS ausschließlich aus einem Commit entstehen, der auf dem Branch `main` des
GitHub-Repositorys liegt. Vor dem Bau MÜSSEN für genau diesen Commit die Lint-Prüfung, die
vollständige Testsuite, ein Probebau des Dockerfiles und die Prüfung der Compose-Dateien
erfolgreich durchlaufen. Die Prüfungen MÜSSEN demselben Standard folgen wie die Prüfung von Pull
Requests. Schlägt eine davon fehl, DARF KEIN Image in
die Registry geschrieben werden. Pushes auf andere Branches DÜRFEN KEIN Image erzeugen. Ein
manuell ausgelöster Lauf MUSS denselben Prüfungen unterliegen.

#### Scenario: Grüner Push auf main

- **WHEN** ein Commit auf `main` gepusht wird, der bildrelevante Dateien ändert, und Lint sowie
  Tests erfolgreich sind
- **THEN** entsteht ein Image dieses Commits in der Registry

#### Scenario: Roter Test verhindert das Image

- **WHEN** ein Commit auf `main` gepusht wird und ein Test fehlschlägt
- **THEN** wird kein Image gebaut, `latest` zeigt weiter auf den vorherigen Stand und der Lauf
  ist in GitHub als fehlgeschlagen sichtbar

#### Scenario: Feature-Branch

- **WHEN** ein Commit auf einen anderen Branch als `main` gepusht wird
- **THEN** entsteht kein Image

### Requirement: Nur bildrelevante Änderungen erzeugen ein Image

Ein Push auf `main` MUSS nur dann ein Image erzeugen, wenn er Dateien ändert, die in das Image
eingehen oder den Bau bestimmen: den Anwendungscode unter `app/`, `Dockerfile`,
`pyproject.toml`, `uv.lock`, `README.md` oder die Workflow-Definition selbst. Änderungen
ausschließlich an anderen Dateien (z. B. Doku, iOS-App, OpenSpec, Tests) DÜRFEN KEIN neues
Image erzeugen, damit der Dienst auf dem NAS nicht ohne Codeänderung neu gestartet wird. Ein
manuell ausgelöster Lauf MUSS unabhängig von geänderten Dateien bauen können.

#### Scenario: Reiner Doku-Commit

- **WHEN** ein Commit auf `main` nur Dateien unter `feature-documentation/` und `ios/` ändert
- **THEN** wird kein Image gebaut und `latest` bleibt unverändert

#### Scenario: Codeänderung

- **WHEN** ein Commit auf `main` eine Datei unter `app/` ändert
- **THEN** wird (bei grünen Prüfungen) ein Image gebaut

#### Scenario: Manueller Neubau

- **WHEN** der Workflow manuell für `main` ausgelöst wird, ohne dass sich bildrelevante Dateien
  geändert haben
- **THEN** wird (bei grünen Prüfungen) ein Image gebaut

### Requirement: Das Image ist eine Manifest-Liste für amd64 und arm64

Jedes veröffentlichte Tag MUSS eine Manifest-Liste sein, die genau die Plattformen
`linux/amd64` und `linux/arm64` enthält, sodass jeder Host mit derselben Image-Zeile seine
Architektur erhält. Es DARF KEINE architekturspezifischen Tags geben.

#### Scenario: NAS und Mac ziehen dasselbe Tag

- **WHEN** das Tag `latest` auf einem amd64-Host und auf einem arm64-Host gezogen wird
- **THEN** erhält jeder Host ein lauffähiges Image seiner Architektur

### Requirement: `latest` wird erst nach vollständigem Image gesetzt

Jeder Bau MUSS das Tag `git-<kurz-sha>` des gebauten Commits erzeugen. Das Tag `latest` MUSS
erst gesetzt werden, nachdem die Manifest-Liste für `git-<kurz-sha>` veröffentlicht und
geprüft wurde, dass sie beide Plattformen enthält. Fehlt eine Plattform, DARF `latest` NICHT
verändert werden. `latest` MUSS danach auf dieselbe Manifest-Liste zeigen wie
`git-<kurz-sha>`.

#### Scenario: Eine Plattform fehlt

- **WHEN** der Bau für eine der beiden Plattformen fehlschlägt
- **THEN** wird `latest` nicht verändert und der Lauf ist als fehlgeschlagen sichtbar

#### Scenario: Erfolgreicher Bau

- **WHEN** beide Plattformen gebaut und veröffentlicht sind
- **THEN** zeigen `git-<kurz-sha>` und `latest` auf dieselbe Manifest-Liste mit beiden
  Plattformen

### Requirement: `latest` fällt nie auf einen älteren Stand zurück

Laufen mehrere Bauvorgänge für `main` zeitlich überlappend, DARF ein älterer Commit `latest`
NICHT überschreiben, nachdem ein neuerer Commit es gesetzt hat. Ein laufender Bau für einen
älteren Commit MUSS zugunsten des neueren abgebrochen werden.

#### Scenario: Zwei Pushes kurz hintereinander

- **WHEN** Commit A und kurz danach Commit B auf `main` gepusht werden und der Bau von A noch läuft
- **THEN** wird der Bau von A abgebrochen und `latest` zeigt nach Abschluss auf B

### Requirement: Nur die CI schreibt in die Registry

Die Registry MUSS ausschließlich vom CI-Workflow beschrieben werden. Das Repository DARF KEIN
Werkzeug mehr enthalten, das Images von einem Entwicklungsrechner in die Registry schiebt. Der
Zugang der CI MUSS über einen eigenen Schlüssel erfolgen, der nur Rechte auf die Container
Registry hat, und als Repository-Secret hinterlegt sein. Der Schlüssel DARF in keiner Datei des
Repositorys und in keiner Log-Ausgabe erscheinen.

#### Scenario: Kein lokaler Push-Weg

- **WHEN** das Repository nach einem Werkzeug zum Pushen in die Registry durchsucht wird
- **THEN** findet sich nur die Workflow-Definition

#### Scenario: Schlüssel bleibt geheim

- **WHEN** die Ausgabe eines Workflow-Laufs eingesehen wird
- **THEN** erscheint der Registry-Schlüssel darin nicht im Klartext

### Requirement: Das Image enthält keine Secrets

Das veröffentlichte Image MUSS frei von Zugangsdaten und Konfigurationswerten der
Betriebsumgebung sein, weil der Registry-Namespace öffentlich ist. Konfiguration MUSS
ausschließlich zur Laufzeit über Umgebungsvariablen und Volumes hinzukommen.

#### Scenario: Lokale Secret-Dateien im Arbeitsverzeichnis

- **WHEN** im Arbeitsverzeichnis eine `.env` oder ein Ordner `secrets` liegt
- **THEN** gelangen deren Inhalte nicht in das Image
