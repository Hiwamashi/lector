# Spec Delta

## Purpose

Regelt, wie Paperless-Rechnungen nach SevDesk gelangen: die Übersicht als Hauptweg, der
Paperless-Tag als Abkürzung, die Prüfungen vor jedem Export und der Rückschrieb an Paperless.
Ziel ist, dass nur Rechnungen des Kontexts IT-Consulting und keine Dubletten exportiert werden.

## ADDED Requirements

### Requirement: Die Übersicht zeigt jede Rechnung mit Kontext, Export und Abgleich

Die Export-Übersicht MUSS alle Paperless-Dokumente des Rechnungs-Dokumenttyps sowie alle mit
dem SevDesk-Tag versehenen Dokumente zeigen. Jede Zeile MUSS enthalten: Datum, Korrespondent,
Betrag (falls bekannt), Kontext-Einstufung mit Konfidenz und Quelle, Exportstatus und das
Ergebnis des SevDesk-Abgleichs. Die Übersicht MUSS filterbar sein nach „IT-Consulting ab
Schwelle“, „nicht exportiert“, „mögliche Dublette“ und „zu prüfen“; die Filter MÜSSEN
kombinierbar sein.

#### Scenario: Geschäftliche Rechnungen finden, die noch fehlen

- **WHEN** der Nutzer die Filter „IT-Consulting“ und „nicht exportiert“ wählt
- **THEN** zeigt die Übersicht nur Rechnungen über der Schwelle, die weder exportiert noch in
  SevDesk gefunden wurden

#### Scenario: Private Rechnung

- **WHEN** eine Rechnung den Empfänger `Familie` trägt
- **THEN** zeigt ihre Zeile den Kontext „nicht IT-Consulting (Empfänger)“

### Requirement: Vor dem Export werden Kontext und Dubletten geprüft

Vor jedem Export MUSS Lector prüfen:

- Ist ein sicherer oder bestätigter Treffer vorhanden, DARF Lector NICHT exportieren; die
  Rechnung gilt als in SevDesk vorhanden. Das gilt auch, wenn eine vermerkte Beleg-ID im Abzug
  fehlt, weil die Rechnung dann bereits einmal exportiert wurde.
- Ist eine nicht entschiedene mögliche Dublette vorhanden, ist das ein Rückfragegrund.
- Ist am Dokument ein anderer Empfänger als IT-Consulting gesetzt, ist das ein Rückfragegrund.

Ein Export aus der Übersicht mit Rückfragegrund MUSS die Gründe nennen und erst nach
ausdrücklicher Bestätigung erfolgen.

#### Scenario: Bereits in SevDesk

- **WHEN** der Nutzer eine Rechnung mit sicherem Treffer exportieren will
- **THEN** bietet die Übersicht keinen Export an und nennt den vorhandenen Beleg

#### Scenario: Abweichender Empfänger

- **WHEN** der Nutzer eine Rechnung mit Empfänger `Familie` exportiert
- **THEN** fragt die Übersicht „Als Familie markiert — trotzdem exportieren und auf
  IT-Consulting umstellen?“ und exportiert erst nach Bestätigung

#### Scenario: Mögliche Dublette

- **WHEN** der Nutzer eine Rechnung mit offener möglicher Dublette exportiert
- **THEN** nennt die Rückfrage den ähnlichen Beleg mit Score und exportiert erst nach
  Bestätigung

#### Scenario: Ohne Rückfragegrund

- **WHEN** der Nutzer eine Rechnung ohne Empfänger und ohne Treffer exportiert
- **THEN** exportiert Lector ohne Rückfrage

### Requirement: Mehrere Rechnungen lassen sich gemeinsam exportieren

Die Übersicht MUSS eine Mehrfachauswahl mit gemeinsamem Export anbieten. Rechnungen ohne
Rückfragegrund MÜSSEN exportiert werden; Rechnungen mit sicherem Treffer oder Rückfragegrund
MÜSSEN übersprungen und im Ergebnis mit Grund genannt werden.

#### Scenario: Gemischte Auswahl

- **WHEN** der Nutzer fünf Rechnungen auswählt, von denen eine eine mögliche Dublette hat
- **THEN** exportiert Lector vier und meldet die fünfte als übersprungen mit dem Grund
  „mögliche Dublette“

### Requirement: Der Export setzt den Empfänger auf IT-Consulting

Nach einem erfolgreichen Export MUSS Lector am Paperless-Dokument das Feld „Empfänger“ auf die
Kontext-Option setzen, zusätzlich zu Beleg-ID, Exportdatum, Tag und Notiz. Scheitert dieser
Rückschrieb, MUSS der Exportstatus erhalten bleiben, der Fehler an der Rechnung sichtbar sein
und der Rückschrieb beim nächsten Sync erneut versucht werden. Beim Nachholen DARF Lector einen
inzwischen am Dokument gesetzten anderen Empfänger NICHT überschreiben; die übrigen Angaben
werden geschrieben und der Verzicht an der Rechnung vermerkt.

#### Scenario: Erfolgreicher Export

- **WHEN** eine Rechnung ohne Empfänger exportiert wird
- **THEN** trägt das Paperless-Dokument danach den Empfänger IT-Consulting und die Beleg-ID

#### Scenario: Rückschrieb scheitert

