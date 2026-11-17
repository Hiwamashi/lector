# Spec Delta

## MODIFIED Requirements

### Requirement: Jede Seite wird vor der Texterkennung aufbereitet

Der Dienst MUSS jede Seite vor der Texterkennung aufbereiten. Die Aufbereitung umfasst eine
Schieflagenkorrektur und eine Kontrast-/Graustufenanpassung. Beide Schritte MÜSSEN einzeln
über `PREPROCESS_DESKEW` bzw. `PREPROCESS_CONTRAST` abschaltbar sein; beide sind standardmäßig
aktiv.

Die Kontrast-/Graustufenanpassung MUSS ausschließlich auf das Bild wirken, das an die
Texterkennung geht. Die Schieflagenkorrektur MUSS genau einmal je Seite ermittelt und
identisch auf das Bild für die Texterkennung und auf die sichtbare Ebene angewendet werden.

#### Scenario: Schieflagenkorrektur abgeschaltet

- **WHEN** `PREPROCESS_DESKEW` auf falsch steht
- **THEN** wird die Seite ohne Schieflagenkorrektur an die Texterkennung gegeben

#### Scenario: Seite ohne erkennbaren Text

- **WHEN** eine Seite zu wenige Textpixel für eine Winkelschätzung enthält
- **THEN** wird sie unverändert weitergereicht statt willkürlich gedreht

#### Scenario: Kontrastanpassung aktiv

- **WHEN** `PREPROCESS_CONTRAST` aktiv ist und eine farbige Seite verarbeitet wird
- **THEN** erhält die Texterkennung die Seite in Graustufen mit angehobenem Kontrast, und die
  sichtbare Ebene behält die Farben des Originals

#### Scenario: Schieflage auf beiden Bildern gleich

- **WHEN** eine schief eingescannte Seite verarbeitet wird
- **THEN** sind das Bild für die Texterkennung und die sichtbare Ebene um denselben Winkel
  gedreht und haben dieselben Abmessungen

### Requirement: Das Ergebnis ist ein durchsuchbares PDF mit unsichtbarem Textlayer

Der Dienst MUSS ein PDF erzeugen, das die Seite als sichtbare Ebene und den erkannten Text
als unsichtbare, an der Fundstelle positionierte Ebene enthält. Der Text MUSS markierbar und
durchsuchbar sein, ohne das Seitenbild zu überdecken.

Die sichtbare Ebene MUSS die Farben des Eingangsdokuments behalten. An ihr DARF außer der
Schieflagenkorrektur keine Bildaufbereitung vorgenommen werden.

#### Scenario: Ergebnis wird in einem PDF-Betrachter geöffnet

- **WHEN** ein veredeltes Dokument geöffnet wird
- **THEN** ist das Seitenbild unverändert sichtbar, und eine Volltextsuche findet den erkannten
  Text an der richtigen Seite

#### Scenario: Text wird markiert

- **WHEN** Text im Ergebnis-PDF markiert und kopiert wird
- **THEN** entspricht der kopierte Text dem erkannten Text an dieser Stelle

#### Scenario: Farbiges Eingangsdokument

- **WHEN** ein Dokument mit farbigen Inhalten (z. B. Stempel, Logo, Unterschrift in Blau)
  veredelt wird
- **THEN** zeigt das Ergebnis-PDF diese Inhalte in ihren ursprünglichen Farben

#### Scenario: Eingangsdokument in Graustufen

- **WHEN** ein Dokument veredelt wird, das bereits in Graustufen oder Schwarz-Weiß vorliegt
- **THEN** erscheint es im Ergebnis-PDF ebenso, ohne hinzugefügte Farbe

#### Scenario: Kontrastanpassung abgeschaltet

- **WHEN** `PREPROCESS_CONTRAST` auf falsch steht
- **THEN** sieht die sichtbare Ebene genauso aus wie bei aktiver Kontrastanpassung
