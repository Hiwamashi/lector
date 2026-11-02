# Spec Delta

## Purpose

Macht Paperless-Dokumente in Lector sichtbar, damit der Alltag in Lector stattfindet und
Paperless nur noch für Pflege und Sonderfälle geöffnet werden muss: lesende Ansicht mit
Vorschau und Metadaten, als eigene Seite und als Seitenleiste neben jeder Liste.

## ADDED Requirements

### Requirement: Lector zeigt ein Paperless-Dokument mit Vorschau und Metadaten

Ist eine Paperless-Anbindung konfiguriert (Adresse und Zugangsschlüssel), MUSS Lector zu jedem
Paperless-Dokument, das Lectors Zugang zu Paperless lesen darf, eine Ansicht unter einer
stabilen Adresse mit der Paperless-Dokument-ID anbieten. Die Ansicht MUSS zeigen: Titel,
Korrespondent, Dokumenttyp, Ausstellungsdatum, Hinzufügedatum, Tags, Archivnummer (ASN),
alle Custom Fields mit Namen und Wert sowie die Notizen mit Verfasser und Zeitpunkt.
Korrespondent, Dokumenttyp, Tags und Feldnamen MÜSSEN mit ihrem Namen erscheinen, nicht mit
ihrer ID. Fehlende Angaben MÜSSEN als leer erkennbar sein, statt ausgelassen zu werden.

#### Scenario: Dokument mit allen Angaben

- **WHEN** der Nutzer die Ansicht des Dokuments 1234 öffnet, das Korrespondent „Telekom“,
  zwei Tags, das Feld „SevDesk-Beleg“ und eine Notiz hat
- **THEN** zeigt die Ansicht diese Angaben mit Namen, die Notiz mit Verfasser und Zeitpunkt
  und daneben die Vorschau des Dokuments

#### Scenario: Dokument ohne Korrespondent

- **WHEN** das Dokument keinen Korrespondenten hat
- **THEN** zeigt die Ansicht beim Korrespondenten „—“

#### Scenario: Unbekannte ID

- **WHEN** der Nutzer eine Dokument-ID öffnet, die Paperless nicht kennt oder für Lectors
  Zugang nicht freigibt
- **THEN** antwortet Lector mit „nicht gefunden“ und einem verständlichen Hinweis

#### Scenario: Keine Paperless-Anbindung

- **WHEN** keine Paperless-Adresse oder kein Zugangsschlüssel konfiguriert ist
- **THEN** ist die Ansicht nicht erreichbar und keine Liste bietet sie an

### Requirement: Die Ansicht ist lesend bis auf Lectors eigene Angaben

Die Ansicht DARF Titel, Korrespondent, Dokumenttyp, Tags, Archivnummer, Notizen und Custom
Fields NICHT bearbeitbar anbieten, mit Ausnahme der Angaben, die Lector bereits vor diesem
Change bearbeiten konnte: Empfänger, Rechnungsdaten (Betrag, IBAN, Verwendungszweck,
„überwiesen“) und SevDesk-Export. Diese Angaben MÜSSEN in der Ansicht mit denselben Regeln
und Rückfragen bearbeitbar sein wie bisher. Rechnungsangaben MÜSSEN nur bei Dokumenten
erscheinen, die Lector als Rechnung führt.

#### Scenario: Empfänger aus der Ansicht setzen

- **WHEN** der Nutzer in der Ansicht eines Dokuments den Empfänger auf „Familie“ setzt
- **THEN** trägt das Paperless-Dokument danach diesen Empfänger und die Ansicht zeigt ihn

#### Scenario: Tags sind nur sichtbar

- **WHEN** der Nutzer die Tags eines Dokuments in der Ansicht betrachtet
- **THEN** gibt es dort kein Bedienelement, das Tags ändert

#### Scenario: Kein Rechnungsbereich bei Nicht-Rechnungen

- **WHEN** der Nutzer ein Dokument öffnet, das Lector nicht als Rechnung führt
- **THEN** zeigt die Ansicht keinen Rechnungsbereich, wohl aber den Empfänger

