# Spec Delta

## ADDED Requirements

### Requirement: Die Seitenzahl wird vor der Texterkennung gegen eine Obergrenze geprüft

Der Dienst MUSS die Gesamtseitenzahl eines Dokuments ermitteln und gegen
`MAX_PAGES_PER_DOCUMENT` (Standard 100) prüfen, **bevor** er die erste Seite an die Engine
gibt. Überschreitet ein Dokument die Grenze, DARF keine Seite an die Engine gegeben werden —
es DÜRFEN also keine Kosten entstehen. Ein Wert kleiner oder gleich 0 schaltet die Prüfung
ab.

Die Prüfung MUSS unabhängig von der eingesetzten Engine gelten und unabhängig vom
Seitenlimit der Engine sein: Das Engine-Limit bestimmt die Blockgröße, diese Grenze bestimmt,
ob überhaupt verarbeitet wird.

#### Scenario: Dokument über der Grenze

- **WHEN** ein Dokument mehr Seiten hat als `MAX_PAGES_PER_DOCUMENT`
- **THEN** wird die Engine für dieses Dokument nicht aufgerufen, und der Vorgang wird
  angehalten, statt verarbeitet zu werden

#### Scenario: Dokument genau auf der Grenze

- **WHEN** ein Dokument genau so viele Seiten hat wie `MAX_PAGES_PER_DOCUMENT`
- **THEN** wird es regulär verarbeitet — die Grenze ist eingeschlossen

#### Scenario: Prüfung abgeschaltet

- **WHEN** `MAX_PAGES_PER_DOCUMENT` auf 0 oder kleiner steht
- **THEN** wird jedes Dokument unabhängig von seiner Seitenzahl verarbeitet

#### Scenario: Die Seitenzahl steht fest, bevor gerechnet wird

- **WHEN** ein Dokument über der Grenze eingeht
- **THEN** hat der Dienst weder die Seiten aufbereitet noch die Engine befragt, und die
  ermittelte Seitenzahl ist am Vorgang festgehalten

#### Scenario: E-Rechnung bleibt unberührt

- **WHEN** eine als E-Rechnung erkannte Datei eingeht
- **THEN** greift die Grenze nicht, weil an ihr keine Texterkennung stattfindet

### Requirement: Eine erteilte Freigabe hebt die Grenze für genau diesen Vorgang auf

Der Dienst MUSS eine erteilte Freigabe dauerhaft am Vorgang festhalten und die Grenzprüfung
für ihn danach übergehen. Die Freigabe DARF ausschließlich für diesen einen Vorgang gelten —
sie DARF weder die konfigurierte Grenze ändern noch andere Vorgänge beeinflussen. Sie MUSS
auch über einen Wiederholversuch und über einen Neustart des Dienstes hinweg gelten, damit
ein freigegebenes Dokument nicht erneut am selben Punkt hängen bleibt.

#### Scenario: Freigegebenes Dokument wird verarbeitet

- **WHEN** ein angehaltener Vorgang freigegeben wird
- **THEN** durchläuft er die Texterkennung vollständig, obwohl er die Grenze weiterhin
  überschreitet

#### Scenario: Freigegebenes Dokument scheitert und wird wiederholt

- **WHEN** die Verarbeitung eines freigegebenen Dokuments fehlschlägt und ein Wiederholversuch
  stattfindet
- **THEN** wird der Vorgang beim Wiederholversuch nicht erneut angehalten

#### Scenario: Freigabe überlebt einen Neustart

- **WHEN** der Dienst neu startet, nachdem ein Vorgang freigegeben, aber noch nicht
  verarbeitet wurde
- **THEN** bleibt die Freigabe erhalten und der Vorgang wird verarbeitet

#### Scenario: Ein anderes großes Dokument bleibt angehalten

- **WHEN** ein Vorgang freigegeben wurde und danach ein weiteres Dokument über der Grenze
  eingeht
- **THEN** wird dieses zweite Dokument angehalten
