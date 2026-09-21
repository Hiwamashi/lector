# Spec Delta

## MODIFIED Requirements

### Requirement: Laufzeitparameter kommen ausschließlich aus Umgebungsvariablen

Der Dienst MUSS sämtliche Laufzeitparameter über Umgebungsvariablen beziehen. Es DARF keine
Konfigurationsdatei geben, die das Laufzeitverhalten bestimmt.

Der Dienst MUSS die Konfiguration beim Start prüfen und den Start abbrechen, wenn eine
Pflichtangabe fehlt oder unbrauchbar ist. Er DARF in diesem Fall keine Arbeit annehmen.
Unbrauchbar ist eine Angabe, die zwar gesetzt ist, aber nicht verwendet werden kann — ein
Wert, der nicht dem verlangten Typ entspricht, oder ein Dateipfad, der auf keine lesbare
Datei zeigt.

Die Ablehnung MUSS begründet werden: Der Dienst MUSS jede beanstandete Angabe beim Namen
nennen, unter dem sie gesetzt wird, und sagen, was an ihr fehlt. Es DARF nicht genügen,
lediglich das Scheitern zu melden.

#### Scenario: Betrieb ohne Konfigurationsdatei

- **WHEN** der Dienst ohne jede Konfigurationsdatei gestartet wird
- **THEN** startet er mit den dokumentierten Standardwerten und den gesetzten
  Umgebungsvariablen, sofern jede Pflichtangabe gesetzt ist

#### Scenario: Eine Pflichtangabe fehlt

- **WHEN** der Dienst mit einer leeren oder nicht gesetzten Pflichtangabe gestartet wird
- **THEN** startet er nicht, nennt die betroffene Angabe und nimmt kein Dokument auf

#### Scenario: Eine Angabe ist gesetzt, aber unbrauchbar

- **WHEN** eine Angabe einen Wert trägt, der nicht dem verlangten Typ entspricht, oder auf
  eine Datei zeigt, die nicht vorhanden oder nicht lesbar ist
- **THEN** startet der Dienst nicht und nennt die betroffene Angabe samt dem, was an ihr
  unbrauchbar ist

#### Scenario: Ein Fehler der Konfiguration erreicht nicht die Verarbeitung

- **WHEN** die Konfiguration unvollständig oder unbrauchbar ist
- **THEN** entsteht kein Vorgang, kein Wiederholversuch und kein Aufruf der Texterkennung

## ADDED Requirements

### Requirement: Die Startprüfung nennt alle Beanstandungen in einem Durchgang

Der Dienst MUSS die Konfiguration vollständig prüfen und alle Beanstandungen gemeinsam
melden. Er DARF nicht bei der ersten Beanstandung abbrechen, denn sonst wird eine
mehrfach unvollständige Konfiguration erst über eine Folge von Neustarts vollständig
sichtbar.

#### Scenario: Mehrere Angaben sind zugleich zu beanstanden

- **WHEN** der Dienst mit mehreren fehlenden oder unbrauchbaren Angaben gestartet wird
- **THEN** nennt die Begründung jede dieser Angaben, nicht nur die erste

### Requirement: Welche Angabe Pflicht ist, richtet sich nach den gesetzten Schaltern

Die Menge der Pflichtangaben MUSS aus der übrigen Konfiguration hervorgehen. Eine Angabe,
die nur ein abgeschaltetes oder nicht gewähltes Teilverhalten betrifft, DARF NICHT verlangt
werden. Insbesondere MÜSSEN die Angaben zur Texterkennung nur für die tatsächlich gewählte
Engine verlangt werden.

#### Scenario: Die gewählte Engine verlangt ihre Angaben

- **WHEN** eine Engine gewählt ist, die eine Cloud-Anbindung benötigt, und deren Angaben
  fehlen
- **THEN** startet der Dienst nicht und nennt diese Angaben

