# ocr-veredelung Specification

## Purpose

Wandelt bildhafte Dokumente in ein einzelnes durchsuchbares PDF um, das die Seiten sichtbar
zeigt und den erkannten Text unsichtbar und positionsgetreu darüberlegt.

## Requirements

### Requirement: Jede Seite wird vor der Texterkennung aufbereitet

Der Dienst MUSS jede Seite vor der Texterkennung aufbereiten. Die Aufbereitung umfasst eine
Schieflagenkorrektur und eine Kontrast-/Graustufenanpassung. Beide Schritte MÜSSEN einzeln
über `PREPROCESS_DESKEW` bzw. `PREPROCESS_CONTRAST` abschaltbar sein; beide sind standardmäßig
aktiv.

#### Scenario: Schieflagenkorrektur abgeschaltet

- **WHEN** `PREPROCESS_DESKEW` auf falsch steht
- **THEN** wird die Seite ohne Schieflagenkorrektur an die Texterkennung gegeben

#### Scenario: Seite ohne erkennbaren Text

- **WHEN** eine Seite zu wenige Textpixel für eine Winkelschätzung enthält
- **THEN** wird sie unverändert weitergereicht statt willkürlich gedreht

### Requirement: Die Seitenorientierung wird nicht lokal korrigiert

Der Dienst DARF Seiten nicht selbst um 90°, 180° oder 270° drehen. Die Bestimmung der
Leserichtung liegt ausschließlich bei der OCR-Engine.

#### Scenario: Auf dem Kopf stehende Seite

- **WHEN** eine um 180° gedrehte Seite verarbeitet wird
- **THEN** nimmt der Dienst keine eigene Drehung vor und überlässt die Orientierung der Engine

### Requirement: Alle Seiten laufen durch die Texterkennung

Der Dienst MUSS jede Seite jedes bildhaften Dokuments durch die Texterkennung geben, auch wenn
ein PDF bereits einen Textlayer mitbringt. Damit ist das Ergebnis unabhängig von der Herkunft
des Eingangsdokuments einheitlich.

#### Scenario: Bereits durchsuchbares PDF

- **WHEN** ein PDF mit vorhandenem Textlayer eingeht und nicht als E-Rechnung gilt
- **THEN** wird es dennoch vollständig durch die Texterkennung gegeben

### Requirement: Dokumente werden lokal geblockt und lokal wieder zusammengeführt

Der Dienst MUSS ein Dokument in Blöcke bis zum Online-Seitenlimit der eingesetzten Engine
zerlegen, die Blöcke einzeln verarbeiten und das Ergebnis zu **einem** Gesamt-PDF
zusammenführen. Die Zerlegung MUSS ohne Zwischenspeicherung bei einem Cloud-Speicher
auskommen.

#### Scenario: Dokument über dem Seitenlimit

- **WHEN** ein Dokument mehr Seiten hat als das Seitenlimit der Engine (Standard 15)
- **THEN** wird es in entsprechend viele Blöcke zerlegt, und es entsteht genau ein Ergebnis-PDF

#### Scenario: Seitenzahl bleibt erhalten

- **WHEN** ein Dokument mit N Seiten veredelt wird
- **THEN** hat das Ergebnis-PDF ebenfalls N Seiten in unveränderter Reihenfolge

### Requirement: Der Fortschritt wird während der Verarbeitung gemeldet

Der Dienst MUSS die Zahl der fertig verarbeiteten Seiten am Vorgang fortschreiben und je Block
einen Verlaufseintrag anlegen, damit der Stand eines langen Dokuments sichtbar ist, bevor es
fertig ist.

#### Scenario: Block abgeschlossen

- **WHEN** ein Block verarbeitet wurde
- **THEN** ist die Zahl der verarbeiteten Seiten am Vorgang aktualisiert und ein
  Verlaufseintrag vom Typ `ocr_chunk` benennt den Stand

### Requirement: Das Ergebnis ist ein durchsuchbares PDF mit unsichtbarem Textlayer

Der Dienst MUSS ein PDF erzeugen, das die aufbereitete Seite als sichtbare Ebene und den
erkannten Text als unsichtbare, an der Fundstelle positionierte Ebene enthält. Der Text MUSS
markierbar und durchsuchbar sein, ohne das Seitenbild zu überdecken.

#### Scenario: Ergebnis wird in einem PDF-Betrachter geöffnet

- **WHEN** ein veredeltes Dokument geöffnet wird
- **THEN** ist das Seitenbild unverändert sichtbar, und eine Volltextsuche findet den erkannten
  Text an der richtigen Seite

#### Scenario: Text wird markiert

- **WHEN** Text im Ergebnis-PDF markiert und kopiert wird
- **THEN** entspricht der kopierte Text dem erkannten Text an dieser Stelle

### Requirement: Die eingesetzte Engine wird am Vorgang festgehalten

Der Dienst MUSS festhalten, welche OCR-Engine ein Dokument verarbeitet hat, damit ein
Ergebnis später einer Engine zugeordnet werden kann.

#### Scenario: Dokument veredelt

- **WHEN** ein Dokument die Texterkennung durchlaufen hat
- **THEN** ist der Name der verwendeten Engine am Vorgang gespeichert

### Requirement: Der Seitendurchsatz gegen die Engine ist begrenzt

Der Dienst MUSS den Durchsatz gegen die Engine auf `DOCAI_MAX_PAGES_PER_MINUTE` begrenzen
(Standard 120). Die Begrenzung MUSS **Seiten** zählen, nicht Anfragen. Ein Wert kleiner oder
gleich 0 schaltet die Begrenzung ab.

#### Scenario: Durchsatzgrenze erreicht

- **WHEN** die konfigurierte Seitenrate erreicht ist
- **THEN** wartet der Dienst vor dem nächsten Block, statt die Grenze zu überschreiten

#### Scenario: Begrenzung abgeschaltet

- **WHEN** `DOCAI_MAX_PAGES_PER_MINUTE` auf 0 oder kleiner steht
- **THEN** findet keine Wartezeit statt

### Requirement: Die Engine ist austauschbar

Der Dienst MUSS die OCR-Engine hinter einer einheitlichen Schnittstelle kapseln. Jede Engine
kennt ihr eigenes Seitenlimit und blockt selbst; Bildaufbereitung und der Bau des
durchsuchbaren PDFs MÜSSEN engine-unabhängig bleiben. Die Auswahl erfolgt über
`OCR_PROVIDER`.

#### Scenario: Andere Engine konfiguriert

- **WHEN** eine andere Engine über `OCR_PROVIDER` ausgewählt wird
- **THEN** bleiben Bildaufbereitung, Fortschrittsmeldung und der Bau des Ergebnis-PDFs
  unverändert, und das jeweilige Seitenlimit der neuen Engine gilt

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
