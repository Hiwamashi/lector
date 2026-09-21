# Spec Delta

## MODIFIED Requirements

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

## ADDED Requirements

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
