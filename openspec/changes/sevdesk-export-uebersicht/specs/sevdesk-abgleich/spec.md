# Spec Delta

## Purpose

Macht die in SevDesk vorhandenen Belege für Lector sichtbar und ordnet sie Paperless-Rechnungen
zu, damit vor einem Export erkennbar ist, ob ein Beleg schon existiert. Die Zuordnung ist so
gehalten, dass später auch Belege ohne Paperless-Dokument auswertbar sind.

## ADDED Requirements

### Requirement: Lector hält einen Abzug der SevDesk-Belege vor

Ist der SevDesk-Export eingeschaltet, MUSS Lector die Belege aus SevDesk periodisch und auf
Anforderung aus der Übersicht abrufen und lokal vorhalten: Beleg-ID, Belegdatum, Lieferant,
Bruttosumme, Währung, Beschreibung und Status. Ein Beleg, der bei einem vollständigen Abruf
nicht mehr geliefert wird, MUSS aus dem Abzug entfernt werden. Der Zeitpunkt des letzten
erfolgreichen Abrufs MUSS in der Übersicht sichtbar sein.

#### Scenario: Periodischer Abruf

- **WHEN** das Abruf-Intervall abläuft
- **THEN** liest Lector alle Belege neu und aktualisiert den Abzug samt Zeitpunkt

#### Scenario: Abruf auf Anforderung

- **WHEN** der Nutzer in der Übersicht „Abgleich aktualisieren“ wählt
- **THEN** ruft Lector die Belege sofort ab und die Übersicht zeigt den neuen Stand

#### Scenario: Beleg in SevDesk gelöscht

- **WHEN** ein Beleg seit dem letzten Abruf in SevDesk gelöscht wurde
- **THEN** ist er nach dem nächsten vollständigen Abruf nicht mehr im Abzug

### Requirement: Ein gescheiterter Abruf behauptet keinen fehlenden Treffer

Scheitert der Abruf, MUSS Lector den letzten erfolgreichen Abzug behalten und die Übersicht
den Fehler samt Zeitpunkt des letzten erfolgreichen Abrufs zeigen. Gibt es noch keinen
erfolgreichen Abruf, MUSS der Abgleich je Rechnung als „nicht verfügbar“ statt als
„kein Treffer“ erscheinen.

#### Scenario: SevDesk nicht erreichbar

- **WHEN** der Abruf mit einem Netzwerkfehler scheitert und ein Abzug von gestern vorliegt
- **THEN** zeigt die Übersicht weiter die Treffer aus dem Abzug von gestern und einen Hinweis
  auf den gescheiterten Abruf

#### Scenario: Noch nie abgerufen

- **WHEN** noch kein Abruf erfolgreich war
- **THEN** zeigt jede Rechnung „Abgleich nicht verfügbar“

### Requirement: Ein sicherer Treffer entsteht über die Beleg-ID

Lector MUSS eine Rechnung einem Beleg sicher zuordnen, wenn die Beleg-ID bei der Rechnung
vermerkt ist, entweder aus Lectors eigenem Export oder aus dem Paperless-Feld
„SevDesk-Beleg“. Ist die vermerkte ID nicht im Abzug enthalten, MUSS die Übersicht
„Beleg in SevDesk nicht gefunden“ zeigen.

#### Scenario: Von Lector exportiert

- **WHEN** Lector eine Rechnung als Beleg 1234 exportiert hat und 1234 im Abzug steht
- **THEN** zeigt die Rechnung den sicheren Treffer „Beleg 1234“

#### Scenario: ID nur in Paperless vermerkt

- **WHEN** Lectors Datenbank keinen Export kennt, das Paperless-Feld „SevDesk-Beleg“ aber 1234
  enthält und 1234 im Abzug steht
- **THEN** zeigt die Rechnung den sicheren Treffer „Beleg 1234“

#### Scenario: Beleg verschwunden

- **WHEN** eine Rechnung als Beleg 1234 exportiert wurde, 1234 aber nicht mehr im Abzug steht
- **THEN** zeigt die Rechnung „Beleg in SevDesk nicht gefunden“

### Requirement: Ein ähnlicher Treffer entsteht über Betrag, Datum und Lieferant

