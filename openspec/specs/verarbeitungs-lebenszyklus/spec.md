# verarbeitungs-lebenszyklus Specification

## Purpose

Führt jeden Vorgang seriell durch definierte Zustände, legt Eingang und Ergebnis an den mit
Paperless vereinbarten Orten ab und regelt Wiederholversuche sowie das Aufräumen alter
Dateien.

## Requirements

### Requirement: Dokumente werden seriell verarbeitet

Der Dienst MUSS die Verarbeitungsreihe streng nacheinander abarbeiten. Es DARF zu keinem
Zeitpunkt mehr als ein Dokument gleichzeitig veredelt werden, damit Speicherbedarf und
Durchsatz gegen die OCR-Engine kalkulierbar bleiben. Ein Dokument DARF nicht mehrfach
gleichzeitig in der Reihe stehen.

#### Scenario: Mehrere Dateien gleichzeitig abgelegt

- **WHEN** mehrere Dokumente gleichzeitig im Eingangsordner erscheinen
- **THEN** werden sie nacheinander verarbeitet, nicht parallel

#### Scenario: Dokument wird erneut eingereiht, während es läuft

- **WHEN** ein bereits in Arbeit befindliches Dokument erneut eingereiht würde
- **THEN** wird es nicht ein zweites Mal aufgenommen

#### Scenario: Weboberfläche bleibt währenddessen bedienbar

- **WHEN** ein rechenintensives Dokument verarbeitet wird
- **THEN** bleibt die Weboberfläche erreichbar und aktualisiert sich weiter

### Requirement: Ein Vorgang durchläuft definierte Zustände

Der Dienst MUSS jeden Vorgang in genau einem der Zustände `pending`, `processing`, `done`,
`skipped_erechnung` oder `failed` führen. `pending` ist der Ausgangszustand und zugleich der
Zustand eines eingeplanten Wiederholversuchs; `done`, `skipped_erechnung` und `failed` sind
Endzustände.

#### Scenario: Verarbeitung beginnt

- **WHEN** ein Vorgang aus der Reihe genommen wird
- **THEN** wechselt er nach `processing`

#### Scenario: Veredelung erfolgreich

- **WHEN** ein Dokument vollständig veredelt und abgelegt wurde
- **THEN** steht der Vorgang auf `done`

### Requirement: E-Rechnungen werden unverändert durchgereicht

Der Dienst MUSS eine als E-Rechnung erkannte Datei **byte-identisch** in den Ausgabeordner
kopieren. Es DARF keine Texterkennung stattfinden, der Dateiname DARF nicht geändert werden,
und es DÜRFEN keine Paperless-Merkmale gesetzt werden.

#### Scenario: E-Rechnung erkannt

- **WHEN** ein Dokument als E-Rechnung eingestuft wurde
- **THEN** liegt eine inhaltlich unveränderte Kopie unter demselben Namen im Ausgabeordner, das
  Original liegt im Ordner der verarbeiteten Dateien, und der Vorgang steht auf
  `skipped_erechnung`

#### Scenario: Keine Veredelung an E-Rechnungen

- **WHEN** eine E-Rechnung durchgereicht wird
- **THEN** wurde weder eine Texterkennung aufgerufen noch ein Textlayer erzeugt

### Requirement: Ergebnis und Original werden getrennt abgelegt

Der Dienst MUSS das Ergebnis in den Ausgabeordner (`CONSUME_DIR`) und das Eingangsoriginal in
den Ordner der verarbeiteten Dateien (`PROCESSED_DIR`) legen. Das Ergebnis-PDF trägt den
Basisnamen des Originals mit der Endung `.pdf`.

#### Scenario: Veredelung abgeschlossen

- **WHEN** ein Dokument erfolgreich veredelt wurde
- **THEN** liegt das Ergebnis-PDF im Ausgabeordner, das Original im Ordner der verarbeiteten
  Dateien, und der Ablageort des Ergebnisses ist am Vorgang festgehalten

### Requirement: Ergebnisdateien tragen die vereinbarte Eigentümerschaft

Der Dienst MUSS Dateien, die er in den Ausgabeordner schreibt, der über `PUID` und `PGID`
konfigurierten Kennung zuweisen (Standard jeweils 1000), weil dieser Ordner mit Paperless
geteilt wird.

#### Scenario: Ergebnis wird abgelegt

- **WHEN** eine Datei in den Ausgabeordner geschrieben wird
- **THEN** gehört sie der konfigurierten Benutzer- und Gruppenkennung

### Requirement: Namenskollisionen überschreiben nichts

Der Dienst DARF beim Ablegen einer Datei keine bestehende Datei gleichen Namens überschreiben.
Stattdessen MUSS ein unterscheidender Namenszusatz vergeben werden.

