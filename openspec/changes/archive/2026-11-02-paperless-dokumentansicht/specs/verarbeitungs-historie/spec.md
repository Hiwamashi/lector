# Spec Delta

## MODIFIED Requirements

### Requirement: Die Weboberfläche zeigt Übersicht und Detail

Der Dienst MUSS eine Weboberfläche bereitstellen, die den aktuellen Bestand nach Zustand
gegliedert zeigt, eine Liste der Vorgänge führt und zu jedem Vorgang eine Detailansicht mit
dem vollständigen Verlauf anbietet. Jeder Zustand, den ein Vorgang annehmen kann, MUSS in
der Gliederung und im Filter vertreten sein; es DARF kein Zustand geben, der nur in der
Datenbank existiert und in der Oberfläche unsichtbar bleibt. Die Detailansicht MUSS sich aus
der Liste zusätzlich als Seitenleiste neben der Liste öffnen lassen, mit demselben Verhalten
wie die Seitenleiste der Paperless-Dokumentansicht (Adresse, Tastatur, Fensterbreite).
Live-Aktualisierungen eines Vorgangs MÜSSEN auch in der Seitenleiste ankommen.

#### Scenario: Übersicht aufrufen

- **WHEN** die Startseite aufgerufen wird
- **THEN** sind die Vorgänge mit ihrem Zustand sichtbar und nach Zustand filterbar

#### Scenario: Detailansicht aufrufen

- **WHEN** ein einzelner Vorgang geöffnet wird
- **THEN** sind seine Stammdaten und sein vollständiger Verlauf sichtbar

#### Scenario: Detail als Seitenleiste

- **WHEN** der Nutzer in der Liste einen Vorgang anklickt
- **THEN** öffnen sich Stammdaten und Verlauf als Seitenleiste neben der Liste, und die
  Liste behält Filter und Scrollposition

#### Scenario: Live-Fortschritt in der Seitenleiste

- **WHEN** die Seitenleiste einen Vorgang zeigt, der gerade verarbeitet wird
- **THEN** erscheinen neue Verlaufseinträge und Fortschritt ohne Neuladen in der Seitenleiste

#### Scenario: Leerer Bestand

- **WHEN** zu einem gewählten Filter kein Vorgang existiert
- **THEN** erklärt die Oberfläche den leeren Zustand, statt nur eine leere Liste zu zeigen

#### Scenario: Angehaltene Vorgänge in der Übersicht

- **WHEN** mindestens ein Vorgang angehalten ist
- **THEN** weist die Übersicht ihn als eigenen Zustand mit eigener Zählung aus und lässt sich
  auf ihn filtern
