# Spec Delta

## MODIFIED Requirements

### Requirement: Der Fortschritt wird während der Verarbeitung gemeldet

Der Dienst MUSS die Zahl der fertig verarbeiteten Seiten am Vorgang fortschreiben und je Block
einen Verlaufseintrag anlegen, damit der Stand eines langen Dokuments sichtbar ist, bevor es
fertig ist. Ein Block, der aus dem Zwischenspeicher stammt statt von der Engine, MUSS im
Verlauf als solcher erkennbar sein — andernfalls sähe ein Lauf, der ein langes Dokument in
Sekunden abschließt, wie eine Fehlfunktion aus.

#### Scenario: Block abgeschlossen

- **WHEN** ein Block verarbeitet wurde
- **THEN** ist die Zahl der verarbeiteten Seiten am Vorgang aktualisiert und ein
  Verlaufseintrag vom Typ `ocr_chunk` benennt den Stand

#### Scenario: Block stammt aus dem Zwischenspeicher

- **WHEN** ein Block nicht an die Engine gegeben, sondern aus dem Zwischenspeicher
  übernommen wurde
- **THEN** schreitet die Zahl der verarbeiteten Seiten genauso fort wie sonst, und der
  Verlaufseintrag weist die Wiederverwendung aus

### Requirement: Die Engine ist austauschbar

Der Dienst MUSS die OCR-Engine hinter einer einheitlichen Schnittstelle kapseln. Jede Engine
kennt ihr eigenes Seitenlimit und blockt selbst; Bildaufbereitung, der Bau des
durchsuchbaren PDFs und das Bewahren von Blockergebnissen MÜSSEN engine-unabhängig bleiben.
Die Auswahl erfolgt über `OCR_PROVIDER`.

#### Scenario: Andere Engine konfiguriert

- **WHEN** eine andere Engine über `OCR_PROVIDER` ausgewählt wird
- **THEN** bleiben Bildaufbereitung, Fortschrittsmeldung, der Bau des Ergebnis-PDFs und das
  Bewahren von Blockergebnissen unverändert, und das jeweilige Seitenlimit der neuen Engine
  gilt

#### Scenario: Ergebnisse einer Engine gelten nicht für eine andere

- **WHEN** die Engine oder der eingesetzte Prozessor gewechselt wird
- **THEN** werden zuvor bewahrte Blockergebnisse nicht wiederverwendet

## ADDED Requirements

### Requirement: Ein erfolgreich verarbeiteter Block wird sofort bewahrt

Der Dienst MUSS das Ergebnis jedes Blocks festhalten, sobald es vorliegt — vor dem Beginn des
nächsten Blocks. Das Bewahren MUSS einen Prozessabbruch überdauern; ein Zwischenspeicher
allein im Arbeitsspeicher genügt nicht, weil ein Wiederholversuch in einem anderen Prozess
stattfinden kann.

Scheitert das Bewahren selbst, DARF das den laufenden Vorgang nicht zum Scheitern bringen:
Ein nicht bewahrter Block kostet einen erneuten Aufruf, ein abgebrochener Lauf kostet alle.

#### Scenario: Fehler nach erfolgreichen Blöcken

- **WHEN** ein Dokument aus mehreren Blöcken besteht und die Verarbeitung an einem späteren
  Block scheitert
- **THEN** sind die Ergebnisse aller zuvor erfolgreich verarbeiteten Blöcke bewahrt

#### Scenario: Prozessabbruch mitten in der Verarbeitung

- **WHEN** der Dienst abbricht, nachdem einzelne Blöcke verarbeitet wurden
- **THEN** stehen deren Ergebnisse nach dem Neustart zur Verfügung

#### Scenario: Das Bewahren schlägt fehl

- **WHEN** ein Blockergebnis sich nicht festhalten lässt
- **THEN** läuft die Verarbeitung dennoch weiter, und der Fehlschlag wird protokolliert

### Requirement: Ein bewahrter Block wird wiederverwendet statt erneut erkannt

Der Dienst MUSS vor jedem Block prüfen, ob für genau diesen Block bereits ein Ergebnis
bewahrt ist, und es in diesem Fall verwenden. Er DARF die Engine dann nicht befragen — es
DÜRFEN keine erneuten Kosten für diesen Block entstehen.

Ein bewahrtes Ergebnis gilt nur für **denselben Inhalt unter denselben Bedingungen**. Die
Zuordnung MUSS die Prüfsumme des Originaldokuments, die Lage und Größe des Blocks sowie die
Einstellungen berücksichtigen, die das Erkennungsergebnis beeinflussen — mindestens die
Schalter der Bildaufbereitung, die Blockgröße sowie Engine und Prozessor. Ändert sich eine
dieser Bedingungen, DARF das frühere Ergebnis nicht mehr verwendet werden.

Das Ergebnis eines wiederverwendeten Blocks MUSS im fertigen Dokument an derselben Stelle
und in derselben Form erscheinen wie ein frisch erkannter Block.

#### Scenario: Wiederholversuch nach einem Teilfehler

- **WHEN** ein Dokument wiederholt wird, dessen erste Blöcke beim vorherigen Versuch
  erfolgreich waren
- **THEN** werden nur die noch fehlenden Blöcke an die Engine gegeben, und das Ergebnis-PDF
  ist dasselbe, als wäre alles frisch erkannt worden

#### Scenario: Vorverarbeitung wurde umgestellt

- **WHEN** zwischen zwei Versuchen ein Schalter der Bildaufbereitung geändert wurde
- **THEN** werden die zuvor bewahrten Blöcke nicht verwendet, sondern neu erkannt

#### Scenario: Blockgröße wurde geändert

- **WHEN** zwischen zwei Versuchen die Blockgröße geändert wurde, sodass andere Seiten in
  einem Block liegen
- **THEN** werden die zuvor bewahrten Blöcke nicht verwendet

#### Scenario: Anderes Dokument mit gleichem Namen

- **WHEN** ein Dokument mit demselben Dateinamen, aber anderem Inhalt verarbeitet wird
- **THEN** werden die bewahrten Blöcke des früheren Dokuments nicht verwendet

### Requirement: Ein wiederverwendeter Block löst keine Drosselung aus

Der Dienst DARF die Wartezeit des seitenbasierten Rate-Limits nicht auf Blöcke anwenden, die
aus dem Zwischenspeicher stammen. Das Limit schützt die Quota der Engine; ohne Anfrage an die
Engine gibt es nichts zu drosseln.

#### Scenario: Lauf ausschließlich aus dem Zwischenspeicher

- **WHEN** ein Wiederholversuch alle Blöcke aus dem Zwischenspeicher bedienen kann
- **THEN** findet keine Wartezeit für die Drosselung statt

#### Scenario: Gemischter Lauf

- **WHEN** ein Teil der Blöcke wiederverwendet und der Rest an die Engine gegeben wird
- **THEN** zählt für die Drosselung ausschließlich die Zahl der tatsächlich an die Engine
  gegebenen Seiten