### Requirement: Jede Ansicht bietet den Absprung nach Paperless

Die Ansicht MUSS einen Link anbieten, der dasselbe Dokument in Paperless öffnet. Der Link
MUSS die öffentliche Paperless-Adresse verwenden, sofern eine konfiguriert ist, sonst die
interne Adresse, und MUSS in einem neuen Tab öffnen.

#### Scenario: Öffentliche Adresse konfiguriert

- **WHEN** eine öffentliche Paperless-Adresse konfiguriert ist und der Nutzer „In Paperless
  öffnen“ wählt
- **THEN** öffnet sich in einem neuen Tab die Detailseite des Dokuments unter dieser Adresse

### Requirement: Lector liefert die Vorschau jedes Paperless-Dokuments aus

Lector MUSS die Vorschau eines Paperless-Dokuments selbst ausliefern, sodass der Browser
keine direkte Verbindung zu Paperless braucht. Ausgeliefert werden DÜRFEN nur PDF und
Bildformate; andere Inhalte MÜSSEN abgelehnt werden. Die Auslieferung MUSS das Einbetten nur
in Lectors eigene Seiten erlauben und in der Vorschau keine Skripte ausführen lassen. Ist
keine Vorschau verfügbar oder Paperless nicht erreichbar, MUSS die Ansicht das als Hinweis
zeigen und die Metadaten trotzdem anzeigen, soweit sie abrufbar sind.

#### Scenario: PDF-Vorschau

- **WHEN** die Ansicht eines PDF-Dokuments geöffnet wird
- **THEN** zeigt sie das PDF eingebettet, geliefert von Lector

#### Scenario: Nicht unterstütztes Format

- **WHEN** Paperless für die Vorschau einen Inhalt liefert, der weder PDF noch Bild ist
- **THEN** liefert Lector ihn nicht aus und die Ansicht zeigt „Keine Vorschau verfügbar“
  samt Absprung nach Paperless

#### Scenario: Paperless nicht erreichbar

- **WHEN** Paperless beim Öffnen der Ansicht nicht antwortet
- **THEN** zeigt die Ansicht einen Hinweis, dass Paperless nicht erreichbar ist, und die
  Liste daneben bleibt bedienbar

### Requirement: Die Ansicht öffnet sich aus jeder Liste als Seitenleiste

Die Listen Rechnungen, Empfänger und Dokumente MÜSSEN die Ansicht eines Eintrags als
Seitenleiste neben der Liste öffnen, ohne die Seite zu wechseln. Das geöffnete Dokument
MUSS in der Adresse der Seite stehen, sodass Neuladen, Zurück-Taste und ein geteilter Link
denselben Zustand wiederherstellen. Filter, Sortierung und Scrollposition der Liste MÜSSEN
beim Öffnen, Wechseln und Schließen erhalten bleiben. Die geöffnete Zeile MUSS in der Liste
markiert sein. Ohne ausgeführtes JavaScript MUSS ein Klick auf den Eintrag die Ansicht als
eigene Seite öffnen.

#### Scenario: Aus der Rechnungsliste öffnen

- **WHEN** der Nutzer in der gefilterten Rechnungsliste einen Titel anklickt
- **THEN** öffnet sich die Ansicht als Seitenleiste, die Liste bleibt mit Filter sichtbar und
  die Adresse enthält das geöffnete Dokument

#### Scenario: Neu laden

- **WHEN** der Nutzer die Seite mit geöffneter Seitenleiste neu lädt
- **THEN** ist dieselbe Liste mit demselben Filter und derselben geöffneten Seitenleiste zu
  sehen

#### Scenario: Zurück-Taste

- **WHEN** der Nutzer nacheinander zwei Dokumente öffnet und dann zurück navigiert
- **THEN** zeigt die Seitenleiste wieder das erste Dokument

#### Scenario: Ohne JavaScript

- **WHEN** JavaScript nicht ausgeführt wird und der Nutzer einen Eintrag anklickt
- **THEN** öffnet sich die Ansicht als eigene Seite

### Requirement: Die Seitenleiste ist per Tastatur bedienbar

