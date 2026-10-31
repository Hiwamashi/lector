# agenten-zugang Specification

## Purpose

Regelt, wie KI-Agents (claude.ai, Claude Code, n8n) über einen MCP-Server auf Paperless
zugreifen: Anmeldung je Client, Rechteumfang und Sichtbarkeit der Dokumente. Die Schutzgrenzen
liegen in Paperless selbst, damit sie auch gegen einen durch Dokumentinhalte manipulierten
Agent halten.

## Requirements

### Requirement: Clients melden sich mit dem Token eines Agent-Benutzers an

Der MCP-Endpunkt MUSS jede neue Sitzung ohne Paperless-Token im Header `Authorization: Bearer
<token>` abweisen. Jede Paperless-Abfrage einer Sitzung MUSS mit dem Token dieser Sitzung
erfolgen, sodass Paperless die Rechte des zugehörigen Benutzers durchsetzt. Jeder Token MUSS
einem Benutzer der Gruppe `agents` gehören, nie einem Admin- oder persönlichen Konto. Clients
dürfen sich einen Agent-Benutzer teilen (z. B. Claude Code über den claude.ai-Connector); sie
sind dann in der Dokumenthistorie nicht zu unterscheiden und nur gemeinsam zu sperren. Clients
mit eigenem Agent-Benutzer MÜSSEN einzeln sperrbar sein.

#### Scenario: Anfrage ohne Token

- **WHEN** ein Client eine MCP-Sitzung ohne `Authorization`-Header eröffnen will
- **THEN** antwortet der Endpunkt mit HTTP 401 und es findet kein Zugriff auf Paperless statt

#### Scenario: Ungültiger Token

- **WHEN** ein Client eine Sitzung mit einem Token eröffnet, den Paperless nicht kennt, und ein
  Tool aufruft
- **THEN** schlägt der Aufruf fehl und es werden keine Daten aus Paperless zurückgegeben

#### Scenario: Einzelnen Client sperren

- **WHEN** der Token des Benutzers für n8n in Paperless widerrufen wird
- **THEN** kann n8n nicht mehr zugreifen, claude.ai und Claude Code arbeiten unverändert weiter

#### Scenario: Geteilter Agent-Benutzer

- **WHEN** Claude Code den claude.ai-Connector mitnutzt und über ihn ein Dokument ändert
- **THEN** nennt die Dokumenthistorie den Agent-Benutzer des claude.ai-Connectors

### Requirement: Agents dürfen lesen und Metadaten pflegen, aber nichts löschen

Die Benutzer der Gruppe `agents` MÜSSEN Dokumente ansehen und ändern sowie Tags,
Korrespondenten, Dokumenttypen und Custom Fields ansehen, anlegen und ändern können. Sie DÜRFEN
NICHT löschen (weder Dokumente noch Tags, Korrespondenten, Dokumenttypen oder Custom Fields)
und DÜRFEN KEINE Dokumente hochladen. Sie DÜRFEN KEINE Rechte auf Benutzer,
Gruppen, Mail-Konten, Mail-Regeln, Workflows und Einstellungen haben. Diese Grenzen MÜSSEN in
Paperless durchgesetzt werden, unabhängig davon, welche Tools der MCP-Server anbietet.

#### Scenario: Tag setzen

- **WHEN** ein Agent einem für `agents` freigegebenen Dokument einen Tag hinzufügt
- **THEN** ist der Tag am Dokument gesetzt und die Historie nennt den Benutzer des Clients

#### Scenario: Löschversuch

- **WHEN** ein Agent ein Dokument oder einen Tag löschen will
- **THEN** lehnt Paperless den Aufruf ab und das Objekt bleibt erhalten

#### Scenario: Rechteausweitung

- **WHEN** ein Agent einen Benutzer anlegen, sich einer Gruppe hinzufügen, eine Mail-Regel oder
  einen Workflow anlegen will
- **THEN** lehnt Paperless den Aufruf ab

#### Scenario: Hochladen

- **WHEN** ein Agent ein Dokument hochladen will
- **THEN** lehnt Paperless den Aufruf ab

### Requirement: Agents sehen nur freigegebene Dokumente

Ein Dokument MUSS für Agents nur sichtbar sein, wenn es der Gruppe `agents` freigegeben ist
oder keinen Besitzer hat. Neu hinzugefügte Dokumente — auch die von Lector über den
Consume-Ordner eingelieferten — MÜSSEN automatisch für `agents` zum Ansehen und Ändern
freigegeben werden. Gibt der Anwender einem Dokument einen Besitzer und entfernt die Freigabe
für `agents`, MUSS es für Agents unsichtbar werden. Bei Dokumenten ohne Besitzer dürfen Agents
deren Rechte und Besitzer setzen (Verhalten von Paperless); das ist bewusst akzeptiert, solange
nur der Anwender selbst Agents nutzt.

#### Scenario: Neues Dokument aus Lector

- **WHEN** Lector ein Ergebnis-PDF in `consume` ablegt und Paperless es importiert
- **THEN** ist das Dokument für die Agents sichtbar und änderbar

#### Scenario: Dokument bewusst verbergen

- **WHEN** der Anwender einem Dokument einen Besitzer gibt und die Freigabe für `agents` entfernt
- **THEN** taucht es in Suchen und Listen der Agents nicht mehr auf

### Requirement: Der MCP-Dienst hält keinen privilegierten Token

Der MCP-Server DARF KEINEN Paperless-Token mit Rechten über die eines anfragenden Clients hinaus
erhalten. Die semantische Suche, die einen Indexierungs-Token mit Lesezugriff auf alle
Dokumente voraussetzt, MUSS ausgeschaltet bleiben.

#### Scenario: Dienstkonfiguration

- **WHEN** die Konfiguration des MCP-Dienstes eingesehen wird
- **THEN** enthält sie keinen echten Paperless-Token und die semantische Suche ist ausgeschaltet

### Requirement: Der Endpunkt ist nur unter seiner eigenen Domain erreichbar und gepinnt

Der MCP-Endpunkt MUSS ausschließlich über HTTPS unter der dafür vorgesehenen Domain erreichbar
sein und Anfragen mit fremdem `Host`-Header abweisen. Anfragen aus Browsern fremder Herkunft
MÜSSEN abgewiesen werden. Das Image des MCP-Servers MUSS auf eine feste Version gepinnt sein und
DARF NICHT automatisch aktualisiert werden.

#### Scenario: Fremder Host-Header

- **WHEN** eine Anfrage mit einem anderen `Host` als der vorgesehenen Domain eintrifft
- **THEN** antwortet der Endpunkt mit HTTP 403

#### Scenario: Neues Release des MCP-Servers

- **WHEN** eine neue Version des MCP-Servers veröffentlicht wird
- **THEN** läuft weiter die gepinnte Version, bis der Anwender die Version bewusst anhebt