#### Scenario: Eine nicht gewählte Engine verlangt nichts

- **WHEN** eine Engine gewählt ist, die eine bestimmte Angabe nicht benötigt
- **THEN** ist diese Angabe für den Start unerheblich

#### Scenario: Eine unbekannte Engine wird beim Start abgewiesen

- **WHEN** als Engine ein Wert gesetzt ist, zu dem es keine Umsetzung gibt
- **THEN** startet der Dienst nicht und nennt die zulässigen Werte

### Requirement: Ein eingeschaltetes Zusatz-Feature ohne seine Angaben gilt als Fehler

Ist ein Zusatz-Feature ausdrücklich eingeschaltet, MÜSSEN die von ihm benötigten Angaben
vorliegen; andernfalls MUSS der Start abgebrochen werden. Ein eingeschaltetes Feature DARF
NICHT stillschweigend unwirksam bleiben, weil ihm eine Angabe fehlt — das ist von außen
nicht von einem abgeschalteten Feature zu unterscheiden.

Ist das Feature nicht eingeschaltet, MÜSSEN fehlende Angaben folgenlos bleiben.

#### Scenario: Feature eingeschaltet, Angabe fehlt

- **WHEN** ein Zusatz-Feature eingeschaltet ist und eine von ihm benötigte Angabe fehlt
- **THEN** startet der Dienst nicht und nennt Feature und fehlende Angabe

#### Scenario: Feature abgeschaltet, Angabe fehlt

- **WHEN** ein Zusatz-Feature nicht eingeschaltet ist und die von ihm benötigten Angaben
  fehlen
- **THEN** startet der Dienst regulär, und das Feature bleibt unwirksam

### Requirement: Die Arbeitsverzeichnisse müssen beim Start benutzbar sein

Der Dienst MUSS beim Start feststellen, dass er in den Eingangs-, Ausgabe-, Verarbeitet-
und Fehlerordner sowie an den Ort der Datenbank schreiben kann. Ist ein Ordner nicht
beschreibbar, MUSS der Start abgebrochen werden.

Ohne diese Prüfung fällt ein falsch eingehängter oder falsch berechtigter Ordner erst beim
Ablegen des ersten Ergebnisses auf — also nachdem die Texterkennung bereits bezahlt wurde.

#### Scenario: Ein Arbeitsordner ist nicht beschreibbar

- **WHEN** einer der Arbeitsordner beim Start nicht beschreibbar ist
- **THEN** startet der Dienst nicht und nennt den betroffenen Ordner

#### Scenario: Ein Arbeitsordner ist noch nicht vorhanden

- **WHEN** ein Arbeitsordner beim Start nicht existiert, aber angelegt werden kann
- **THEN** wird er angelegt und der Start läuft weiter

### Requirement: Ein abgelehnter Start hinterlässt keine Wirkung

Die Prüfung MUSS vor jeder anderen Wirkung des Starts stattfinden. Wird der Start
abgelehnt, DARF der Dienst keinen Zustand hinterlassen haben, der ohne ihn nicht bestünde —
insbesondere keine neue Datenbank, keine aufgelösten Vorgänge und keine bewegten Dateien.

Ausgenommen sind die Arbeitsordner selbst: Sie anzulegen ist Teil der Feststellung, dass
sie benutzbar sind, und ist für sich genommen wirkungslos wiederholbar.

#### Scenario: Ablehnung vor dem ersten Seiteneffekt

- **WHEN** der Start wegen einer fehlenden oder unbrauchbaren Angabe abgelehnt wird
- **THEN** ist keine Datenbank entstanden, kein Vorgang verändert und keine Datei bewegt
  worden

#### Scenario: Ablehnung wegen eines Ordners

- **WHEN** der Start abgelehnt wird, weil ein Arbeitsordner nicht beschreibbar ist
- **THEN** ist ebenfalls keine Datenbank entstanden und kein Vorgang verändert worden
