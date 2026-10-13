# Spec Delta

## ADDED Requirements

### Requirement: Eine App meldet sich über die Schnittstelle an und erhält einen Zugangsschlüssel

Im Modus `paperless` MUSS der Dienst eine Anmeldung über die App-Schnittstelle anbieten, mit
Nutzername, Passwort und optionalem MFA-Code. Für diese Anmeldung MÜSSEN dieselben Regeln
gelten wie für die Anmeldeseite:

- Prüfung durch Paperless, ohne eigene Rollen- oder Rechteprüfung
- keine Speicherung von Passwörtern oder Paperless-Schlüsseln
- Paperless-Ausfall als eigener Grund, der nicht als Fehlversuch zählt
- Protokollierung ohne Geheimnisse

Fehlversuche über die Schnittstelle und über die Anmeldeseite MÜSSEN gemeinsam gezählt und
gebremst werden. Bei Erfolg MUSS der Dienst eine Sitzung nach denselben Regeln eröffnen wie
bei der Anmeldeseite und einen Zugangsschlüssel zurückgeben, an dem er diese Sitzung erkennt.
Bei Misserfolg MUSS die Antwort maschinenlesbar einen von vier Gründen nennen:

- Anmeldung fehlgeschlagen
- MFA-Code erforderlich
- Paperless nicht erreichbar
- vorübergehend gebremst

Wie auf der Anmeldeseite DARF dabei nicht erkennbar werden, welche Angabe falsch war. Im
Modus `none` DARF es diese Anmeldung nicht geben.

#### Scenario: Erfolgreiche Anmeldung der App

- **WHEN** eine App gültige Angaben eines Paperless-Kontos an die Schnittstelle schickt
- **THEN** erhält sie einen Zugangsschlüssel, und der Dienst führt dafür eine Sitzung

#### Scenario: MFA-Code fehlt

- **WHEN** Paperless die Anmeldung über die Schnittstelle wegen eines fehlenden MFA-Codes
  ablehnt
- **THEN** nennt die Antwort den Grund „MFA-Code erforderlich“, und es wird kein Schlüssel
  ausgegeben

#### Scenario: Gemeinsame Bremse

- **WHEN** für denselben Nutzernamen drei Anmeldungen auf der Anmeldeseite und zwei über die
  Schnittstelle innerhalb von 15 Minuten fehlschlagen
- **THEN** werden weitere Versuche über beide Wege bis zum Ablauf des Zeitfensters abgewiesen,
  ohne Paperless zu befragen

#### Scenario: Anmeldung über die Schnittstelle im Modus `none`

- **WHEN** im Modus `none` eine Anmeldung über die Schnittstelle versucht wird
- **THEN** antwortet der Dienst mit „nicht gefunden“ (404)

### Requirement: Der Zugangsschlüssel weist eine Sitzung nach

Der Dienst MUSS einen Zugangsschlüssel, den der Client im Kopf der Anfrage mitschickt, als
Nachweis einer Sitzung anerkennen, gleichwertig zum Sitzungsmerkmal der Weboberfläche. Für
die so nachgewiesene Sitzung MÜSSEN dieselben Regeln gelten:

- 30 Tage gleitend ab der letzten Nutzung, höchstens 90 Tage ab der Anmeldung
- gültig nur, solange der Dienst die Sitzung führt
- ungültig nach einem Wechsel des Sitzungsgeheimnisses

Ein Zugangsschlüssel MUSS gegen Veränderung gesichert sein. Seine Gültigkeit DARF NICHT
davon abhängen, dass der Client ihn erneuert, solange die Sitzung besteht. Schickt eine
Anfrage einen Zugangsschlüssel mit, MUSS allein dieser über die Sitzung entscheiden. Ein
zusätzlich mitgeschicktes Sitzungsmerkmal bleibt dann unbeachtet. Eine App MUSS ihre Sitzung
über die Schnittstelle beenden können. Danach MUSS der Schlüssel ungültig sein, und andere
Sitzungen derselben Person MÜSSEN unberührt bleiben.

#### Scenario: Regelmäßige Nutzung durch die App

- **WHEN** eine App ihren Zugangsschlüssel mindestens alle 30 Tage benutzt
- **THEN** bleibt er gültig, höchstens aber 90 Tage ab der Anmeldung, ohne dass die App einen
  neuen Schlüssel beziehen muss

#### Scenario: Veränderter Zugangsschlüssel

- **WHEN** eine Anfrage einen veränderten oder selbst erstellten Zugangsschlüssel mitschickt
- **THEN** behandelt der Dienst sie wie eine Anfrage ohne Sitzung

#### Scenario: Abmelden der App

- **WHEN** eine App sich über die Schnittstelle abmeldet
- **THEN** wird jede weitere Anfrage mit diesem Schlüssel wie eine Anfrage ohne Sitzung
  behandelt, und eine Sitzung derselben Person im Browser bleibt bestehen

#### Scenario: Sitzungsgeheimnis gewechselt

- **WHEN** der Dienst mit einem anderen `LECTOR_SECRET_KEY` neu startet
- **THEN** ist jeder zuvor ausgegebene Zugangsschlüssel ungültig

