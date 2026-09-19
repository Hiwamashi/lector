# verarbeitungs-historie Specification

## Purpose

Macht Stand und Verlauf jedes Dokuments dauerhaft nachvollziehbar und zeigt Änderungen ohne
Zutun des Betrachters in der Weboberfläche an.

## Requirements

### Requirement: Zu jedem Vorgang wird ein Stammsatz geführt

Der Dienst MUSS je Dokument einen dauerhaften Datensatz führen, der mindestens den
ursprünglichen Dateinamen, den Quellpfad, eine Prüfsumme des Inhalts, den Zustand, den
Dokumenttyp, die verwendete OCR-Engine, Gesamt- und verarbeitete Seitenzahl, den
Versuchszähler, den nächsten Wiederholzeitpunkt, eine Fehlermeldung, den Ablageort des
Ergebnisses sowie Zeitpunkte für Anlage, Beginn und Abschluss enthält.

#### Scenario: Vorgang abgeschlossen

- **WHEN** ein Dokument fertig verarbeitet ist
- **THEN** sind Zustand, Dokumenttyp, Engine, Seitenzahlen, Ablageort des Ergebnisses und der
  Abschlusszeitpunkt am Datensatz abrufbar

### Requirement: Jeder Verarbeitungsschritt erzeugt einen Verlaufseintrag

Der Dienst MUSS zu jedem Vorgang eine zeitlich geordnete Folge von Verlaufseinträgen führen.
Ein Eintrag benennt Zeitpunkt, Art des Schritts und eine lesbare Meldung. Die Arten sind
`detected`, `preprocessing`, `ocr_chunk`, `built_pdf`, `moved_to_consume`, `retry_scheduled`,
`skipped_erechnung`, `failed` und `done`.

#### Scenario: Verlauf eines veredelten Dokuments

- **WHEN** ein Dokument den OCR-Weg vollständig durchlaufen hat
- **THEN** zeigt sein Verlauf die Schritte von der Erkennung über Aufbereitung und
  Texterkennung bis zur Ablage in nachvollziehbarer Reihenfolge

#### Scenario: Verlauf eines gescheiterten Dokuments

- **WHEN** ein Dokument endgültig gescheitert ist
- **THEN** ist aus dem Verlauf ersichtlich, wie viele Versuche stattfanden und woran der letzte
  scheiterte

### Requirement: Die Historie überlebt das Löschen der Dateien

Der Dienst MUSS Stammsatz und Verlauf eines Vorgangs erhalten, auch nachdem die zugehörige
Datei durch die Aufbewahrungsregel entfernt wurde.

#### Scenario: Datei durch Aufbewahrungsregel gelöscht

- **WHEN** die verarbeitete Originaldatei nach Ablauf der Aufbewahrungsfrist gelöscht wurde
- **THEN** bleiben Stammsatz und Verlauf des Vorgangs vollständig abrufbar

### Requirement: Die Weboberfläche zeigt Übersicht und Detail

Der Dienst MUSS eine Weboberfläche bereitstellen, die den aktuellen Bestand nach Zustand
gegliedert zeigt, eine Liste der Vorgänge führt und zu jedem Vorgang eine Detailansicht mit
dem vollständigen Verlauf anbietet.

#### Scenario: Übersicht aufrufen

- **WHEN** die Startseite aufgerufen wird
- **THEN** sind die Vorgänge mit ihrem Zustand sichtbar und nach Zustand filterbar

#### Scenario: Detailansicht aufrufen

- **WHEN** ein einzelner Vorgang geöffnet wird
- **THEN** sind seine Stammdaten und sein vollständiger Verlauf sichtbar

#### Scenario: Leerer Bestand

- **WHEN** zu einem gewählten Filter kein Vorgang existiert
- **THEN** erklärt die Oberfläche den leeren Zustand, statt nur eine leere Liste zu zeigen

### Requirement: Zeitangaben erscheinen einheitlich in der konfigurierten Zeitzone

Der Dienst MUSS alle in der Oberfläche angezeigten Zeitpunkte in der über `TZ` konfigurierten
Zeitzone (Standard `Europe/Berlin`) und in einheitlicher, lesbarer Form darstellen. Es DARF
kein Zeitpunkt unformatiert oder in einer abweichenden Zeitzone erscheinen.

#### Scenario: Zeitpunkt im Verlauf

- **WHEN** ein Verlaufseintrag angezeigt wird
- **THEN** erscheint sein Zeitpunkt in derselben Zeitzone und Form wie alle übrigen Zeitangaben
  der Oberfläche

### Requirement: Änderungen werden ohne Neuladen sichtbar

Der Dienst MUSS die Oberfläche bei einer Zustandsänderung von sich aus aktualisieren, ohne
dass der Betrachter die Seite neu lädt. Bricht die Aktualisierung ab, MUSS das sichtbar
werden, statt eine veraltete Anzeige als aktuell erscheinen zu lassen.

#### Scenario: Zustand ändert sich während der Betrachtung

- **WHEN** sich der Zustand eines Vorgangs ändert, während die Übersicht geöffnet ist
- **THEN** aktualisiert sich die Anzeige von selbst

#### Scenario: Live-Verbindung bricht ab

- **WHEN** die Verbindung für Live-Aktualisierungen unterbrochen wird
- **THEN** weist die Oberfläche darauf hin, statt unbemerkt stehen zu bleiben

#### Scenario: Geänderte Zeile wird hervorgehoben

- **WHEN** sich eine Zeile der Liste durch eine Aktualisierung inhaltlich ändert
- **THEN** wird genau diese Zeile kurz hervorgehoben, eine nur verschobene Zeile dagegen nicht

### Requirement: Der Dienst bietet einen Health-Endpunkt

Der Dienst MUSS einen Endpunkt bereitstellen, über den eine Überwachung prüfen kann, ob er
antwortet.

#### Scenario: Health-Endpunkt abfragen

- **WHEN** der Health-Endpunkt aufgerufen wird
- **THEN** antwortet der Dienst mit einem Erfolgsstatus

### Requirement: Der Dienst verlangt keine Authentifizierung

Der Dienst ist für den Betrieb im lokalen Netz durch einen einzelnen Nutzer bestimmt und
MUSS ohne Anmeldung bedienbar sein. Er DARF keine eigene Benutzerverwaltung mitbringen.

#### Scenario: Zugriff ohne Anmeldedaten

- **WHEN** die Weboberfläche ohne Anmeldedaten aufgerufen wird
- **THEN** ist sie vollständig bedienbar

### Requirement: Der Dienst nimmt keine inhaltliche Klassifizierung vor

Der Dienst DARF keine Inhaltsdaten aus Dokumenten extrahieren, keine Dokumentklassen
vergeben und keine Schlagworte oder Korrespondenten setzen. Diese Aufgaben bleiben
vollständig bei Paperless.

#### Scenario: Dokument abgelegt

- **WHEN** ein veredeltes oder durchgereichtes Dokument im Ausgabeordner landet
- **THEN** trägt es keine vom Dienst vergebenen Schlagworte, Klassen oder Korrespondenten
