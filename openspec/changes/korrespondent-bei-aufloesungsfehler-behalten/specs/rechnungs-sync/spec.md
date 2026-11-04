# Spec Delta

## ADDED Requirements

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
