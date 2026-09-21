# Spec Delta

## MODIFIED Requirements

### Requirement: Jeder Verarbeitungsschritt erzeugt einen Verlaufseintrag

Der Dienst MUSS zu jedem Vorgang eine zeitlich geordnete Folge von Verlaufseinträgen führen.
Ein Eintrag benennt Zeitpunkt, Art des Schritts und eine lesbare Meldung. Die Arten sind
`detected`, `preprocessing`, `ocr_chunk`, `built_pdf`, `moved_to_consume`, `retry_scheduled`,
`skipped_erechnung`, `blocked`, `released`, `discarded`, `failed` und `done`.

#### Scenario: Verlauf eines veredelten Dokuments

- **WHEN** ein Dokument den OCR-Weg vollständig durchlaufen hat
- **THEN** zeigt sein Verlauf die Schritte von der Erkennung über Aufbereitung und
  Texterkennung bis zur Ablage in nachvollziehbarer Reihenfolge

#### Scenario: Verlauf eines gescheiterten Dokuments

- **WHEN** ein Dokument endgültig gescheitert ist
- **THEN** ist aus dem Verlauf ersichtlich, wie viele Versuche stattfanden und woran der letzte
  scheiterte

#### Scenario: Verlauf eines angehaltenen Dokuments

- **WHEN** ein Dokument angehalten wurde
- **THEN** nennt ein Verlaufseintrag vom Typ `blocked` den Grund samt der festgestellten
  Seitenzahl und der geltenden Grenze

#### Scenario: Verlauf nach einer Entscheidung

- **WHEN** ein angehaltener Vorgang freigegeben bzw. verworfen wurde
- **THEN** hält ein Verlaufseintrag vom Typ `released` bzw. `discarded` diese Entscheidung
  samt Zeitpunkt fest, und der vorangegangene `blocked`-Eintrag bleibt erhalten

### Requirement: Die Weboberfläche zeigt Übersicht und Detail

Der Dienst MUSS eine Weboberfläche bereitstellen, die den aktuellen Bestand nach Zustand
gegliedert zeigt, eine Liste der Vorgänge führt und zu jedem Vorgang eine Detailansicht mit
dem vollständigen Verlauf anbietet. Jeder Zustand, den ein Vorgang annehmen kann, MUSS in
der Gliederung und im Filter vertreten sein; es DARF kein Zustand geben, der nur in der
Datenbank existiert und in der Oberfläche unsichtbar bleibt.

#### Scenario: Übersicht aufrufen

- **WHEN** die Startseite aufgerufen wird
- **THEN** sind die Vorgänge mit ihrem Zustand sichtbar und nach Zustand filterbar

#### Scenario: Detailansicht aufrufen

- **WHEN** ein einzelner Vorgang geöffnet wird
- **THEN** sind seine Stammdaten und sein vollständiger Verlauf sichtbar

#### Scenario: Leerer Bestand

- **WHEN** zu einem gewählten Filter kein Vorgang existiert
- **THEN** erklärt die Oberfläche den leeren Zustand, statt nur eine leere Liste zu zeigen

#### Scenario: Angehaltene Vorgänge in der Übersicht

- **WHEN** mindestens ein Vorgang angehalten ist
- **THEN** weist die Übersicht ihn als eigenen Zustand mit eigener Zählung aus und lässt sich
  auf ihn filtern

## ADDED Requirements

### Requirement: Die Oberfläche macht die Entscheidung über einen angehaltenen Vorgang möglich

Der Dienst MUSS in der Detailansicht eines angehaltenen Vorgangs beide Entscheidungen
anbieten — freigeben und verwerfen. Beide MÜSSEN ausdrücklich ausgelöst werden; keine der
beiden DARF durch bloßes Betrachten oder Aktualisieren der Seite geschehen.

Bei einem Vorgang, der nicht angehalten ist, DÜRFEN diese Schaltflächen nicht auslösbar
sein.

#### Scenario: Angehaltener Vorgang wird geöffnet

- **WHEN** die Detailansicht eines angehaltenen Vorgangs aufgerufen wird
- **THEN** stehen dort genau zwei Schaltflächen zur Entscheidung bereit

#### Scenario: Betrachten ändert nichts

- **WHEN** die Detailansicht eines angehaltenen Vorgangs geöffnet und mehrfach aktualisiert
  wird
- **THEN** bleibt der Vorgang angehalten

#### Scenario: Vorgang in anderem Zustand

- **WHEN** die Detailansicht eines Vorgangs aufgerufen wird, der nicht angehalten ist
- **THEN** werden die beiden Entscheidungen nicht zum Auslösen angeboten

### Requirement: Die Entscheidung ist ohne Rückfrage begründbar

Der Dienst MUSS dem Betrachter eines angehaltenen Vorgangs die Tatsachen nennen, auf denen
die Entscheidung beruht: die festgestellte Seitenzahl des Dokuments und die geltende Grenze.
Es DARF nicht nötig sein, das Betriebsprotokoll oder die Konfiguration heranzuziehen, um zu
verstehen, warum der Vorgang angehalten wurde.

#### Scenario: Grund wird angezeigt

- **WHEN** ein angehaltener Vorgang betrachtet wird
- **THEN** sind Seitenzahl und geltende Grenze aus der Anzeige ablesbar

### Requirement: Eine Entscheidung wird ohne Neuladen sichtbar

Der Dienst MUSS die Oberfläche nach einer Freigabe oder einem Verwerfen von sich aus
aktualisieren, wie bei jeder anderen Zustandsänderung auch.

#### Scenario: Zweite geöffnete Ansicht

- **WHEN** ein Vorgang freigegeben wird, während die Übersicht in einer zweiten Ansicht
  geöffnet ist
- **THEN** aktualisiert sich auch diese Ansicht von selbst
