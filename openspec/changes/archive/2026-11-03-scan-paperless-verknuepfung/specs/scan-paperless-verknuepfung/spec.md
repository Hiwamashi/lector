# Spec Delta

## Purpose

Verbindet jeden Lector-Vorgang mit dem Paperless-Dokument, das aus ihm entstanden ist, damit
die Kontrolle nach dem Scannen in Lector stattfindet: Ankunft in Paperless sehen, das Ergebnis
ansehen und bei Fehlern das Original prüfen, ohne Paperless oder das NAS zu öffnen.

## ADDED Requirements

### Requirement: Lector merkt sich die Prüfsumme der abgelegten Datei

Legt der Dienst ein Ergebnis im Ausgabeordner ab, MUSS er die SHA-256-Prüfsumme genau der
abgelegten Datei beim Vorgang speichern. Bei einer E-Rechnung ist das die Prüfsumme des
unverändert kopierten Originals, beim OCR-Weg die des erzeugten durchsuchbaren PDFs.

#### Scenario: OCR-Dokument

- **WHEN** ein Scan erfolgreich verarbeitet und als PDF im Ausgabeordner abgelegt wird
- **THEN** trägt der Vorgang die SHA-256-Prüfsumme dieses PDFs, nicht die des Scans

#### Scenario: E-Rechnung

- **WHEN** eine E-Rechnung unverändert in den Ausgabeordner kopiert wird
- **THEN** stimmt die gespeicherte Prüfsumme mit der Prüfsumme des Originals überein

### Requirement: Lector verknüpft einen Vorgang über die Prüfsumme mit Paperless

Ist eine Paperless-Anbindung konfiguriert (Adresse und Zugangsschlüssel), MUSS der Dienst für
jeden Vorgang mit gespeicherter Ausgabe-Prüfsumme und ohne Verknüpfung regelmäßig, höchstens
alle 5 Minuten, in Paperless nach einem Dokument mit genau dieser Prüfsumme suchen. Findet er
eines, MUSS er dessen ID beim Vorgang speichern und den Zustand „verknüpft“ setzen. Hat
Paperless die Datei als Dublette abgelehnt, MUSS die Verknüpfung auf das bereits vorhandene
Dokument mit dieser Prüfsumme zeigen. Ist Paperless nicht erreichbar, MUSS der Zustand
unverändert bleiben und die Suche später erneut erfolgen.

#### Scenario: Dokument kommt in Paperless an

- **WHEN** Paperless ein von Lector abgelegtes PDF aufgenommen hat
- **THEN** zeigt der Vorgang spätestens nach dem nächsten Suchlauf die ID des
  Paperless-Dokuments und den Zustand „verknüpft“

#### Scenario: Dublette

- **WHEN** Paperless eine von Lector abgelegte Datei ablehnt, weil ein Dokument mit derselben
  Prüfsumme schon existiert
- **THEN** ist der Vorgang mit diesem vorhandenen Dokument verknüpft

#### Scenario: Paperless nicht erreichbar

- **WHEN** Paperless beim Suchlauf nicht antwortet
- **THEN** bleibt der Vorgang im Zustand „wartet“ und der nächste Suchlauf versucht es erneut

#### Scenario: Keine Paperless-Anbindung

- **WHEN** keine Paperless-Adresse oder kein Zugangsschlüssel konfiguriert ist
- **THEN** findet keine Suche statt und die Dokumente-Liste zeigt keine Paperless-Angaben

### Requirement: Ein nicht auffindbares Dokument wird nach 24 Stunden als solches markiert

Findet der Dienst ein Dokument 24 Stunden nach dem Ablegen nicht, MUSS er den Vorgang als
„nicht gefunden“ markieren und ihn nicht weiter in jedem Lauf suchen. Der Verarbeitungszustand
des Vorgangs DARF sich dadurch NICHT ändern. Ein späterer Treffer in einem Nachholdurchlauf
MUSS die Markierung wieder aufheben.

#### Scenario: Paperless hat die Datei nie aufgenommen

- **WHEN** ein Vorgang seit mehr als 24 Stunden abgelegt ist und Paperless kein Dokument mit
  seiner Prüfsumme kennt
- **THEN** zeigt die Dokumente-Liste „nicht gefunden“ und der Vorgang bleibt „fertig“

### Requirement: Ein in Paperless gelöschtes Dokument wird erkannt

Meldet Paperless für die ID eines verknüpften Vorgangs „nicht gefunden“, MUSS der Dienst den
Zustand „in Paperless nicht mehr vorhanden“ setzen und die bisherige ID behalten.

#### Scenario: Dokument gelöscht

