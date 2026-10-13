# app-schnittstelle Specification

## Purpose

Stellt einer nativen App dieselben Daten und Aktionen bereit wie die Weboberfläche, also
Vorgangsliste, Detail mit Verlauf und Entscheidungen über angehaltene Vorgänge. Die Antworten
sind maschinenlesbar. Die Anmeldung und die Übergabe von Dateien regeln `web-zugang` und
`datei-upload`.

## Requirements

### Requirement: Der Dienst gibt ohne Anmeldung Auskunft über sich

Der Dienst MUSS unter einem festen Pfad der Schnittstelle ohne Anmeldung eine Selbstauskunft
liefern. Sie MUSS erkennen lassen, dass es sich um Lector handelt, und die Version der
Schnittstelle sowie den geltenden Zugangsmodus (`none` oder `paperless`) nennen. Darüber
hinaus DARF die Selbstauskunft keine Angaben zum Betrieb, zu Vorgängen, zur Konfiguration oder
zu angebundenen Diensten enthalten.

#### Scenario: Selbstauskunft im Modus `paperless`

- **WHEN** die Selbstauskunft im Modus `paperless` ohne Anmeldung abgefragt wird
- **THEN** antwortet der Dienst erfolgreich mit der Kennung von Lector, der Version der
  Schnittstelle und dem Zugangsmodus `paperless`

#### Scenario: Selbstauskunft im Modus `none`

- **WHEN** die Selbstauskunft im Modus `none` abgefragt wird
- **THEN** nennt sie den Zugangsmodus `none`

#### Scenario: Keine Betriebsangaben

- **WHEN** die Selbstauskunft abgefragt wird
- **THEN** enthält die Antwort weder Vorgänge oder Zähler noch Konfigurationswerte oder die
  Adresse von Paperless

### Requirement: Die Schnittstelle antwortet maschinenlesbar und leitet nie um

Jede Antwort der Schnittstelle MUSS maschinenlesbar strukturiert sein, auch im Fehlerfall.
Ein Fehler MUSS einen festen, maschinenlesbaren Fehlercode und eine lesbare Meldung tragen.
Die Schnittstelle DARF NICHT auf Seiten der Weboberfläche umleiten. Eine Anfrage ohne gültige
Sitzung MUSS im Modus `paperless` mit dem Status „nicht angemeldet“ (401) beantwortet werden.

#### Scenario: Anfrage ohne Sitzung

- **WHEN** im Modus `paperless` die Vorgangsliste der Schnittstelle ohne gültige Sitzung
  abgefragt wird
- **THEN** antwortet der Dienst mit 401 und einem Fehlercode statt mit einer Umleitung zur
  Anmeldeseite

#### Scenario: Unbekannter Vorgang

- **WHEN** das Detail eines nicht vorhandenen Vorgangs abgefragt wird
- **THEN** antwortet der Dienst mit „nicht gefunden“ (404) und einem Fehlercode

### Requirement: Zeitangaben sind eindeutig

Die Schnittstelle MUSS jeden Zeitpunkt als vollständige Zeitangabe mit Zeitzonenbezug
liefern, sodass ein Client ihn ohne Kenntnis der Serverkonfiguration richtig einordnen kann.

#### Scenario: Zeitpunkt eines Vorgangs

- **WHEN** ein Client einen Vorgang mit Anlagezeitpunkt abruft
- **THEN** lässt sich aus der Angabe allein der absolute Zeitpunkt bestimmen

### Requirement: Die Vorgangsliste entspricht der Übersicht der Weboberfläche

Die Schnittstelle MUSS eine Liste der Vorgänge liefern, neueste zuerst, mit denselben
Filtermöglichkeiten wie die Weboberfläche: Zustand, Suchbegriff im ursprünglichen Dateinamen
und Zeitraum. Ein unbekannter Zustand als Filter MUSS wie in der Weboberfläche wie „kein
Filter“ behandelt werden. Die Liste MUSS seitenweise abrufbar sein, höchstens 200 Vorgänge
je Abruf. Zu jedem Vorgang MUSS sie mindestens liefern:

- Kennung, ursprünglicher Dateiname, Zustand und Dokumenttyp
- Gesamtseitenzahl, verarbeitete Seiten und Zahl der Versuche
- Zeitpunkt des nächsten Versuchs und Fehlermeldung
- Anlage-, Start- und Endzeitpunkt

Zusätzlich MUSS die Schnittstelle die Zahl der Vorgänge je Zustand über den gesamten Bestand
liefern, unabhängig vom Filter.

#### Scenario: Ungefilterte Liste

- **WHEN** ein angemeldeter Client die Vorgangsliste ohne Filter abruft
- **THEN** erhält er die neuesten Vorgänge in absteigender Reihenfolge und die Zähler je
  Zustand

