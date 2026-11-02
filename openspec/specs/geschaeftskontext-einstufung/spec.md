# geschaeftskontext-einstufung Specification

## Purpose
Schätzt für jede Paperless-Rechnung ein, ob sie zum Geschäftskontext IT-Consulting gehört,
mit einer Konfidenz und einer nachvollziehbaren Herkunft. Grundlage für die Auswahl der
Rechnungen, die nach SevDesk exportiert werden.

## Requirements

### Requirement: Die Kontext-Option ist eine Option des Empfänger-Felds

Der Geschäftskontext MUSS als Option des bestehenden Paperless-Felds „Empfänger“ abgebildet
sein. Ihr Label MUSS konfigurierbar sein, Standard ist `IT-Consulting`. Lector MUSS die Option
nicht selbst anlegen. Fehlt sie im Feld, MUSS die Export-Übersicht das als Hinweis zeigen und
jede Rechnung als „nicht einstufbar“ führen, statt eine Einschätzung zu behaupten.

#### Scenario: Option vorhanden

- **WHEN** das Feld „Empfänger“ die Option `IT-Consulting` enthält
- **THEN** stuft Lector die Rechnungen gegen diese Option ein

#### Scenario: Option fehlt

- **WHEN** das Feld „Empfänger“ keine Option mit dem konfigurierten Label enthält
- **THEN** zeigt die Übersicht einen Hinweis, nennt das erwartete Label und führt alle
  Rechnungen als „nicht einstufbar“

### Requirement: Die Einstufung folgt einer festen Rangfolge der Quellen

Lector MUSS die Einstufung einer Rechnung aus der ersten zutreffenden Quelle dieser Rangfolge
bilden und die Quelle mit ausweisen:

1. **Empfänger:** Ist das Feld „Empfänger“ am Dokument gesetzt, gilt es als maßgeblich —
   Konfidenz 1,0 für IT-Consulting, wenn die Kontext-Option gesetzt ist, sonst 0,0.
2. **Korrespondent:** Liegen zum selben Korrespondenten mindestens zwei andere Rechnungen mit
   entschiedenem Kontext vor (Empfänger gesetzt oder nach SevDesk exportiert) und zeigen sie
   alle in dieselbe Richtung, gilt diese Richtung mit hoher Konfidenz. Widersprechen sie
   sich, wird diese Quelle nicht verwendet.
3. **KI:** Liegt eine KI-Einschätzung vor, gilt deren Wahrscheinlichkeit für IT-Consulting.

Trifft keine Quelle zu, MUSS die Rechnung als „nicht eingeschätzt“ gelten.

#### Scenario: Manuell gesetzter Empfänger schlägt alle anderen Quellen

- **WHEN** eine Rechnung den Empfänger `Familie` trägt und die KI für IT-Consulting 0,9 meldet
- **THEN** gilt die Rechnung mit Konfidenz 0,0 als nicht IT-Consulting, Quelle „Empfänger“

#### Scenario: Eindeutige Korrespondenten-Historie

- **WHEN** eine Rechnung ohne Empfänger von einem Korrespondenten stammt, dessen drei frühere
  Rechnungen alle den Empfänger IT-Consulting tragen
- **THEN** gilt sie mit hoher Konfidenz als IT-Consulting, Quelle „Korrespondent (3/3)“

#### Scenario: Widersprüchliche Historie

- **WHEN** von einem Korrespondenten eine frühere Rechnung IT-Consulting und eine andere
  `Sascha` trägt
- **THEN** wird die Korrespondenten-Historie nicht verwendet und die nächste Quelle greift

#### Scenario: Keine Quelle

- **WHEN** eine Rechnung keinen Empfänger, keine verwertbare Historie und keine KI-Einschätzung
  hat
- **THEN** zeigt die Übersicht „nicht eingeschätzt“

### Requirement: Die KI liefert die IT-Consulting-Wahrscheinlichkeit im Empfänger-Aufruf

