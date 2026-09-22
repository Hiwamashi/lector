# verarbeitungs-lebenszyklus Specification

## Purpose

Führt jeden Vorgang seriell durch definierte Zustände, legt Eingang und Ergebnis an den mit
Paperless vereinbarten Orten ab und regelt Wiederholversuche sowie das Aufräumen alter
Dateien.

## Requirements

### Requirement: Dokumente werden seriell verarbeitet

Der Dienst MUSS die Verarbeitungsreihe streng nacheinander abarbeiten. Es DARF zu keinem
Zeitpunkt mehr als ein Dokument gleichzeitig veredelt werden, damit Speicherbedarf und
Durchsatz gegen die OCR-Engine kalkulierbar bleiben. Ein Dokument DARF nicht mehrfach
gleichzeitig in der Reihe stehen.

#### Scenario: Mehrere Dateien gleichzeitig abgelegt

- **WHEN** mehrere Dokumente gleichzeitig im Eingangsordner erscheinen
- **THEN** werden sie nacheinander verarbeitet, nicht parallel

#### Scenario: Dokument wird erneut eingereiht, während es läuft

- **WHEN** ein bereits in Arbeit befindliches Dokument erneut eingereiht würde
- **THEN** wird es nicht ein zweites Mal aufgenommen

#### Scenario: Weboberfläche bleibt währenddessen bedienbar

- **WHEN** ein rechenintensives Dokument verarbeitet wird
- **THEN** bleibt die Weboberfläche erreichbar und aktualisiert sich weiter

### Requirement: Ein Vorgang durchläuft definierte Zustände

Der Dienst MUSS jeden Vorgang in genau einem der Zustände `pending`, `processing`, `blocked`,
`done`, `skipped_erechnung` oder `failed` führen. `pending` ist der Ausgangszustand und
zugleich der Zustand eines eingeplanten Wiederholversuchs; `done`, `skipped_erechnung` und
`failed` sind Endzustände.

`blocked` ist **kein** Endzustand, sondern ein Wartezustand: Der Vorgang ist angehalten, weil
die Verarbeitung eine Entscheidung des Anwenders erfordert. Er verlässt diesen Zustand
ausschließlich durch eine ausdrückliche Entscheidung — er DARF weder von selbst
weiterlaufen noch von selbst scheitern, und es DARF kein Wiederholversuch für ihn eingeplant
werden.

#### Scenario: Verarbeitung beginnt

- **WHEN** ein Vorgang aus der Reihe genommen wird
- **THEN** wechselt er nach `processing`

#### Scenario: Veredelung erfolgreich

- **WHEN** ein Dokument vollständig veredelt und abgelegt wurde
- **THEN** steht der Vorgang auf `done`

#### Scenario: Angehaltener Vorgang wartet

- **WHEN** ein Vorgang angehalten wurde und keine Entscheidung erfolgt
- **THEN** bleibt er auf `blocked` stehen, ohne Wiederholzeitpunkt und ohne erhöhten
  Versuchszähler

### Requirement: E-Rechnungen werden unverändert durchgereicht

Der Dienst MUSS eine als E-Rechnung erkannte Datei **byte-identisch** in den Ausgabeordner
kopieren. Es DARF keine Texterkennung stattfinden, der Dateiname DARF nicht geändert werden,
und es DÜRFEN keine Paperless-Merkmale gesetzt werden.

#### Scenario: E-Rechnung erkannt

- **WHEN** ein Dokument als E-Rechnung eingestuft wurde
- **THEN** liegt eine inhaltlich unveränderte Kopie unter demselben Namen im Ausgabeordner, das
  Original liegt im Ordner der verarbeiteten Dateien, und der Vorgang steht auf
  `skipped_erechnung`

#### Scenario: Keine Veredelung an E-Rechnungen

- **WHEN** eine E-Rechnung durchgereicht wird
- **THEN** wurde weder eine Texterkennung aufgerufen noch ein Textlayer erzeugt

### Requirement: Ergebnis und Original werden getrennt abgelegt

Der Dienst MUSS das Ergebnis in den Ausgabeordner (`CONSUME_DIR`) und das Eingangsoriginal in
den Ordner der verarbeiteten Dateien (`PROCESSED_DIR`) legen. Das Ergebnis-PDF trägt den
Basisnamen des Originals mit der Endung `.pdf`.

#### Scenario: Veredelung abgeschlossen

