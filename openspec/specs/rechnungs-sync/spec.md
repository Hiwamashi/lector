# rechnungs-sync Specification

## Purpose
Hält Lectors Rechnungsliste mit den Rechnungen in Paperless aktuell, ohne den Dienst während
des Abgleichs lahmzulegen und ohne Datenbank und offene Browser mit unveränderten Daten zu
belasten.

## Requirements

### Requirement: Der Sync schreibt nur geänderte Rechnungen

Beim regelmäßigen Abgleich MUSS der Dienst eine Rechnung nur dann in seiner Datenbank
schreiben, wenn sie neu ist oder sich mindestens eine ihrer aus Paperless übernommenen Angaben
geändert hat: Titel, Korrespondent, Rechnungsdatum, Empfänger oder Beleg-Vermerk. Eine
unveränderte Rechnung DARF weder geschrieben werden noch ein Live-Signal an offene Ansichten
auslösen. Angaben, die in Paperless nicht auflösbar sind (fehlendes Feld), gelten als
unverändert.

#### Scenario: Nichts geändert

- **WHEN** ein Sync-Lauf alle Rechnungen unverändert vorfindet
- **THEN** bleibt die Rechnungstabelle unverändert und keine geöffnete Rechnungsansicht wird
  neu geladen

#### Scenario: Titel geändert

- **WHEN** der Titel einer Rechnung in Paperless geändert wurde
- **THEN** zeigt Lector nach dem nächsten Lauf den neuen Titel, und nur diese Rechnung erhält
  ein Live-Signal

#### Scenario: Neue Rechnung

- **WHEN** in Paperless eine neue Rechnung hinzugekommen ist
- **THEN** legt der nächste Lauf sie in Lector an, wie bisher mit Zahldaten-Auslese

### Requirement: Rechnungen zeigen den Zeitpunkt der letzten Änderung

Die Rechnungsdetails MÜSSEN anzeigen, wann der Sync die übernommenen Angaben der Rechnung
zuletzt geändert oder sie angelegt hat, beschriftet als „Zuletzt geändert“. Ein Lauf ohne
Änderung DARF diesen Zeitpunkt NICHT verschieben.

#### Scenario: Lauf ohne Änderung

- **WHEN** eine Rechnung zuletzt vor drei Tagen geändert wurde und seitdem mehrere Läufe
  stattfanden
- **THEN** zeigen die Details weiterhin den Zeitpunkt von vor drei Tagen

### Requirement: Lector bleibt während eines Sync-Laufs bedienbar

Während eines Sync-Laufs MUSS der Dienst Anfragen an Weboberfläche, Schnittstelle und
Statusabfrage weiter beantworten. Ein Lauf ohne Änderungen DARF die Antwort auf eine Anfrage um
nicht mehr als 2 Sekunden verzögern. Andere Hintergrundaufgaben, insbesondere die
Scan-Verknüpfung, DÜRFEN durch einen solchen Lauf NICHT in eine Zeitüberschreitung geraten.

#### Scenario: Statusabfrage während des Syncs

- **WHEN** während eines Sync-Laufs mit rund 800 unveränderten Rechnungen `/healthz` abgefragt
  wird
- **THEN** antwortet der Dienst innerhalb von 2 Sekunden

### Requirement: Der Sync protokolliert seine Laufzeit

Der Dienst MUSS je Sync-Lauf protokollieren, wie lange der Abgleich der Rechnungen gedauert hat
und wie viele Rechnungen neu oder geändert waren, ohne Dokumentinhalte oder Titel zu nennen.

#### Scenario: Log nach einem Lauf

- **WHEN** ein Sync-Lauf endet
- **THEN** enthält das Log eine Zeile mit Dauer, Zahl der geprüften und Zahl der geänderten
  Rechnungen

### Requirement: Ein nicht auflösbarer Korrespondent überschreibt den gespeicherten Namen nicht
Der Rechnungs-Sync MUST den gespeicherten Korrespondenten einer Rechnung unverändert lassen, wenn das
Paperless-Dokument einen Korrespondenten hat, dessen Name im Lauf nicht ermittelt werden kann. Nur
wenn das Dokument keinen Korrespondenten hat, MUST der Sync das Feld leeren.

#### Scenario: Einzelabruf schlägt fehl, Rechnung besteht schon
- **WHEN** eine gespeicherte Rechnung den Korrespondenten „A“ hat, die Korrespondenten-ID ihres Dokuments
  in der Karte des Laufs fehlt und der Einzelabruf mit einem Fehler endet
- **THEN** bleibt der Korrespondent „A“ gespeichert

#### Scenario: Nur der Korrespondent war betroffen
- **WHEN** der Name wie oben nicht auflösbar ist und sich sonst keine gespiegelte Angabe geändert hat
- **THEN** gilt die Rechnung als unverändert: kein Schreiben, kein `synced`-Ereignis, kein Live-Signal

#### Scenario: Andere Angabe hat sich geändert
- **WHEN** der Name nicht auflösbar ist und sich der Titel des Dokuments geändert hat
- **THEN** wird der neue Titel gespeichert und der Korrespondent bleibt unverändert

#### Scenario: Neue Rechnung mit nicht auflösbarem Korrespondenten
- **WHEN** eine Rechnung neu angelegt wird und der Name ihres Korrespondenten nicht auflösbar ist
- **THEN** wird sie ohne Korrespondent angelegt, und ein späterer Lauf mit erfolgreicher Auflösung trägt
  den Namen als Änderung nach

#### Scenario: Dokument ohne Korrespondent
- **WHEN** das Paperless-Dokument keinen Korrespondenten hat und die gespeicherte Rechnung den
  Korrespondenten „A“ führt
- **THEN** wird der Korrespondent geleert

#### Scenario: Fehlschlag wird protokolliert
- **WHEN** der Einzelabruf eines Korrespondentennamens fehlschlägt
- **THEN** schreibt der Sync eine Warnung mit Korrespondenten-ID und Fehlertyp ins Log
