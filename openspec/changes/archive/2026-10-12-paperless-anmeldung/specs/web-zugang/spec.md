# Spec Delta

## Purpose

Regelt, wer die Weboberfläche bedienen darf. Wahlweise ist sie anmeldefrei (Betrieb im lokalen
Netz) oder durch eine Anmeldung geschützt, die die angebundene Paperless-Instanz prüft, sodass
der Dienst auch öffentlich erreichbar betrieben werden kann.

## ADDED Requirements

### Requirement: Der Zugangsmodus wird über `AUTH_MODE` gewählt

Der Dienst MUSS zwei Zugangsmodi kennen, wählbar über `AUTH_MODE`: `none` (ohne Anmeldung)
und `paperless` (Anmeldung über Paperless). Fehlt die Angabe, MUSS `none` gelten. Ein
unbekannter Wert MUSS den Start mit einer Begründung verhindern. Bei `paperless` MUSS
`PAPERLESS_URL` gesetzt sein, unabhängig davon, ob die übrigen Paperless-Funktionen
eingeschaltet sind. Diese Prüfungen folgen denselben Regeln wie die übrige Startprüfung.
Insbesondere MÜSSEN alle Beanstandungen gemeinsam gemeldet werden.

#### Scenario: Ohne Angabe läuft der Dienst anmeldefrei

- **WHEN** der Dienst ohne `AUTH_MODE` gestartet und die Weboberfläche aufgerufen wird
- **THEN** ist sie ohne Anmeldung vollständig bedienbar

#### Scenario: Unbekannter Zugangsmodus

- **WHEN** der Dienst mit `AUTH_MODE=offen` gestartet wird
- **THEN** startet er nicht und nennt `AUTH_MODE` als beanstandete Angabe

#### Scenario: Anmeldung über Paperless ohne Paperless-Adresse

- **WHEN** der Dienst mit `AUTH_MODE=paperless` und leerem `PAPERLESS_URL` gestartet wird,
  während die übrigen Paperless-Funktionen ausgeschaltet sind
- **THEN** startet er nicht und nennt `PAPERLESS_URL` als beanstandete Angabe

### Requirement: Die Anmeldung wird von Paperless geprüft

Im Modus `paperless` MUSS der Dienst eine Anmeldeseite mit Nutzername, Passwort und einem
optionalen MFA-Code anbieten. Er MUSS die Angaben bei der konfigurierten Paperless-Instanz
prüfen lassen und jede Person zulassen, deren Angaben Paperless akzeptiert. Darüber hinaus
DARF er keine eigene Prüfung von Rollen, Gruppen oder Rechten vornehmen. Der Dienst DARF
weder Passwörter noch von Paperless ausgestellte Zugangsschlüssel speichern oder für
andere Zwecke weiterverwenden. Die Bestätigung durch Paperless dient ausschließlich dazu,
eine eigene Sitzung zu eröffnen.

#### Scenario: Gültige Anmeldedaten

- **WHEN** eine Person Nutzername und Passwort eines aktiven Paperless-Kontos eingibt
- **THEN** ist sie angemeldet und gelangt auf die Seite, die sie ursprünglich aufrufen wollte,
  ersatzweise auf die Startseite

#### Scenario: Konto mit Zwei-Faktor-Anmeldung

- **WHEN** eine Person für ein Paperless-Konto mit aktivierter Zwei-Faktor-Anmeldung
  Nutzername, Passwort und einen gültigen MFA-Code eingibt
- **THEN** ist sie angemeldet

#### Scenario: Paperless verlangt einen MFA-Code, der fehlt

- **WHEN** Paperless die Anmeldung wegen eines fehlenden MFA-Codes ablehnt
- **THEN** bleibt die Person abgemeldet, und die Anmeldeseite fordert ausdrücklich zur
  Eingabe des MFA-Codes auf

#### Scenario: Falsche Anmeldedaten

- **WHEN** Nutzername, Passwort oder MFA-Code von Paperless abgelehnt werden
- **THEN** bleibt die Person abgemeldet, und die Anmeldeseite meldet einheitlich, dass die
  Anmeldung fehlgeschlagen ist, ohne erkennen zu lassen, welche der Angaben falsch war oder
  ob das Konto existiert

#### Scenario: Bereits angemeldet