#### Scenario: Filter nach Zustand und Suchbegriff

- **WHEN** ein Client die Liste mit dem Zustand `failed` und einem Suchbegriff abruft
- **THEN** enthält sie nur gescheiterte Vorgänge, deren ursprünglicher Dateiname den
  Suchbegriff enthält, und die Zähler beziehen sich weiterhin auf den gesamten Bestand

#### Scenario: Weitere Seite

- **WHEN** ein Client nach den ersten 200 Vorgängen die nächste Seite abruft
- **THEN** erhält er die darauf folgenden älteren Vorgänge ohne Überschneidung

#### Scenario: Unbekannter Zustand als Filter

- **WHEN** die Liste mit einem Zustand abgerufen wird, den es nicht gibt
- **THEN** erhält der Client dieselbe Liste wie ohne Zustandsfilter

### Requirement: Das Vorgangsdetail enthält den Verlauf und die Entscheidungsgrundlage

Die Schnittstelle MUSS zu einem Vorgang alle Angaben der Liste und seine Verlaufseinträge in
zeitlicher Reihenfolge liefern, je Eintrag mit Zeitpunkt, Art und Meldung. Für einen
angehaltenen Vorgang (`blocked`) MUSS sie die festgestellte Seitenzahl und die geltende
Seitenobergrenze nennen, also die Tatsachen, die auch die Weboberfläche für die Entscheidung
anzeigt. Außerdem MUSS sie die zulässige Zahl der Versuche liefern.

#### Scenario: Detail eines abgeschlossenen Vorgangs

- **WHEN** ein Client das Detail eines Vorgangs im Zustand `done` abruft
- **THEN** erhält er dessen Angaben und alle Verlaufseinträge in zeitlicher Reihenfolge

#### Scenario: Detail eines angehaltenen Vorgangs

- **WHEN** ein Client das Detail eines Vorgangs im Zustand `blocked` abruft
- **THEN** enthält die Antwort die festgestellte Seitenzahl und die geltende Seitenobergrenze

### Requirement: Angehaltene Vorgänge lassen sich über die Schnittstelle entscheiden

Die Schnittstelle MUSS für einen angehaltenen Vorgang dieselben beiden Entscheidungen
anbieten wie die Weboberfläche, Freigeben und Verwerfen. Sie MUSS sie mit derselben Wirkung
ausführen. Eine erfolgreiche Entscheidung MUSS mit dem aktualisierten Vorgang beantwortet
werden. Eine Entscheidung über einen Vorgang, der nicht (mehr) angehalten ist, MUSS als
Konflikt (409) beantwortet werden und DARF nichts verändern. Scheitert das Verwerfen beim
Verschieben des Originals, MUSS die Schnittstelle dies als eigenen Fehler melden. Der Vorgang
bleibt dann angehalten.

#### Scenario: Freigeben

- **WHEN** ein angemeldeter Client einen angehaltenen Vorgang freigibt
- **THEN** wird der Vorgang wie bei einer Freigabe in der Weboberfläche wieder aufgenommen,
  und die Antwort enthält den aktualisierten Vorgang

#### Scenario: Doppelte Entscheidung

- **WHEN** ein Client einen Vorgang verwirft, der bereits freigegeben wurde
- **THEN** antwortet der Dienst mit 409 und einem Fehlercode, und der Vorgang bleibt unverändert

#### Scenario: Verwerfen scheitert

- **WHEN** das Original beim Verwerfen nicht in den Fehlerordner verschoben werden kann
- **THEN** meldet die Schnittstelle den Fehlschlag mit eigenem Fehlercode, und der Vorgang
  bleibt angehalten

### Requirement: Der Ereignisstrom ist für Clients der Schnittstelle nutzbar

Der Dienst MUSS den bestehenden Ereignisstrom für Live-Aktualisierungen auch Clients
zugänglich machen, die sich mit einem Zugangsschlüssel ausweisen. Jedes Ereignis zu einem
Vorgang MUSS als solches erkennbar sein und die Kennung des geänderten Vorgangs tragen,
damit der Client gezielt nachladen kann. Das gilt auch für einen Vorgang, der gerade erst
angelegt wurde. Ereignisse anderer Bereiche darf der Strom weiterhin enthalten.

#### Scenario: Neuer Vorgang nach einem Upload

- **WHEN** ein Client den Ereignisstrom geöffnet hat und eine von ihm übergebene Datei
  aufgenommen wird
- **THEN** erhält er ein Ereignis mit der Kennung des neuen Vorgangs

#### Scenario: Ereignisstrom mit Zugangsschlüssel

- **WHEN** ein Client im Modus `paperless` den Ereignisstrom mit gültigem Zugangsschlüssel und
  ohne Cookie öffnet
- **THEN** bleibt die Verbindung offen und liefert Ereignisse
