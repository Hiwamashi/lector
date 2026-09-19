# Spec Delta

## ADDED Requirements

### Requirement: Nach einem Neustart bleibt kein Vorgang in Bearbeitung zurück

Der Dienst MUSS beim Start jeden Vorgang im Zustand `processing` auflösen, bevor er neue
Arbeit annimmt. Ein solcher Vorgang gehört zu keinem laufenden Prozess mehr, weil die
Verarbeitung streng seriell in genau einem Prozess stattfindet. Nach dem Start DARF kein
Vorgang mehr im Zustand `processing` stehen, der nicht gerade bearbeitet wird.

Die Auflösung MUSS sich nach dem erreichten Fortschritt richten und in einem der bestehenden
Zustände enden. Ein neuer Zustand wird nicht eingeführt.

#### Scenario: Unterbrechung vor der Ablage des Ergebnisses

- **WHEN** der Dienst startet und ein Vorgang auf `processing` steht, für den weder ein
  Ergebnis im Ausgabeordner liegt noch das Original den Eingangsordner verlassen hat
- **THEN** wird der Vorgang erneut zur Verarbeitung eingereiht

#### Scenario: Unterbrechung nach der Ablage des Ergebnisses

- **WHEN** der Dienst startet und für einen Vorgang auf `processing` bereits ein Ergebnis im
  Ausgabeordner liegt
- **THEN** wird der Vorgang abgeschlossen statt wiederholt: das Original wird in den Ordner
  der verarbeiteten Dateien überführt, der Ablageort des Ergebnisses ist am Vorgang
  festgehalten, und der Vorgang erreicht seinen regulären Endzustand

#### Scenario: Unterbrechung nach dem Verschieben des Originals

- **WHEN** der Dienst startet und für einen Vorgang auf `processing` das Ergebnis abgelegt und
  das Original bereits verschoben ist, nur der Abschluss fehlt
- **THEN** wird der Vorgang abgeschlossen und **nicht** als gescheitert gewertet

#### Scenario: Fortschritt nicht eindeutig feststellbar

- **WHEN** der Dienst startet und sich für einen Vorgang auf `processing` nicht eindeutig
  bestimmen lässt, wie weit er gekommen ist
- **THEN** wird er als gescheitert markiert, mit einer Meldung, die die Unterbrechung als
  Ursache benennt, und das Original bleibt zur manuellen Prüfung erhalten

#### Scenario: Auflösung geschieht vor der Annahme neuer Arbeit

- **WHEN** der Dienst startet, während unterbrochene Vorgänge und neue Eingangsdateien
  gleichzeitig vorliegen
- **THEN** sind die unterbrochenen Vorgänge aufgelöst, bevor eine neue Eingangsdatei
  aufgenommen wird

#### Scenario: Erneuter Start ohne unterbrochene Vorgänge

- **WHEN** der Dienst ein zweites Mal startet, nachdem die Auflösung bereits gelaufen ist
- **THEN** verändert die Auflösung nichts

### Requirement: Eine Wiederaufnahme erzeugt keine zweite Ablage

Der Dienst DARF durch die Auflösung eines unterbrochenen Vorgangs kein zweites Ergebnis für
dasselbe Dokument im Ausgabeordner erzeugen. Das gilt auch dann, wenn der Vorgang selbst
nicht festgehalten hat, dass die Ablage bereits stattgefunden hat.

#### Scenario: Ergebnis liegt abgelegt, ist aber am Vorgang nicht vermerkt

- **WHEN** ein Ergebnis für einen unterbrochenen Vorgang im Ausgabeordner liegt, ohne dass der
  Ablageort am Vorgang festgehalten ist
- **THEN** erkennt die Auflösung die vorhandene Ablage und erzeugt keine weitere

#### Scenario: Nachgelagerte Verarbeitung sieht jedes Dokument einmal

- **WHEN** ein Dokument von einer Unterbrechung betroffen war und der Dienst neu gestartet ist
- **THEN** liegt genau ein Ergebnis für dieses Dokument im Ausgabeordner

### Requirement: Die Auflösung ist im Verlauf nachvollziehbar

Der Dienst MUSS für jeden aufgelösten Vorgang festhalten, dass er von einer Unterbrechung
betroffen war und wie er aufgelöst wurde. Zusätzlich MUSS die Zahl der beim Start
aufgelösten Vorgänge im Betriebsprotokoll erscheinen, damit wiederkehrende Unterbrechungen
auffallen.

#### Scenario: Vorgang wurde nach einer Unterbrechung aufgelöst

- **WHEN** die Detailansicht eines Vorgangs geöffnet wird, der von einer Unterbrechung
  betroffen war
- **THEN** ist aus seinem Verlauf ersichtlich, dass eine Unterbrechung vorlag und wie sie
  aufgelöst wurde

#### Scenario: Mehrere Vorgänge gleichzeitig betroffen

- **WHEN** der Dienst startet und mehrere unterbrochene Vorgänge auflöst
- **THEN** nennt das Betriebsprotokoll deren Anzahl