- **WHEN** ein Dokument erfolgreich veredelt wurde
- **THEN** liegt das Ergebnis-PDF im Ausgabeordner, das Original im Ordner der verarbeiteten
  Dateien, und der Ablageort des Ergebnisses ist am Vorgang festgehalten

### Requirement: Ergebnisdateien tragen die vereinbarte Eigentümerschaft

Der Dienst MUSS Dateien, die er in den Ausgabeordner schreibt, der über `PUID` und `PGID`
konfigurierten Kennung zuweisen (Standard jeweils 1000), weil dieser Ordner mit Paperless
geteilt wird.

#### Scenario: Ergebnis wird abgelegt

- **WHEN** eine Datei in den Ausgabeordner geschrieben wird
- **THEN** gehört sie der konfigurierten Benutzer- und Gruppenkennung

### Requirement: Namenskollisionen überschreiben nichts

Der Dienst DARF beim Ablegen einer Datei keine bestehende Datei gleichen Namens überschreiben.
Stattdessen MUSS ein unterscheidender Namenszusatz vergeben werden.

#### Scenario: Zieldatei existiert bereits

- **WHEN** im Zielordner bereits eine Datei mit demselben Namen liegt
- **THEN** wird die neue Datei unter einem ergänzten Namen abgelegt und die vorhandene bleibt
  unverändert

### Requirement: Fehler führen zu begrenzten Wiederholversuchen

Der Dienst MUSS einen fehlgeschlagenen Vorgang erneut einplanen, solange die Zahl der
Versuche unter `RETRY_MAX` liegt (Standard 3). Der nächste Versuch wird um
`RETRY_DELAY_MINUTES` (Standard 15) in die Zukunft gelegt und der Vorgang geht zurück nach
`pending`. Ein manuelles Auslösen eines Wiederholversuchs ist nicht vorgesehen.

#### Scenario: Erster Fehlschlag

- **WHEN** die Verarbeitung eines Dokuments fehlschlägt und die Versuchsgrenze noch nicht
  erreicht ist
- **THEN** steht der Vorgang wieder auf `pending`, trägt einen Zeitpunkt für den nächsten
  Versuch, und ein Verlaufseintrag vom Typ `retry_scheduled` nennt Versuchszähler und Grund

#### Scenario: Versuchsgrenze erreicht

- **WHEN** die Verarbeitung im letzten zulässigen Versuch fehlschlägt
- **THEN** wird das Original in den Fehlerordner (`ERROR_DIR`) verschoben, der Vorgang steht
  auf `failed` mit hinterlegter Fehlermeldung, und ein Verlaufseintrag vom Typ `failed` hält
  das fest

#### Scenario: Endgültig fehlgeschlagene Datei bleibt erhalten

- **WHEN** ein Vorgang endgültig fehlgeschlagen ist
- **THEN** bleibt das Original im Fehlerordner liegen und wird nicht automatisch gelöscht

### Requirement: Fällige Wiederholversuche werden auch nach einem Neustart aufgenommen

Der Dienst MUSS beim Start und danach regelmäßig prüfen, welche Vorgänge im Zustand `pending`
zur Wiederholung fällig sind, und sie wieder einreihen.

#### Scenario: Neustart mit eingeplantem Wiederholversuch

- **WHEN** der Dienst neu startet und ein Vorgang auf `pending` mit fälligem Wiederholzeitpunkt
  steht
- **THEN** wird er wieder eingereiht und verarbeitet

### Requirement: Alte verarbeitete Dateien werden automatisch gelöscht

Der Dienst MUSS regelmäßig Dateien aus dem Ordner der verarbeiteten Dateien entfernen, die
älter als `PROCESSED_RETENTION_DAYS` sind (Standard 30). Die Historie in der Datenbank MUSS
dabei erhalten bleiben. Das Aufräumen DARF ausschließlich diesen einen Ordner betreffen und
keine Unterverzeichnisse einbeziehen.

#### Scenario: Datei ist älter als die Aufbewahrungsfrist

- **WHEN** eine Datei im Ordner der verarbeiteten Dateien die Aufbewahrungsfrist überschreitet
- **THEN** wird sie gelöscht, während der zugehörige Vorgang samt Verlauf erhalten bleibt

#### Scenario: Aufbewahrung abgeschaltet

- **WHEN** `PROCESSED_RETENTION_DAYS` auf 0 oder kleiner steht
- **THEN** wird keine Datei gelöscht