- **WHEN** der Beleg angelegt wurde, Paperless beim Setzen des Empfängers aber nicht erreichbar
  ist
- **THEN** bleibt die Rechnung „exportiert“, zeigt den offenen Rückschrieb und der nächste Sync
  holt ihn nach

#### Scenario: Empfänger zwischenzeitlich geändert

- **WHEN** der Rückschrieb scheiterte und der Nutzer vor dem Nachholen in Paperless den
  Empfänger `Sascha` gesetzt hat
- **THEN** bleibt `Sascha` stehen, Beleg-ID, Tag und Notiz werden geschrieben und die Rechnung
  vermerkt, dass der Empfänger nicht überschrieben wurde

### Requirement: Ein gesicherter Betrag wird als Belegsumme mitgegeben

Ist der Betrag einer Rechnung automatisch ermittelt oder manuell bestätigt und ist ein
Buchungskonto für die Belegposition konfiguriert, MUSS der Export den Betrag als Bruttosumme
des Belegs mitgeben. Ist der Betrag unbekannt, die Ermittlung gescheitert oder kein
Buchungskonto konfiguriert, MUSS der Beleg ohne Summe angelegt werden.

#### Scenario: Betrag bekannt

- **WHEN** ein Buchungskonto konfiguriert ist und eine Rechnung mit ermitteltem Betrag
  39,27 EUR exportiert wird
- **THEN** hat der SevDesk-Entwurf die Bruttosumme 39,27 EUR

#### Scenario: Kein Buchungskonto konfiguriert

- **WHEN** kein Buchungskonto konfiguriert ist und eine Rechnung mit ermitteltem Betrag
  exportiert wird
- **THEN** legt Lector den Beleg ohne Summe an

#### Scenario: Betrag unbekannt

- **WHEN** für eine Rechnung kein Betrag vorliegt
- **THEN** legt Lector den Beleg wie bisher ohne Summe an

### Requirement: Der Tag-Weg exportiert nur ohne Rückfragegrund

Ein Dokument mit SevDesk-Tag MUSS dieselben Prüfungen durchlaufen. Hat es einen sicheren oder
bestätigten Treffer, DARF Lector NICHT exportieren. Hat es einen Rückfragegrund, MUSS es den
Status „zu prüfen“ mit dem Grund erhalten und DARF NICHT exportiert werden, auch nicht bei
eingeschaltetem Auto-Export. Ohne Rückfragegrund gilt das bisherige Verhalten (vormerken bzw.
bei Auto-Export direkt exportieren). Ein Auto-Export DARF erst erfolgen, wenn mindestens ein
Abruf der SevDesk-Belege erfolgreich war; bis dahin bleibt die Rechnung vorgemerkt und wird
nach dem ersten erfolgreichen Abruf erneut geprüft. Eine Rechnung „zu prüfen“ MUSS sich aus der Übersicht mit
Rückfrage exportieren oder verwerfen lassen.

#### Scenario: Getaggte Rechnung mit Familien-Empfänger

- **WHEN** ein Dokument mit Empfänger `Familie` den SevDesk-Tag erhält und Auto-Export
  eingeschaltet ist
- **THEN** wird es nicht exportiert, sondern als „zu prüfen: anderer Empfänger“ geführt

#### Scenario: Getaggte Rechnung ohne Auffälligkeit

- **WHEN** ein Dokument ohne Empfänger und ohne Treffer den SevDesk-Tag erhält und Auto-Export
  eingeschaltet ist
- **THEN** exportiert Lector es und setzt den Empfänger auf IT-Consulting

#### Scenario: Auto-Export vor dem ersten Abgleich

- **WHEN** ein Dokument ohne Auffälligkeit den SevDesk-Tag erhält, Auto-Export eingeschaltet ist
  und noch kein Abruf der SevDesk-Belege gelungen ist
- **THEN** wird es nur vorgemerkt und erst nach dem ersten erfolgreichen Abruf geprüft und
  exportiert

#### Scenario: Prüffall verwerfen

- **WHEN** der Nutzer eine Rechnung „zu prüfen“ verwirft
- **THEN** wird sie nicht exportiert und erscheint nicht mehr im Filter „zu prüfen“

### Requirement: Ein Beleg wird nie doppelt angelegt

Gleichzeitige oder wiederholte Exporte derselben Rechnung DÜRFEN höchstens einen Beleg
erzeugen. Lehnt SevDesk das Anlegen eindeutig ab, MUSS die Rechnung erneut exportierbar sein.
Ist unklar, ob ein Beleg angelegt wurde (Serverfehler, Abbruch, fehlende Beleg-ID), MUSS die
Rechnung als „unklar“ gelten und DARF NICHT automatisch erneut exportiert werden; findet der
nächste Abgleich den Beleg, MUSS er ihn als ähnlichen Treffer zur Bestätigung anbieten. Bestätigt
der Nutzer ihn, MUSS die Rechnung als exportiert mit dieser Beleg-ID gelten.

#### Scenario: Doppelklick

- **WHEN** der Nutzer den Export zweimal kurz nacheinander auslöst
- **THEN** entsteht genau ein Beleg

#### Scenario: Unklarer Ausgang

- **WHEN** SevDesk beim Anlegen mit HTTP 500 antwortet
- **THEN** steht die Rechnung auf „unklar“ und wird nicht automatisch erneut exportiert
