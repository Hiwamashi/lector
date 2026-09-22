# Spec Delta

## MODIFIED Requirements

### Requirement: Der Dienst bietet einen Health-Endpunkt

Der Dienst MUSS einen Endpunkt bereitstellen, über den eine Überwachung prüfen kann, ob er
betriebsbereit ist. Betriebsbereit heißt: Er antwortet, **und** die Bestandteile, die er
zum Arbeiten braucht, sind vorhanden.

Der Endpunkt MUSS mindestens feststellen, dass die Datenbank benutzbar ist, dass die
laufenden Hintergrundarbeiten nicht beendet sind und dass die Überwachung des
Eingangsordners noch läuft. Ist eine dieser Tatsachen nicht gegeben, MUSS der Endpunkt mit
einem Fehlerstatus antworten, damit eine Überwachung ohne Auswertung des Antwortinhalts
auskommt.

Die Antwort MUSS erkennen lassen, **welche** Prüfung fehlgeschlagen ist. Ein blosses
„ungesund" verlagert die Fehlersuche vollständig ins Protokoll.

Der Endpunkt DARF NICHT die Erreichbarkeit fremder Dienste prüfen — weder die der
Texterkennung noch die von Paperless oder SevDesk. Ein Aussetzer dort ist kein Mangel
dieses Dienstes, und ein davon abhängiger Zustand würde den Container als ungesund
ausweisen, während die Veredelung einwandfrei arbeitet.

#### Scenario: Health-Endpunkt abfragen

- **WHEN** der Health-Endpunkt bei betriebsbereitem Dienst aufgerufen wird
- **THEN** antwortet der Dienst mit einem Erfolgsstatus und weist jede einzelne Prüfung als
  bestanden aus

#### Scenario: Eine Hintergrundarbeit ist beendet

- **WHEN** eine der Hintergrundarbeiten nicht mehr läuft und der Health-Endpunkt aufgerufen
  wird
- **THEN** antwortet der Dienst mit einem Fehlerstatus und benennt die beendete Arbeit

#### Scenario: Die Datenbank ist nicht benutzbar

- **WHEN** die Datenbank nicht mehr abgefragt werden kann und der Health-Endpunkt
  aufgerufen wird
- **THEN** antwortet der Dienst mit einem Fehlerstatus und benennt die Datenbank

#### Scenario: Die Überwachung des Eingangsordners läuft nicht mehr

- **WHEN** die ereignisgesteuerte Überwachung des Eingangsordners beendet ist und der
  Health-Endpunkt aufgerufen wird
- **THEN** antwortet der Dienst mit einem Fehlerstatus und benennt die Überwachung

#### Scenario: Ein fremder Dienst ist nicht erreichbar

- **WHEN** Paperless, SevDesk oder die Texterkennung nicht erreichbar sind, der Dienst
  selbst aber arbeitsfähig ist
- **THEN** antwortet der Health-Endpunkt weiterhin mit einem Erfolgsstatus

## ADDED Requirements

### Requirement: Der Health-Endpunkt beobachtet, ohne einzugreifen

Der Health-Endpunkt DARF den Betrieb nicht verändern. Er DARF insbesondere keine beendete
Hintergrundarbeit neu starten, keinen Vorgang anstoßen und keinen Zustand schreiben.

Eine beendete Hintergrundarbeit ist ein struktureller Fehler und kein Betriebsrauschen:
Jeder Arbeitsschritt fängt seine Fehler bereits einzeln ab und läuft weiter. Wird ein
solcher Fehler stillschweigend behoben, wiederholt er sich unbemerkt, statt aufzufallen.

#### Scenario: Abfrage bei beendeter Hintergrundarbeit

- **WHEN** der Health-Endpunkt bei einer beendeten Hintergrundarbeit mehrfach abgefragt wird
- **THEN** bleibt die Arbeit beendet, und jede Antwort meldet denselben Fehlerstatus

#### Scenario: Abfrage verändert die Historie nicht

- **WHEN** der Health-Endpunkt abgefragt wird
- **THEN** entsteht kein Vorgang und kein Verlaufseintrag

### Requirement: Die Container-Ebene nutzt den Health-Endpunkt

Das Betriebsabbild MUSS einen eigenen Zustandstest mitbringen, der den Health-Endpunkt
abfragt, damit der Zustand des Dienstes ohne Kenntnis seiner Innereien ablesbar ist. Die
Compose-Vorlage MUSS diesen Zustandstest ausweisen.

Der Zustandstest DARF keine Abhängigkeit voraussetzen, die im Betriebsabbild nicht ohnehin
vorhanden ist.

#### Scenario: Zustand von außen ablesbar

- **WHEN** der Dienst als Container läuft und seine Hintergrundarbeiten laufen
- **THEN** weist der Container sich als gesund aus

#### Scenario: Ungesunder Dienst im Container

- **WHEN** der Health-Endpunkt des laufenden Containers einen Fehlerstatus meldet
- **THEN** weist der Container sich als ungesund aus

#### Scenario: Keine zusätzliche Abhängigkeit

- **WHEN** das Betriebsabbild gebaut wird
- **THEN** kommt der Zustandstest ohne ein Paket aus, das allein für ihn aufgenommen wurde