- **WHEN** eine angemeldete Person die Anmeldeseite aufruft
- **THEN** wird sie zur Startseite weitergeleitet

### Requirement: Ist Paperless nicht erreichbar, schlägt nur die neue Anmeldung fehl

Kann der Dienst Paperless bei einer Anmeldung nicht erreichen oder antwortet Paperless mit
einem Serverfehler, MUSS die Anmeldeseite dies als eigenen Grund melden, unterscheidbar von
falschen Anmeldedaten. Ein solcher Versuch DARF NICHT als Fehlversuch zählen. Einen
anderen Zugangsweg, der ohne Paperless auskommt, DARF der Dienst NICHT anbieten. Bestehende
Sitzungen MÜSSEN unabhängig von der Erreichbarkeit von Paperless gültig bleiben.

#### Scenario: Paperless ist bei der Anmeldung nicht erreichbar

- **WHEN** eine Person sich anmelden will und Paperless nicht antwortet
- **THEN** bleibt sie abgemeldet, und die Anmeldeseite meldet, dass Paperless nicht
  erreichbar ist

#### Scenario: Angemeldete Person während eines Paperless-Ausfalls

- **WHEN** eine angemeldete Person die Weboberfläche nutzt, während Paperless nicht
  erreichbar ist
- **THEN** bleibt sie angemeldet, und alle Bereiche, die Paperless nicht benötigen, bleiben
  bedienbar

### Requirement: Im Modus `paperless` ist die Oberfläche nur nach Anmeldung zugänglich

Im Modus `paperless` MUSS jeder Bereich des Dienstes eine gültige Sitzung verlangen,
einschließlich nachgeladener Seitenteile, des Ereignisstroms für Live-Aktualisierungen, des
Datei-Uploads und aller Aktionen. Ohne Anmeldung zugänglich bleiben MÜSSEN ausschließlich
der Health-Endpunkt, die statischen Ressourcen (Stylesheets, Skripte, Symbole) sowie die
Anmeldeseite selbst. Eine automatisch erzeugte Schnittstellenbeschreibung DARF in keinem
Modus abrufbar sein.

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

#### Scenario: Health-Endpunkt ohne Sitzung

- **WHEN** der Health-Endpunkt im Modus `paperless` ohne Sitzung abgefragt wird
- **THEN** antwortet er wie ohne Zugangsschutz

#### Scenario: Schnittstellenbeschreibung

- **WHEN** die Pfade `/docs`, `/redoc` oder `/openapi.json` aufgerufen werden, gleich in
  welchem Modus und ob mit oder ohne Sitzung
- **THEN** liefert der Dienst keine Schnittstellenbeschreibung aus

### Requirement: Das Rücksprungziel bleibt innerhalb des Dienstes

Der Dienst MUSS nach der Anmeldung ausschließlich zu Pfaden des eigenen Dienstes
weiterleiten. Ein Rücksprungziel, das auf eine andere Adresse verweist, MUSS durch die
Startseite ersetzt werden.

#### Scenario: Fremdes Rücksprungziel

- **WHEN** die Anmeldeseite mit einem Rücksprungziel auf eine fremde Adresse aufgerufen und die
  Anmeldung erfolgreich abgeschlossen wird
- **THEN** landet die Person auf der Startseite des Dienstes

### Requirement: Eine Sitzung gilt gleitend 30 Tage

Eine Sitzung MUSS 30 Tage nach der letzten Nutzung der Oberfläche ablaufen. Jede Nutzung
MUSS die Frist neu beginnen lassen. Unabhängig davon MUSS jede Sitzung spätestens 90 Tage
nach der Anmeldung enden. Der Dienst MUSS jede Sitzung selbst kennen. Eine Sitzung
ist nur gültig, solange der Dienst sie als bestehend führt, nicht schon dadurch, dass ein
Browser ein formal gültiges Sitzungsmerkmal vorzeigt. Sitzungen MÜSSEN einen Neustart des
Dienstes überstehen. Ändert der Betreiber das Sitzungsgeheimnis (`LECTOR_SECRET_KEY`),
MÜSSEN alle bestehenden Sitzungen ungültig werden. Ist kein Sitzungsgeheimnis konfiguriert,
MUSS der Dienst beim ersten Start eines erzeugen und dauerhaft neben seiner Datenbank
aufbewahren.

