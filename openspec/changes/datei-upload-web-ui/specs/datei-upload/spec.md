# Spec Delta

## Purpose

Nimmt Dateien über die Web-Oberfläche entgegen und übergibt sie vollständig an den
Eingangsordner, damit ein Dokument auch ohne Zugriff auf die Dateifreigabe eingespeist werden
kann. Der Vertrag endet an dieser Übergabe — die weitere Verarbeitung verantwortet
`dokumenteneingang`.

## ADDED Requirements

### Requirement: Entgegengenommene Dateien werden dem Eingangsordner übergeben

Der Dienst MUSS jede über die Oberfläche entgegengenommene Datei im Eingangsordner ablegen und
darf für sie keinen eigenen Verarbeitungsweg eröffnen. Die weitere Behandlung MUSS
ausschließlich über die Regeln des Eingangsordners erfolgen, sodass eine übergebene Datei von
einer dort abgelegten nicht zu unterscheiden ist.

#### Scenario: Unterstützte Datei wird übergeben

- **WHEN** eine Datei mit unterstützter Endung über die Oberfläche entgegengenommen wird
- **THEN** liegt sie anschließend im Eingangsordner und wird von dort nach denselben Regeln
  aufgenommen wie eine per Dateifreigabe abgelegte Datei

#### Scenario: Keine Sonderbehandlung in der Historie

- **WHEN** ein Vorgang aus einer übergebenen Datei entsteht
- **THEN** trägt er denselben Ausgangszustand, dieselben Zustandsübergänge und dieselben
  Verlaufseinträge wie ein Vorgang aus dem Eingangsordner

### Requirement: Eine Datei wird erst nach vollständiger Übertragung übergeben

Der Dienst MUSS ausschließen, dass eine noch in Übertragung befindliche Datei im Eingangsordner
als vollständige Datei erscheint. Eine Datei MUSS unter ihrem endgültigen Namen erst dann im
Eingangsordner sichtbar werden, wenn ihr Inhalt vollständig übertragen und geschrieben ist.

#### Scenario: Übertragung wird abgeschlossen

- **WHEN** die Übertragung einer Datei vollständig abgeschlossen ist
- **THEN** erscheint sie unter ihrem endgültigen Namen im Eingangsordner

#### Scenario: Übertragung bricht ab

- **WHEN** eine Übertragung vor ihrem Abschluss abbricht
- **THEN** entsteht im Eingangsordner keine Datei unter einem endgültigen Namen und es wird kein
  Vorgang angelegt

#### Scenario: Übertragung stockt über das Stabilitätsfenster hinaus

- **WHEN** eine Übertragung länger als das Stabilitätsfenster des Eingangsordners ohne
  Fortschritt bleibt und danach weiterläuft
- **THEN** wird der unvollständige Stand nicht aufgenommen und die Datei wird erst nach dem
  vollständigen Abschluss übergeben

### Requirement: Nicht unterstützte Formate werden mit Rückmeldung zurückgewiesen

Der Dienst MUSS eine Datei mit nicht unterstützter Endung zurückweisen, bevor sie dem
Eingangsordner übergeben wird, und den Grund in der Oberfläche sichtbar machen. Unterstützt sind
dieselben Formate wie im Eingangsordner. Ein stilles Übergehen ist an dieser Stelle NICHT
zulässig.

#### Scenario: Nicht unterstützte Endung

- **WHEN** eine Datei mit nicht unterstützter Endung zur Übergabe angeboten wird
- **THEN** wird sie nicht im Eingangsordner abgelegt und die Oberfläche benennt die abgewiesene
  Datei und den Grund

#### Scenario: Gemischte Auswahl

- **WHEN** in einem Vorgang mehrere Dateien angeboten werden, von denen nur ein Teil eine
  unterstützte Endung trägt
- **THEN** werden die unterstützten Dateien übergeben und die übrigen unter Nennung ihres Namens
  zurückgewiesen

### Requirement: Der gelieferte Dateiname kann den Eingangsordner nicht verlassen

Der Dienst MUSS den vom Client gelieferten Dateinamen so behandeln, dass die Datei
ausschließlich unmittelbar im Eingangsordner entstehen kann. Verzeichnisanteile und
Navigationsangaben im gelieferten Namen DÜRFEN NICHT zu einem Schreibzugriff außerhalb des
Eingangsordners führen.

#### Scenario: Name enthält Verzeichnisanteile

- **WHEN** ein gelieferter Dateiname Verzeichnisanteile oder Navigationsangaben enthält
- **THEN** entsteht die Datei dennoch unmittelbar im Eingangsordner und außerhalb davon wird
  nichts geschrieben

### Requirement: Eine Übergabe überschreibt keine vorhandene Datei

Der Dienst MUSS eine vorhandene Datei im Eingangsordner unangetastet lassen, wenn eine Übergabe
denselben Namen trägt, und für die neue Datei einen freien Namen vergeben.

#### Scenario: Name ist bereits vergeben

- **WHEN** eine Datei übergeben wird, deren Name im Eingangsordner bereits belegt ist
- **THEN** bleibt die vorhandene Datei unverändert und die übergebene Datei erhält einen freien
  Namen

### Requirement: Mehrere Dateien in einem Vorgang

Der Dienst MUSS die Übergabe mehrerer Dateien in einem einzelnen Bedienschritt unterstützen und
jede davon als eigene Datei im Eingangsordner ablegen.

#### Scenario: Mehrfachauswahl

- **WHEN** mehrere unterstützte Dateien in einem Bedienschritt angeboten werden
- **THEN** wird jede einzeln im Eingangsordner abgelegt und erzeugt dort einen eigenen Vorgang

### Requirement: Die Oberfläche bestätigt die Übergabe ohne auf die Verarbeitung zu warten

Der Dienst MUSS die Bedienung nach der Übergabe freigeben, ohne die Aufnahme oder die
Verarbeitung abzuwarten. Die Oberfläche MUSS erkennbar machen, dass die Übergabe erfolgt ist und
der zugehörige Vorgang erst verzögert in der Übersicht erscheint.

#### Scenario: Nach der Übergabe

- **WHEN** eine Übergabe abgeschlossen ist
- **THEN** kehrt die Bedienung zur Übersicht zurück, bestätigt die Übergabe und wartet nicht auf
  das Ergebnis der Verarbeitung

### Requirement: Eine gescheiterte Ablage hinterlässt keine Datei im Eingangsordner

Der Dienst MUSS eine Übergabe, die beim Schreiben scheitert, so beenden, dass im Eingangsordner
keine verwertbare Datei dieses Vorgangs zurückbleibt, und den Fehlschlag in der Oberfläche
melden.

#### Scenario: Schreiben schlägt fehl

- **WHEN** das Schreiben einer übergebenen Datei fehlschlägt
- **THEN** bleibt keine Datei unter einem endgültigen Namen im Eingangsordner zurück und die
  Oberfläche meldet den Fehlschlag unter Nennung der betroffenen Datei