#### Scenario: Zieldatei existiert bereits

- **WHEN** im Zielordner bereits eine Datei mit demselben Namen liegt
- **THEN** wird die neue Datei unter einem ergänzten Namen abgelegt und die vorhandene bleibt
  unverändert

### Requirement: Fehler führen zu begrenzten Wiederholversuchen

Der Dienst MUSS einen fehlgeschlagenen Vorgang erneut einplanen, solange die Zahl der
Versuche unter `RETRY_MAX` liegt (Standard 3). Der nächste Versuch wird um
`RETRY_DELAY_MINUTES` (Standard 15) in die Zukunft gelegt und der Vorgang geht zurück nach
`pending`. Ein manuelles Auslösen eines Wiederholversuchs ist nicht vorgesehen.

#### Scenario: Erster Fehlschlag

- **WHEN** die Verarbeitung eines Dokuments fehlschlägt und die Versuchsgrenze noch nicht
  erreicht ist
- **THEN** steht der Vorgang wieder auf `pending`, trägt einen Zeitpunkt für den nächsten
  Versuch, und ein Verlaufseintrag vom Typ `retry_scheduled` nennt Versuchszähler und Grund

#### Scenario: Versuchsgrenze erreicht

- **WHEN** die Verarbeitung im letzten zulässigen Versuch fehlschlägt
- **THEN** wird das Original in den Fehlerordner (`ERROR_DIR`) verschoben, der Vorgang steht
  auf `failed` mit hinterlegter Fehlermeldung, und ein Verlaufseintrag vom Typ `failed` hält
  das fest

#### Scenario: Endgültig fehlgeschlagene Datei bleibt erhalten

- **WHEN** ein Vorgang endgültig fehlgeschlagen ist
- **THEN** bleibt das Original im Fehlerordner liegen und wird nicht automatisch gelöscht

### Requirement: Fällige Wiederholversuche werden auch nach einem Neustart aufgenommen

Der Dienst MUSS beim Start und danach regelmäßig prüfen, welche Vorgänge im Zustand `pending`
zur Wiederholung fällig sind, und sie wieder einreihen.

#### Scenario: Neustart mit eingeplantem Wiederholversuch

- **WHEN** der Dienst neu startet und ein Vorgang auf `pending` mit fälligem Wiederholzeitpunkt
  steht
- **THEN** wird er wieder eingereiht und verarbeitet

### Requirement: Alte verarbeitete Dateien werden automatisch gelöscht

Der Dienst MUSS regelmäßig Dateien aus dem Ordner der verarbeiteten Dateien entfernen, die
älter als `PROCESSED_RETENTION_DAYS` sind (Standard 30). Die Historie in der Datenbank MUSS
dabei erhalten bleiben. Das Aufräumen DARF ausschließlich diesen einen Ordner betreffen und
keine Unterverzeichnisse einbeziehen.

#### Scenario: Datei ist älter als die Aufbewahrungsfrist

- **WHEN** eine Datei im Ordner der verarbeiteten Dateien die Aufbewahrungsfrist überschreitet
- **THEN** wird sie gelöscht, während der zugehörige Vorgang samt Verlauf erhalten bleibt

#### Scenario: Aufbewahrung abgeschaltet

- **WHEN** `PROCESSED_RETENTION_DAYS` auf 0 oder kleiner steht
- **THEN** wird keine Datei gelöscht

#### Scenario: Andere Ordner bleiben unangetastet

- **WHEN** das Aufräumen läuft
- **THEN** bleiben Ausgabeordner, Fehlerordner und Eingangsordner unverändert

#### Scenario: Eine Datei lässt sich nicht löschen

- **WHEN** das Löschen einer einzelnen Datei fehlschlägt
- **THEN** wird das protokolliert und die übrigen Dateien werden weiterhin geprüft

### Requirement: Laufzeitparameter kommen ausschließlich aus Umgebungsvariablen

Der Dienst MUSS sämtliche Laufzeitparameter über Umgebungsvariablen beziehen. Es DARF keine
Konfigurationsdatei geben, die das Laufzeitverhalten bestimmt.

#### Scenario: Betrieb ohne Konfigurationsdatei

- **WHEN** der Dienst ohne jede Konfigurationsdatei gestartet wird
- **THEN** startet er mit den dokumentierten Standardwerten und den gesetzten
  Umgebungsvariablen

### Requirement: Nach einem Neustart bleibt kein Vorgang in Bearbeitung zurück