#### Scenario: Regelmäßige Nutzung

- **WHEN** eine angemeldete Person die Oberfläche mindestens alle 30 Tage nutzt
- **THEN** bleibt sie ohne erneute Anmeldung angemeldet, höchstens aber 90 Tage ab der
  Anmeldung

#### Scenario: Absolute Höchstdauer erreicht

- **WHEN** seit der Anmeldung mehr als 90 Tage vergangen sind, auch bei täglicher Nutzung
- **THEN** ist die Sitzung ungültig, und der nächste Aufruf führt zur Anmeldeseite

#### Scenario: Längere Pause

- **WHEN** eine Sitzung länger als 30 Tage nicht genutzt wurde
- **THEN** ist sie ungültig, und der nächste Aufruf führt zur Anmeldeseite

#### Scenario: Neustart des Dienstes

- **WHEN** der Dienst ohne Änderung des Sitzungsgeheimnisses neu startet
- **THEN** bleiben bestehende Sitzungen gültig

#### Scenario: Sitzungsgeheimnis gewechselt

- **WHEN** der Dienst mit einem anderen `LECTOR_SECRET_KEY` neu startet
- **THEN** ist jede zuvor ausgestellte Sitzung ungültig

### Requirement: Eine Person kann sich abmelden

Im Modus `paperless` MUSS die Oberfläche auf jeder Seite eine Möglichkeit zum Abmelden
anbieten. Nach dem Abmelden MUSS die bisherige Sitzung beim Dienst selbst ungültig sein,
auch für jede Kopie ihres Sitzungsmerkmals. Andere Sitzungen derselben Person (z. B. auf
einem anderen Gerät) MÜSSEN davon unberührt bleiben. Im Modus `none` DARF keine
Abmeldemöglichkeit angezeigt werden.

#### Scenario: Abmelden

- **WHEN** eine angemeldete Person sich abmeldet
- **THEN** landet sie auf der Anmeldeseite, und weitere Aufrufe verlangen eine neue Anmeldung

#### Scenario: Kopiertes Sitzungsmerkmal nach dem Abmelden

- **WHEN** jemand eine Kopie des Sitzungsmerkmals besitzt und die Person sich anschließend
  abmeldet
- **THEN** wird auch die Kopie wie eine Anfrage ohne Sitzung behandelt

#### Scenario: Zweites Gerät bleibt angemeldet

- **WHEN** eine Person auf zwei Geräten angemeldet ist und sich auf einem abmeldet
- **THEN** bleibt sie auf dem anderen Gerät angemeldet

### Requirement: Das Sitzungsmerkmal ist gegen Mitlesen und Fremdzugriff geschützt

Das Merkmal, an dem der Dienst eine Sitzung erkennt, MUSS gegen Veränderung gesichert sein,
DARF für Skripte der Seite nicht lesbar sein und DARF vom Browser nicht bei Anfragen
mitgeschickt werden, die von einer anderen Website ausgehen. Ist `SESSION_COOKIE_SECURE`
eingeschaltet, DARF es nur über verschlüsselte Verbindungen übertragen werden. Ohne die
Angabe MUSS es auch über unverschlüsselte Verbindungen funktionieren.

#### Scenario: Verändertes Sitzungsmerkmal

- **WHEN** eine Anfrage ein verändertes oder selbst erstelltes Sitzungsmerkmal mitschickt
- **THEN** behandelt der Dienst sie wie eine Anfrage ohne Sitzung

#### Scenario: Betrieb hinter einem HTTPS-Proxy

- **WHEN** `SESSION_COOKIE_SECURE` eingeschaltet ist und die Oberfläche über HTTPS aufgerufen
  wird
- **THEN** funktioniert die Anmeldung, und das Sitzungsmerkmal ist auf verschlüsselte
  Verbindungen beschränkt

### Requirement: Zustandsändernde Anfragen müssen von der eigenen Oberfläche stammen

Im Modus `paperless` MUSS der Dienst jede zustandsändernde Anfrage (Anmelden, Abmelden,
Upload und alle Aktionen) ablehnen, deren Herkunftsangabe des Browsers nicht auf die eigene
Adresse des Dienstes verweist oder fehlt. Das gilt auch für Anfragen von anderen Adressen
derselben übergeordneten Domain (z. B. eine Schwester-Subdomain), weil der Browser das
Sitzungsmerkmal dorthin ebenfalls mitschickt.