#### Scenario: Andere Ordner bleiben unangetastet

- **WHEN** das Aufräumen läuft
- **THEN** bleiben Ausgabeordner, Fehlerordner und Eingangsordner unverändert

#### Scenario: Eine Datei lässt sich nicht löschen

- **WHEN** das Löschen einer einzelnen Datei fehlschlägt
- **THEN** wird das protokolliert und die übrigen Dateien werden weiterhin geprüft

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

### Requirement: Nach einem Neustart bleibt kein Vorgang in Bearbeitung zurück

Der Dienst MUSS beim Start jeden Vorgang im Zustand `processing` auflösen, bevor er neue
Arbeit annimmt. Ein solcher Vorgang gehört zu keinem laufenden Prozess mehr, weil die
Verarbeitung streng seriell in genau einem Prozess stattfindet. Nach dem Start DARF kein
Vorgang mehr im Zustand `processing` stehen, der nicht gerade bearbeitet wird. Ausgenommen
ist der Vorgang, dessen eigene Auflösung selbst fehlschlägt: Er DARF bewusst auf
`processing` stehen bleiben, damit der nächste Start ihn erneut versucht.

Die Auflösung MUSS sich nach dem erreichten Fortschritt richten und in einem der bestehenden
Zustände enden. Ein neuer Zustand wird nicht eingeführt.

#### Scenario: Unterbrechung vor der Ablage des Ergebnisses

- **WHEN** der Dienst startet, ein Vorgang auf `processing` steht, für den weder ein Ergebnis im
  Ausgabeordner liegt noch das Original den Eingangsordner verlassen hat, und die
  Versuchsgrenze (`RETRY_MAX`) noch nicht erreicht ist
- **THEN** wird der Vorgang erneut zur Verarbeitung eingereiht: der Versuchszähler steigt, der
  Vorgang steht wieder auf `pending` mit einem Zeitpunkt für den nächsten Versuch, und das
  Original bleibt im Eingangsordner

#### Scenario: Unterbrechung vor der Ablage des Ergebnisses, Versuchsgrenze erreicht

- **WHEN** der Dienst startet, ein Vorgang auf `processing` steht, für den weder ein Ergebnis im
  Ausgabeordner liegt noch das Original den Eingangsordner verlassen hat, und dies bereits der
  letzte zulässige Versuch war
- **THEN** wird das Original in den Fehlerordner verschoben und der Vorgang steht auf `failed`
  mit hinterlegter Fehlermeldung

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

#### Scenario: Auflösung eines einzelnen Vorgangs schlägt fehl

- **WHEN** der Dienst startet und die Auflösung für einen von mehreren unterbrochenen
  Vorgängen selbst mit einem Fehler abbricht
- **THEN** bleibt dieser Vorgang auf `processing` stehen, der Fehler wird protokolliert, die
  übrigen unterbrochenen Vorgänge werden dennoch aufgelöst, und der Start gelingt

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

### Requirement: Ein angehaltener Vorgang behält sein Original im Eingangsordner

Der Dienst MUSS das Original eines angehaltenen Vorgangs im Eingangsordner belassen, weil
noch nicht entschieden ist, ob es verarbeitet wird. Er DARF für dieselbe Datei keinen
zweiten Vorgang anlegen, solange der erste angehalten ist.

#### Scenario: Eingangsordner wird erneut geprüft

- **WHEN** der Eingangsordner geprüft wird, während dort das Original eines angehaltenen
  Vorgangs liegt
- **THEN** entsteht kein zweiter Vorgang für diese Datei

#### Scenario: Neustart während eine Datei angehalten ist

- **WHEN** der Dienst neu startet und das Original eines angehaltenen Vorgangs im
  Eingangsordner liegt
- **THEN** bleibt der Vorgang angehalten und die Datei wird nicht erneut aufgenommen

### Requirement: Ein angehaltener Vorgang wird freigegeben oder verworfen

Der Dienst MUSS für jeden angehaltenen Vorgang genau zwei Entscheidungen anbieten, damit der
Wartezustand keine Sackgasse ist:

- **Freigeben:** Der Vorgang geht zurück in die reguläre Verarbeitungsreihe und wird
  verarbeitet, obwohl der Grund der Blockade fortbesteht.