## MODIFIED Requirements

### Requirement: Im Modus `paperless` ist die Oberfläche nur nach Anmeldung zugänglich

Im Modus `paperless` MUSS jeder Bereich des Dienstes eine gültige Sitzung verlangen,
einschließlich nachgeladener Seitenteile, des Ereignisstroms für Live-Aktualisierungen, des
Datei-Uploads, aller Aktionen und der App-Schnittstelle. Ohne Anmeldung zugänglich bleiben
MÜSSEN ausschließlich:

- der Health-Endpunkt
- die statischen Ressourcen (Stylesheets, Skripte, Symbole)
- die Anmeldeseite selbst
- die Selbstauskunft und die Anmeldung der App-Schnittstelle

Eine Sitzung kann durch das Sitzungsmerkmal der Weboberfläche oder durch einen
Zugangsschlüssel nachgewiesen werden. Eine automatisch erzeugte Schnittstellenbeschreibung
DARF in keinem Modus abrufbar sein.

#### Scenario: Seitenaufruf ohne Sitzung

- **WHEN** eine Seite der Oberfläche ohne gültige Sitzung aufgerufen wird
- **THEN** wird zur Anmeldeseite weitergeleitet, und die aufgerufene Seite wird als
  Rücksprungziel mitgegeben

#### Scenario: Nachgeladener Seitenteil oder Ereignisstrom ohne Sitzung

- **WHEN** ein nachgeladener Seitenteil oder der Ereignisstrom ohne gültige Sitzung angefragt
  wird
- **THEN** antwortet der Dienst mit dem Status „nicht angemeldet“ (401) statt mit Inhalt, und
  die geöffnete Oberfläche wechselt von sich aus zur Anmeldeseite

#### Scenario: Aktion ohne Sitzung

- **WHEN** ein Upload oder eine Aktion (z. B. als bezahlt markieren, Export auslösen) ohne
  gültige Sitzung abgeschickt wird
- **THEN** wird die Aktion nicht ausgeführt

#### Scenario: App-Schnittstelle ohne Sitzung

- **WHEN** ein Bereich der App-Schnittstelle außer Selbstauskunft und Anmeldung ohne gültige
  Sitzung angefragt wird
- **THEN** antwortet der Dienst mit 401 und führt nichts aus

#### Scenario: Health-Endpunkt ohne Sitzung

- **WHEN** der Health-Endpunkt im Modus `paperless` ohne Sitzung abgefragt wird
- **THEN** antwortet er wie ohne Zugangsschutz

#### Scenario: Schnittstellenbeschreibung

- **WHEN** die Pfade `/docs`, `/redoc` oder `/openapi.json` aufgerufen werden, gleich in
  welchem Modus und ob mit oder ohne Sitzung
- **THEN** liefert der Dienst keine Schnittstellenbeschreibung aus

### Requirement: Zustandsändernde Anfragen müssen von der eigenen Oberfläche stammen

Im Modus `paperless` MUSS der Dienst jede zustandsändernde Anfrage (Anmelden, Abmelden,
Upload und alle Aktionen) ablehnen, deren Herkunftsangabe des Browsers nicht auf die eigene
Adresse des Dienstes verweist oder fehlt. Das gilt auch für Anfragen von anderen Adressen
derselben übergeordneten Domain (z. B. eine Schwester-Subdomain), weil der Browser das
Sitzungsmerkmal dorthin ebenfalls mitschickt. Ausgenommen sind Anfragen, die ihre Sitzung
durch einen Zugangsschlüssel nachweisen, sowie die Anmeldung über die App-Schnittstelle. Ein
Browser schickt beides nicht von sich aus mit. Der Dienst DARF fremden Websites nicht
erlauben, Anfragen mit Zugangsschlüssel aus dem Browser heraus zu stellen.

#### Scenario: Formular einer anderen Subdomain

- **WHEN** eine Seite unter einer anderen Subdomain derselben Domain eine angemeldete Person
  dazu bringt, eine Aktion an den Dienst abzuschicken
- **THEN** lehnt der Dienst die Anfrage ab und führt die Aktion nicht aus

#### Scenario: Aktion aus der eigenen Oberfläche

- **WHEN** eine angemeldete Person eine Aktion über die Oberfläche des Dienstes auslöst
- **THEN** wird sie ausgeführt, auch wenn der Dienst hinter einem Proxy unter einer
  öffentlichen Adresse erreichbar ist

#### Scenario: Aktion der App ohne Herkunftsangabe

- **WHEN** eine App mit gültigem Zugangsschlüssel und ohne Herkunftsangabe eine Datei übergibt
  oder einen Vorgang freigibt
- **THEN** wird die Anfrage ausgeführt

#### Scenario: Fremde Website versucht eine Anfrage mit Zugangsschlüssel

- **WHEN** eine Seite einer fremden Adresse im Browser eine Anfrage mit Zugangsschlüssel an
  den Dienst stellen will
- **THEN** gibt der Dienst ihr keine Erlaubnis dazu, und der Browser führt die Anfrage nicht aus