Der Dienst MUSS beim Start jeden Vorgang im Zustand `processing` auflösen, bevor er neue
Arbeit annimmt. Ein solcher Vorgang gehört zu keinem laufenden Prozess mehr, weil die
Verarbeitung streng seriell in genau einem Prozess stattfindet. Nach dem Start DARF kein
Vorgang mehr im Zustand `processing` stehen, der nicht gerade bearbeitet wird.

Die Auflösung MUSS sich nach dem erreichten Fortschritt richten und in einem der bestehenden
Zustände enden. Ein neuer Zustand wird nicht eingeführt.

#### Scenario: Unterbrechung vor der Ablage des Ergebnisses

- **WHEN** der Dienst startet und ein Vorgang auf `processing` steht, für den weder ein
  Ergebnis im Ausgabeordner liegt noch das Original den Eingangsordner verlassen hat
- **THEN** wird der Vorgang erneut zur Verarbeitung eingereiht

#### Scenario: Unterbrechung nach der Ablage des Ergebnisses

- **WHEN** der Dienst startet und für einen Vorgang auf `processing` bereits ein Ergebnis im
  Ausgabeordner liegt
- **THEN** wird der Vorgang abgeschlossen statt wiederholt: das Original wird in den Ordner
  der verarbeiteten Dateien überführt, der Ablageort des Ergebnisses ist am Vorgang
  festgehalten, und der Vorgang erreicht seinen regulären Endzustand

#### Scenario: Unterbrechung nach dem Verschieben des Originals

- **WHEN** der Dienst startet und für einen Vorgang auf `processing` das Ergebnis abgelegt und
  das Original bereits verschoben ist, nur der Abschluss fehlt
- **THEN** wird der Vorgang abgeschlossen und **nicht** als gescheitert gewertet

#### Scenario: Fortschritt nicht eindeutig feststellbar

- **WHEN** der Dienst startet und sich für einen Vorgang auf `processing` nicht eindeutig
  bestimmen lässt, wie weit er gekommen ist
- **THEN** wird er als gescheitert markiert, mit einer Meldung, die die Unterbrechung als
  Ursache benennt, und das Original bleibt zur manuellen Prüfung erhalten

#### Scenario: Auflösung geschieht vor der Annahme neuer Arbeit

- **WHEN** der Dienst startet, während unterbrochene Vorgänge und neue Eingangsdateien
  gleichzeitig vorliegen
- **THEN** sind die unterbrochenen Vorgänge aufgelöst, bevor eine neue Eingangsdatei
  aufgenommen wird

#### Scenario: Erneuter Start ohne unterbrochene Vorgänge

- **WHEN** der Dienst ein zweites Mal startet, nachdem die Auflösung bereits gelaufen ist
- **THEN** verändert die Auflösung nichts

### Requirement: Eine Wiederaufnahme erzeugt keine zweite Ablage

Der Dienst DARF durch die Auflösung eines unterbrochenen Vorgangs kein zweites Ergebnis für
dasselbe Dokument im Ausgabeordner erzeugen. Das gilt auch dann, wenn der Vorgang selbst
nicht festgehalten hat, dass die Ablage bereits stattgefunden hat.

#### Scenario: Ergebnis liegt abgelegt, ist aber am Vorgang nicht vermerkt

- **WHEN** ein Ergebnis für einen unterbrochenen Vorgang im Ausgabeordner liegt, ohne dass der
  Ablageort am Vorgang festgehalten ist
- **THEN** erkennt die Auflösung die vorhandene Ablage und erzeugt keine weitere

#### Scenario: Nachgelagerte Verarbeitung sieht jedes Dokument einmal

- **WHEN** ein Dokument von einer Unterbrechung betroffen war und der Dienst neu gestartet ist
- **THEN** liegt genau ein Ergebnis für dieses Dokument im Ausgabeordner

### Requirement: Die Auflösung ist im Verlauf nachvollziehbar

Der Dienst MUSS für jeden aufgelösten Vorgang festhalten, dass er von einer Unterbrechung
betroffen war und wie er aufgelöst wurde. Zusätzlich MUSS die Zahl der beim Start
aufgelösten Vorgänge im Betriebsprotokoll erscheinen, damit wiederkehrende Unterbrechungen
auffallen.

#### Scenario: Vorgang wurde nach einer Unterbrechung aufgelöst

- **WHEN** die Detailansicht eines Vorgangs geöffnet wird, der von einer Unterbrechung
  betroffen war
- **THEN** ist aus seinem Verlauf ersichtlich, dass eine Unterbrechung vorlag und wie sie
  aufgelöst wurde

#### Scenario: Mehrere Vorgänge gleichzeitig betroffen

- **WHEN** der Dienst startet und mehrere unterbrochene Vorgänge auflöst
- **THEN** nennt das Betriebsprotokoll deren Anzahl