Für Rechnungen ohne sicheren Treffer MUSS Lector ähnliche Belege suchen. Voraussetzung ist ein
bekannter Betrag der Rechnung; Kandidaten MÜSSEN im Betrag auf den Cent übereinstimmen und im
Belegdatum innerhalb eines konfigurierbaren Fensters um das Rechnungsdatum liegen. Aus
Datumsabstand und Ähnlichkeit von Lieferant und Korrespondent MUSS ein Score zwischen 0 und 1
entstehen. Kandidaten ab einer konfigurierbaren Mindestschwelle MÜSSEN als „mögliche Dublette“
mit Score angezeigt werden. Ohne bekannten Betrag MUSS die Übersicht „ohne Betrag nicht
prüfbar“ zeigen statt „kein Treffer“. Ein Beleg, der bereits einer anderen Rechnung sicher
zugeordnet ist, DARF NICHT als ähnlicher Treffer erscheinen. Belege ohne Summe DÜRFEN nur für
Rechnungen mit unklarem Exportausgang Kandidaten sein; dort MÜSSEN sie über Datum und
Ähnlichkeit von Lieferant oder Beschreibung gefunden werden, unabhängig vom Betrag.

#### Scenario: Gleicher Betrag, nahes Datum, gleicher Lieferant

- **WHEN** eine Rechnung über 112,00 EUR von „Amazon Web Services“ vom 03.10. vorliegt und
  SevDesk einen Beleg über 112,00 EUR von „AWS EMEA SARL“ vom 04.10. enthält
- **THEN** zeigt die Rechnung eine mögliche Dublette mit diesem Beleg und einem Score

#### Scenario: Betrag weicht ab

- **WHEN** der einzige Beleg mit passendem Datum und Lieferant 112,01 EUR lautet und die
  Rechnung 112,00 EUR
- **THEN** zeigt die Rechnung keinen ähnlichen Treffer

#### Scenario: Betrag unbekannt

- **WHEN** für eine Rechnung kein Betrag ermittelt wurde
- **THEN** zeigt die Rechnung „ohne Betrag nicht prüfbar“

#### Scenario: Unklarer Export ohne Summe

- **WHEN** eine Rechnung „unklar“ ist und SevDesk einen Entwurf ohne Summe mit passendem Datum
  und dem Rechnungstitel als Beschreibung enthält
- **THEN** zeigt die Rechnung diesen Entwurf als mögliche Dublette

#### Scenario: Beleg bereits vergeben

- **WHEN** ein Beleg einer Rechnung A sicher zugeordnet ist und zu Rechnung B passen würde
- **THEN** erscheint er bei B nicht als ähnlicher Treffer

### Requirement: Der Nutzer entscheidet über ähnliche Treffer dauerhaft

Der Nutzer MUSS einen ähnlichen Treffer als „derselbe Beleg“ bestätigen oder als „anderer
Beleg“ verwerfen können. Die Entscheidung MUSS über spätere Abrufe und Neustarts erhalten
bleiben. Ein bestätigter Treffer MUSS wie ein sicherer Treffer gelten. Ein verworfener Treffer
DARF für dieselbe Rechnung NICHT erneut als mögliche Dublette erscheinen.

#### Scenario: Bestätigen

- **WHEN** der Nutzer den Treffer „Beleg 987“ als derselbe Beleg bestätigt
- **THEN** gilt die Rechnung als in SevDesk vorhanden und der Export wird nicht angeboten

#### Scenario: Verwerfen

- **WHEN** der Nutzer den Treffer „Beleg 987“ als anderer Beleg verwirft und später ein neuer
  Abruf läuft
- **THEN** erscheint Beleg 987 bei dieser Rechnung nicht mehr als mögliche Dublette

### Requirement: Zuordnungen sind von beiden Seiten abfragbar

Jede Zuordnung zwischen Rechnung und Beleg MUSS als eigene Beziehung mit Art (sicher, ähnlich,
bestätigt, verworfen) und Score gespeichert sein, sodass sich sowohl die Treffer einer
Rechnung als auch die Belege ohne jede Rechnung ermitteln lassen.

#### Scenario: Belege ohne Rechnung ermitteln

- **WHEN** der Abzug drei Belege enthält und nur einer einer Rechnung zugeordnet ist
- **THEN** lassen sich die beiden übrigen als Belege ohne Paperless-Rechnung abfragen
