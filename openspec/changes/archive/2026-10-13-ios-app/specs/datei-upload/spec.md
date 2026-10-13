# Spec Delta

## ADDED Requirements

### Requirement: Die Übergabe ist auch über die App-Schnittstelle möglich

Der Dienst MUSS die Übergabe von Dateien zusätzlich über die App-Schnittstelle anbieten.
Dafür MÜSSEN dieselben Regeln gelten wie für die Übergabe über die Oberfläche:

- Ablage ausschließlich im Eingangsordner
- Sichtbarkeit erst nach vollständiger Übertragung
- Zurückweisung nicht unterstützter Formate
- Absicherung des gelieferten Namens
- kein Überschreiben vorhandener Dateien
- mehrere Dateien in einem Schritt
- keine verwertbare Datei nach gescheiterter Ablage

Statt einer Umleitung MUSS der Dienst eine maschinenlesbare Rückmeldung liefern. Sie nennt
für jede angebotene Datei entweder die Annahme oder die Zurückweisung mit einem Grund, der
zwischen nicht unterstütztem Format, unbrauchbarem Namen und gescheiterter Ablage
unterscheidet. Die Rückmeldung MUSS erfolgen, ohne Aufnahme oder Verarbeitung abzuwarten.
Der Inhalt einer angenommenen Datei DARF bei der Übergabe nicht verändert werden.

#### Scenario: Annahme über die Schnittstelle

- **WHEN** ein angemeldeter Client eine PDF-Datei über die Schnittstelle übergibt
- **THEN** liegt sie byte-genau unverändert im Eingangsordner, und die Rückmeldung nennt sie
  als angenommen

#### Scenario: Gemischte Übergabe über die Schnittstelle

- **WHEN** ein Client in einem Schritt eine PDF-Datei und eine Datei mit nicht unterstützter
  Endung übergibt
- **THEN** wird die PDF-Datei angenommen, und die Rückmeldung nennt die andere Datei mit dem
  Grund „nicht unterstütztes Format“

#### Scenario: E-Rechnung über die Schnittstelle

- **WHEN** ein Client eine ZUGFeRD-PDF über die Schnittstelle übergibt
- **THEN** wird sie wie eine im Eingangsordner abgelegte Datei als E-Rechnung erkannt und
  unverändert durchgereicht

#### Scenario: Übergabe ohne Sitzung

- **WHEN** im Modus `paperless` eine Datei ohne gültige Sitzung über die Schnittstelle
  übergeben wird
- **THEN** antwortet der Dienst mit 401, und im Eingangsordner entsteht keine Datei