#### Scenario: Formular einer anderen Subdomain

- **WHEN** eine Seite unter einer anderen Subdomain derselben Domain eine angemeldete Person
  dazu bringt, eine Aktion an den Dienst abzuschicken
- **THEN** lehnt der Dienst die Anfrage ab und führt die Aktion nicht aus

#### Scenario: Aktion aus der eigenen Oberfläche

- **WHEN** eine angemeldete Person eine Aktion über die Oberfläche des Dienstes auslöst
- **THEN** wird sie ausgeführt, auch wenn der Dienst hinter einem Proxy unter einer
  öffentlichen Adresse erreichbar ist

### Requirement: Wiederholte Fehlversuche werden gebremst

Im Modus `paperless` MUSS der Dienst Anmeldeversuche begrenzen, und zwar sowohl je
Absenderadresse als auch je Nutzername. Nach fünf Fehlversuchen innerhalb von 15 Minuten
MUSS er weitere Versuche aus derselben Quelle bzw. für denselben Nutzernamen bis zum Ende
dieses Zeitfensters abweisen, ohne Paperless zu befragen, und dies auf der Anmeldeseite
melden. Als Absenderadresse MUSS die Adresse des eigentlichen Clients gelten, nicht die
eines vorgeschalteten, als vertrauenswürdig konfigurierten Proxys. Eine erfolgreiche
Anmeldung MUSS die Fehlversuche für diesen Nutzernamen zurücksetzen.

#### Scenario: Wiederholtes Raten

- **WHEN** von derselben Adresse innerhalb von 15 Minuten fünf Anmeldungen fehlschlagen
- **THEN** werden weitere Versuche von dieser Adresse bis zum Ablauf des Zeitfensters
  abgewiesen, ohne an Paperless weitergereicht zu werden

#### Scenario: Verteiltes Raten auf einen Nutzernamen

- **WHEN** für denselben Nutzernamen von verschiedenen Adressen innerhalb von 15 Minuten
  fünf Anmeldungen fehlschlagen
- **THEN** werden weitere Versuche für diesen Nutzernamen bis zum Ablauf des Zeitfensters
  abgewiesen

#### Scenario: Andere Nutzer hinter demselben Proxy

- **WHEN** ein Angreifer gebremst wird und der Dienst hinter einem vertrauenswürdig
  konfigurierten Proxy läuft
- **THEN** können sich andere Personen, die über denselben Proxy zugreifen, weiterhin anmelden

### Requirement: Anmeldeversuche werden ohne Geheimnisse protokolliert

Der Dienst MUSS jeden fehlgeschlagenen und jeden gebremsten Anmeldeversuch mit Zeitpunkt,
Absenderadresse und Nutzername protokollieren. Passwörter, MFA-Codes und von Paperless
ausgestellte Zugangsschlüssel DÜRFEN in keinem Protokoll erscheinen.

#### Scenario: Fehlversuch im Protokoll

- **WHEN** eine Anmeldung mit falschem Passwort fehlschlägt
- **THEN** enthält das Protokoll Absenderadresse und Nutzername, aber nicht das Passwort

### Requirement: Die Oberfläche setzt schützende Antwort-Header

Der Dienst MUSS in jedem Modus mit jeder Seite Angaben ausliefern, die verhindern, dass die
Oberfläche in fremde Seiten eingebettet wird, die das Nachladen von Skripten und
Stylesheets auf die eigene Adresse beschränken, die keine vollständigen Adressen an fremde
Seiten weitergeben und die das Umdeuten von Inhaltstypen durch den Browser unterbinden.
Die bestehende Oberfläche MUSS mit diesen Angaben unverändert funktionieren.

#### Scenario: Einbettung in eine fremde Seite

- **WHEN** eine fremde Seite die Oberfläche in einem Rahmen einbetten will
- **THEN** verweigert der Browser die Darstellung

#### Scenario: Oberfläche mit Schutzangaben

- **WHEN** die Oberfläche mit diesen Angaben aufgerufen wird
- **THEN** funktionieren Live-Aktualisierung, Upload, Vorschaubilder und alle Aktionen wie
  zuvor