- **Verwerfen:** Der Vorgang wird nicht verarbeitet. Das Original wird in den Fehlerordner
  verschoben und bleibt dort erhalten; der Vorgang erreicht den Endzustand `failed` mit einer
  Meldung, die das Verwerfen als Ursache benennt.

Eine Entscheidung DARF nur auf einen Vorgang wirken, der tatsächlich angehalten ist. Für
einen Vorgang in einem anderen Zustand MUSS sie wirkungslos bleiben und als solche erkennbar
sein.

#### Scenario: Vorgang wird freigegeben

- **WHEN** ein angehaltener Vorgang freigegeben wird
- **THEN** steht er wieder in der Verarbeitungsreihe und wird ohne weiteres Zutun verarbeitet

#### Scenario: Vorgang wird verworfen

- **WHEN** ein angehaltener Vorgang verworfen wird
- **THEN** liegt das Original im Fehlerordner, der Vorgang steht auf `failed`, und es wurde
  keine Texterkennung ausgeführt

#### Scenario: Entscheidung für einen Vorgang, der nicht angehalten ist

- **WHEN** eine Freigabe oder ein Verwerfen für einen Vorgang angefordert wird, der nicht auf
  `blocked` steht
- **THEN** ändert sich sein Zustand nicht, und die Anforderung wird als unzulässig beantwortet

#### Scenario: Original fehlt bei der Freigabe

- **WHEN** ein angehaltener Vorgang freigegeben wird, dessen Original inzwischen nicht mehr
  im Eingangsordner liegt
- **THEN** wird er nicht wieder eingereiht, sondern erreicht `failed` mit einer Meldung, die
  das fehlende Original benennt

### Requirement: Eine Entscheidung wirkt ohne Neustart des Dienstes

Der Dienst MUSS einen freigegebenen Vorgang von sich aus wieder aufnehmen, ohne dass der
Dienst neu gestartet oder eine Datei erneut abgelegt werden muss.

#### Scenario: Freigabe im laufenden Betrieb

- **WHEN** ein Vorgang während des Betriebs freigegeben wird
- **THEN** beginnt seine Verarbeitung, ohne dass ein weiterer Eingriff nötig ist

### Requirement: Bewahrte Zwischenergebnisse werden freigegeben, sobald sie entbehrlich sind

Der Dienst MUSS die bewahrten Blockergebnisse eines Vorgangs entfernen, sobald dieser einen
Endzustand erreicht — gleich welchen. Sie dienen ausschließlich dem Wiederholversuch; nach
`done`, `skipped_erechnung` oder `failed` gibt es keinen mehr.

Zusätzlich MUSS der Dienst Zwischenergebnisse entfernen, die älter als
`CHUNK_CACHE_RETENTION_DAYS` (Standard 7) sind, damit Reste eines abgebrochenen Laufs nicht
dauerhaft liegen bleiben. Ein Wert kleiner oder gleich 0 schaltet dieses Verfallen ab.

Das Entfernen DARF weder den Vorgang noch seinen Verlauf antasten: Die Historie bleibt
vollständig erhalten.

#### Scenario: Vorgang erfolgreich abgeschlossen

- **WHEN** ein Dokument vollständig veredelt und abgelegt wurde
- **THEN** sind seine bewahrten Blockergebnisse entfernt, während Vorgang und Verlauf
  unverändert abrufbar bleiben

#### Scenario: Vorgang endgültig gescheitert

- **WHEN** ein Vorgang seinen letzten Versuch verbraucht hat und auf `failed` steht
- **THEN** sind seine bewahrten Blockergebnisse entfernt

#### Scenario: Wiederholversuch eingeplant

- **WHEN** ein Vorgang gescheitert ist, aber ein Wiederholversuch eingeplant wurde
- **THEN** bleiben seine bewahrten Blockergebnisse erhalten — sie werden gerade dann
  gebraucht

#### Scenario: Rest eines abgebrochenen Laufs

- **WHEN** Zwischenergebnisse älter als die Verfallsfrist sind
- **THEN** werden sie entfernt, auch wenn der zugehörige Vorgang keinen Endzustand erreicht
  hat

#### Scenario: Verfallen abgeschaltet

- **WHEN** `CHUNK_CACHE_RETENTION_DAYS` auf 0 oder kleiner steht
- **THEN** verfallen Zwischenergebnisse nicht von selbst, werden aber weiterhin bei Erreichen
  eines Endzustands entfernt

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