- **WHEN** das verknüpfte Dokument in Paperless gelöscht wurde und der Nutzer den Vorgang öffnet
- **THEN** zeigt die Ansicht „in Paperless nicht mehr vorhanden (#1234)“ statt eines Fehlers

### Requirement: Der Altbestand wird nachgeholt

Der Dienst MUSS beim Start und danach mit dem regulären Suchlauf Vorgänge ohne Verknüpfung
nachholen, die vor diesem Change abgeschlossen wurden:

- E-Rechnungen über die gespeicherte Prüfsumme des Originals, mit Zustand „verknüpft“.
- OCR-Vorgänge ohne gespeicherte Ausgabe-Prüfsumme über den Dateinamen der abgelegten Datei:
  Paperless-Dokumente mit genau diesem ursprünglichen Dateinamen, die innerhalb von 24 Stunden
  nach dem Ablegen hinzugefügt wurden. Nur bei genau einem Treffer MUSS der Dienst verknüpfen,
  mit dem Zustand „verknüpft über Dateinamen“; sonst „nicht gefunden“.

Fehlgeschlagene Vorgänge DÜRFEN NICHT gesucht werden.

#### Scenario: Alte E-Rechnung

- **WHEN** eine vor dem Change durchgereichte E-Rechnung noch keine Verknüpfung hat
- **THEN** ist sie nach dem Nachholen über ihre Prüfsumme verknüpft

#### Scenario: Alter Scan mit eindeutigem Namen

- **WHEN** ein alter OCR-Vorgang als `rechnung.pdf` abgelegt wurde und Paperless genau ein
  Dokument mit diesem ursprünglichen Dateinamen hat, das am selben Tag hinzugefügt wurde
- **THEN** ist der Vorgang „verknüpft über Dateinamen“ mit diesem Dokument

#### Scenario: Mehrdeutiger Name

- **WHEN** zwei Paperless-Dokumente im Zeitfenster denselben ursprünglichen Dateinamen tragen
- **THEN** verknüpft der Dienst nicht und markiert den Vorgang als „nicht gefunden“

### Requirement: Die Dokumente-Liste zeigt den Paperless-Bezug

Bei konfigurierter Paperless-Anbindung MUSS die Dokumente-Liste je Vorgang den Bezug zu
Paperless zeigen: die Dokument-ID, „wartet“, „nicht gefunden“, „nicht mehr vorhanden“ oder
„—“ für Vorgänge ohne Ergebnis. Eine Verknüpfung über den Dateinamen MUSS als solche erkennbar
sein. Ein Schnellfilter „Nicht in Paperless“ MUSS die Liste auf abgeschlossene Vorgänge
beschränken, die nicht verknüpft sind.

#### Scenario: Filter

- **WHEN** der Nutzer den Schnellfilter „Nicht in Paperless“ wählt
- **THEN** zeigt die Liste nur abgeschlossene Vorgänge in den Zuständen „wartet“, „nicht
  gefunden“ und „nicht mehr vorhanden“

### Requirement: Seitenleiste und Detail zeigen Vorgang und Dokument zusammen

Die Detailansicht eines Vorgangs, als Seite und als Seitenleiste, MUSS oben Name, Status und
Paperless-Bezug des Vorgangs zeigen und den vollständigen Verlauf eingeklappt anbieten.
Darunter MUSS sie bei einem verknüpften Vorgang die Paperless-Dokumentansicht mit allen ihren
Angaben und Lector-Aktionen zeigen. Ohne Verknüpfung MUSS sie stattdessen die Vorschau des
lokalen Originals zeigen, sofern es noch vorhanden ist. Bei einem fehlgeschlagenen oder
laufenden Vorgang MUSS der Verlauf ausgeklappt sein.

#### Scenario: Verknüpfter Scan

- **WHEN** der Nutzer in der Dokumente-Liste einen verknüpften Vorgang öffnet
- **THEN** zeigt die Leiste oben Dateiname, Status und „in Paperless #1234“, darunter Vorschau
  und Angaben des Paperless-Dokuments, der Verlauf ist eingeklappt

#### Scenario: Fehlgeschlagener Scan

- **WHEN** der Nutzer einen fehlgeschlagenen Vorgang öffnet, dessen Original im Fehlerordner liegt
- **THEN** zeigt die Leiste den ausgeklappten Verlauf mit Fehlermeldung und darunter die
  Vorschau des Originals

### Requirement: Lector liefert das lokale Original sicher aus

Der Dienst MUSS das Original eines Vorgangs ausliefern können, solange die Datei im Ordner der
verarbeiteten Dateien oder im Fehlerordner liegt. Ausgeliefert werden DARF nur die Datei, die
dem Vorgang zugeordnet ist, und nur, wenn sie innerhalb eines dieser beiden Ordner liegt. PDF
und Bilder MÜSSEN mit denselben Schutzangaben wie die Paperless-Vorschau angezeigt werden
(Einbetten nur in Lectors eigene Seiten, keine Skripte). Für andere Formate, insbesondere
XML-E-Rechnungen, MUSS die Ansicht einen Hinweis und einen Download anbieten. Ist die Datei
nicht mehr vorhanden, MUSS die Ansicht das als Hinweis zeigen.

#### Scenario: Original im Fehlerordner

- **WHEN** ein Vorgang fehlgeschlagen ist und sein Original im Fehlerordner liegt
- **THEN** zeigt die Ansicht das Original als Vorschau

#### Scenario: Aufbewahrung abgelaufen

- **WHEN** das Original eines erfolgreichen Vorgangs nach Ablauf der Aufbewahrung gelöscht wurde
- **THEN** zeigt die Ansicht „Original nicht mehr vorhanden“ und keinen Fehler

#### Scenario: XML-E-Rechnung

- **WHEN** der Vorgang eine XML-E-Rechnung ist und nicht verknüpft ist
- **THEN** bietet die Ansicht „XML-E-Rechnung herunterladen“ statt einer Vorschau

#### Scenario: Pfad außerhalb der Ordner

- **WHEN** der zugeordnete Pfad eines Vorgangs nicht im Ordner der verarbeiteten Dateien oder im
  Fehlerordner liegt
- **THEN** liefert der Dienst die Datei nicht aus