Der KI-Aufruf der Empfänger-Zuordnung MUSS neben dem Empfänger-Vorschlag eine eigene
Wahrscheinlichkeit zwischen 0 und 1 liefern, dass das Dokument eine Ausgabe des Kontexts
IT-Consulting ist, unabhängig davon, welcher Empfänger vorgeschlagen wird. Ein Wert außerhalb
von 0..1 oder ein fehlender Wert MUSS als „nicht eingeschätzt“ gelten. Die Einschätzung MUSS
mit dem Vorschlag gespeichert werden, sodass die Übersicht ohne erneuten KI-Aufruf lädt.

#### Scenario: Vorschlag und Einschätzung aus einem Aufruf

- **WHEN** die KI für eine Hosting-Rechnung den Empfänger `Sascha` mit 0,7 vorschlägt
- **THEN** liegt zusätzlich eine IT-Consulting-Wahrscheinlichkeit vor, und es war nur ein
  KI-Aufruf nötig

#### Scenario: Ungültiger Wert

- **WHEN** die KI für die IT-Consulting-Wahrscheinlichkeit den Wert 1,4 liefert
- **THEN** gilt die Rechnung als „nicht eingeschätzt“, der Empfänger-Vorschlag bleibt gültig

#### Scenario: Seitenaufruf löst keine KI aus

- **WHEN** die Export-Übersicht geladen wird
- **THEN** findet kein KI-Aufruf statt; angezeigt werden nur gespeicherte Einschätzungen

### Requirement: Der Batch-Lauf holt fehlende Einschätzungen nach

Der Batch-Lauf der Empfänger-Zuordnung MUSS Dokumente ohne gesetzten Empfänger auch dann
bearbeiten, wenn sie bereits einen Vorschlag, aber noch keine IT-Consulting-Einschätzung
haben. Dokumente mit Vorschlag und Einschätzung MUSS er weiterhin überspringen.

#### Scenario: Alter Vorschlag ohne Einschätzung

- **WHEN** ein Dokument ohne Empfänger einen Vorschlag aus der Zeit vor diesem Change hat
- **THEN** bearbeitet der nächste Batch-Lauf es erneut und ergänzt die Einschätzung

#### Scenario: Vollständiger Eintrag

- **WHEN** ein Dokument ohne Empfänger bereits Vorschlag und Einschätzung hat
- **THEN** überspringt der Batch-Lauf es

### Requirement: Eine Schwelle trennt „IT-Consulting“ von „unsicher“

Eine konfigurierbare Schwelle (Standard 0,75, größer als 0) MUSS festlegen, ab welcher
Konfidenz eine Rechnung in der Übersicht als IT-Consulting gilt. KI-Einschätzungen unterhalb der
Schwelle, aber über 0, MÜSSEN als „unsicher“ erkennbar sein. Einstufungen aus Empfänger oder
Korrespondenten-Historie, die gegen IT-Consulting sprechen, MÜSSEN als „nicht IT-Consulting“
gelten. Der Vergleich mit dem Kontext-Label MUSS Groß- und Kleinschreibung sowie Randleerraum
ignorieren.

#### Scenario: Über der Schwelle

- **WHEN** eine Rechnung eine KI-Einschätzung von 0,91 hat
- **THEN** erscheint sie im Filter „IT-Consulting“

#### Scenario: Unter der Schwelle

- **WHEN** eine Rechnung eine KI-Einschätzung von 0,6 hat
- **THEN** erscheint sie nicht im Filter „IT-Consulting“ und ist als „unsicher“ markiert

#### Scenario: Historie spricht dagegen

- **WHEN** die drei früheren Rechnungen eines Korrespondenten alle den Empfänger `Familie` tragen
- **THEN** gilt eine neue Rechnung dieses Korrespondenten als „nicht IT-Consulting“, nicht als
  „unsicher“
