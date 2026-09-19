# Spec Delta

## Purpose

Überwacht den Eingangsordner und nimmt eine Datei erst dann in die Verarbeitung auf, wenn
sie vollständig geschrieben, von einem unterstützten Format und nicht bereits in Arbeit ist.

## ADDED Requirements

### Requirement: Nur vollständig geschriebene Dateien werden aufgenommen

Der Dienst MUSS verhindern, dass eine noch im Schreibvorgang befindliche Datei verarbeitet
wird. Eine Datei gilt als vollständig, wenn ihr Name kein Teil-Suffix trägt und ihre Größe
über das Stabilitätsfenster (`STABILITY_WINDOW_SECONDS`, Standard 6 s) unverändert bleibt.
Die Liste der Teil-Suffixe ist über `PARTIAL_SUFFIXES` konfigurierbar (Standard `.tmp`,
`.part`, `.crdownload`).

#### Scenario: Datei mit Teil-Suffix

- **WHEN** eine Datei mit einem konfigurierten Teil-Suffix im Eingangsordner liegt
- **THEN** wird sie nicht aufgenommen, unabhängig davon, wie lange sie unverändert bleibt

#### Scenario: Datei wächst noch

- **WHEN** die Größe einer Datei zwischen zwei Prüfungen abweicht
- **THEN** beginnt das Stabilitätsfenster neu und die Datei wird nicht aufgenommen

#### Scenario: Umbenennung auf den Zielnamen

- **WHEN** eine Datei mit Teil-Suffix auf ihren endgültigen Namen umbenannt wird
- **THEN** wird für den Zielnamen dieselbe Stabilitätsprüfung durchlaufen, bevor die Datei
  aufgenommen wird

#### Scenario: Leere Datei

- **WHEN** eine Datei die Größe 0 hat
- **THEN** wird sie nicht aufgenommen

#### Scenario: Datei verschwindet vor der Aufnahme

- **WHEN** eine beobachtete Datei aus dem Eingangsordner verschwindet, bevor sie als
  vollständig gilt
- **THEN** wird sie nicht mehr beobachtet und erzeugt keinen Eintrag

### Requirement: Jede Eingangsdatei wird höchstens einmal aufgenommen

Der Dienst MUSS sicherstellen, dass eine als vollständig erkannte Datei nur ein einziges Mal
in die Verarbeitung gegeben wird, auch wenn der Eingangsordner mehrfach geprüft wird.

#### Scenario: Wiederholte Prüfung derselben Datei

- **WHEN** dieselbe unveränderte Datei nach ihrer Aufnahme erneut geprüft wird
- **THEN** wird kein zweiter Vorgang für sie angelegt

### Requirement: Nur unterstützte Formate werden aufgenommen

Der Dienst MUSS Dateien mit nicht unterstützter Endung übergehen. Unterstützt sind PDF, TIFF
(`.tif`, `.tiff`), gängige Einzelbilder (`.jpg`, `.jpeg`, `.png`, `.bmp`, `.webp`) und XML.

#### Scenario: Nicht unterstützte Endung

- **WHEN** eine Datei mit einer nicht unterstützten Endung vollständig im Eingangsordner liegt
- **THEN** wird sie übergangen, es entsteht kein Eintrag in der Historie und die Datei bleibt
  unangetastet liegen

### Requirement: Inhaltsgleiche Doppeleingänge werden übersprungen

Der Dienst MUSS den Inhalt einer Eingangsdatei anhand einer Prüfsumme mit den Vorgängen
abgleichen, die noch nicht abgeschlossen sind, und einen inhaltsgleichen Doppeleingang
übergehen.

#### Scenario: Gleiche Datei erneut abgelegt, während der erste Vorgang läuft

- **WHEN** eine inhaltsgleiche Datei abgelegt wird, während zu derselben Prüfsumme noch ein
  aktiver Vorgang existiert
- **THEN** wird kein zweiter Vorgang angelegt

#### Scenario: Gleiche Datei nach Abschluss erneut abgelegt

- **WHEN** eine inhaltsgleiche Datei abgelegt wird, nachdem der frühere Vorgang abgeschlossen
  ist
- **THEN** wird sie als neuer Vorgang aufgenommen

### Requirement: Aufnahme erzeugt einen Vorgang im Ausgangszustand

Der Dienst MUSS für jede aufgenommene Datei einen Vorgang mit dem ursprünglichen Dateinamen,
dem Quellpfad und der Prüfsumme anlegen und ihn im Zustand `pending` in die Verarbeitung
einreihen.

#### Scenario: Vollständige Datei wird aufgenommen

- **WHEN** eine unterstützte, vollständige und nicht doppelte Datei erkannt wird
- **THEN** entsteht ein Vorgang mit Status `pending`, der ursprüngliche Dateiname bleibt
  erhalten, und der Vorgang steht in der Verarbeitungsreihe

### Requirement: Eingang reagiert ereignisgesteuert und zeitgesteuert

Der Dienst MUSS den Eingangsordner sowohl bei Dateisystemereignissen als auch in einem festen
Intervall (`POLL_INTERVAL_SECONDS`, Standard 2 s) prüfen, damit weder ein verpasstes Ereignis
noch ein nicht meldendes Dateisystem die Aufnahme dauerhaft verhindert.

#### Scenario: Dateisystem meldet keine Ereignisse

- **WHEN** eine Datei abgelegt wird, ohne dass ein Dateisystemereignis eintrifft
- **THEN** wird sie spätestens bei der nächsten zeitgesteuerten Prüfung erkannt

#### Scenario: Fehler bei einer Prüfung

- **WHEN** eine Prüfung des Eingangsordners fehlschlägt
- **THEN** wird der Fehler protokolliert und die nächste Prüfung findet weiterhin statt