Bei geöffneter Seitenleiste MÜSSEN Pfeil hoch und Pfeil runter sowie `k` und `j` zum
vorherigen bzw. nächsten Eintrag der Liste wechseln, `Esc` MUSS die Seitenleiste schließen
und `Enter` MUSS die Ansicht als eigene Seite öffnen. Diese Tasten DÜRFEN NICHT greifen,
während ein Eingabefeld, eine Auswahlliste oder die eingebettete Vorschau den Fokus hat.
Beim Schließen MUSS der Fokus auf die zuletzt geöffnete Zeile zurückkehren.

#### Scenario: Nächstes Dokument

- **WHEN** die Seitenleiste das dritte Dokument der Liste zeigt und der Nutzer `j` drückt
- **THEN** zeigt sie das vierte Dokument und die Markierung in der Liste wandert mit

#### Scenario: Tippen im Eingabefeld

- **WHEN** der Nutzer im Betragsfeld der Seitenleiste `j` tippt
- **THEN** erscheint das Zeichen im Feld und das Dokument wechselt nicht

#### Scenario: Schließen

- **WHEN** der Nutzer `Esc` drückt
- **THEN** schließt sich die Seitenleiste, die Adresse enthält kein Dokument mehr und der
  Fokus liegt auf der zuletzt geöffneten Zeile

### Requirement: Die Seitenleiste passt sich der Fensterbreite an

Auf breiten Fenstern MUSS die Seitenleiste neben der Liste stehen und die Liste MUSS
schmaler werden; Spalten, deren Inhalt die Seitenleiste ebenfalls zeigt, DÜRFEN dabei
ausgeblendet werden, Titel und Datum MÜSSEN sichtbar bleiben. Auf mittleren Fenstern MUSS
die Seitenleiste über der Liste liegen. Auf Handybreite MUSS sie den ganzen Bildschirm
einnehmen und einen sichtbaren Schließen-Knopf haben. In keinem Fall DARF die Seite
waagerecht scrollen.

#### Scenario: Breites Fenster

- **WHEN** die Rechnungsliste in einem 1800 px breiten Fenster mit geöffneter Seitenleiste
  angezeigt wird
- **THEN** stehen Liste und Seitenleiste nebeneinander, die Liste zeigt mindestens Titel und
  Datum und die Seite scrollt nicht waagerecht

#### Scenario: Handy

- **WHEN** die Seitenleiste auf einem 390 px breiten Bildschirm geöffnet wird
- **THEN** füllt sie den Bildschirm und lässt sich über einen Knopf schließen

### Requirement: Aktionen in der Seitenleiste wirken ohne Neuladen

Ändert der Nutzer in der Seitenleiste eine Lector-Angabe, MUSS die Seitenleiste danach den
neuen Stand zeigen, ohne dass die ganze Seite neu lädt, und die zugehörige Zeile der Liste
MUSS den neuen Stand ebenfalls zeigen. Schlägt die Aktion fehl, MUSS die Seitenleiste den
Fehler zeigen und die bisherigen Werte behalten.

#### Scenario: Überwiesen markieren

- **WHEN** der Nutzer in der Seitenleiste eine Rechnung als überwiesen markiert
- **THEN** zeigt die Seitenleiste „überwiesen“ und die Zeile in der Rechnungsliste ebenfalls,
  ohne dass die Seite neu lädt

#### Scenario: Paperless lehnt ab

- **WHEN** Paperless das Setzen des Empfängers ablehnt
- **THEN** zeigt die Seitenleiste den Fehler und den bisherigen Empfänger

### Requirement: Bisherige Rechnungsadressen bleiben gültig

Die bisherige Adresse der Rechnungsdetailseite MUSS weiter funktionieren und zur Ansicht des
zugehörigen Paperless-Dokuments mit Rechnungsbereich führen.

#### Scenario: Alter Link

- **WHEN** der Nutzer einen gespeicherten Link auf die Detailseite einer Rechnung öffnet
- **THEN** landet er in der Ansicht des zugehörigen Paperless-Dokuments mit Rechnungsbereich
