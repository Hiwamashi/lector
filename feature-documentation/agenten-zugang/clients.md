# Clients anbinden

Alle Clients nutzen denselben Endpunkt `https://paperless-mcp.<domain>/mcp` mit **ihrem
eigenen** Token (siehe [rechte.md](rechte.md)). Der Header lautet immer
`Authorization: Bearer <token>`.

## claude.ai

*Customize → Connectors → Add custom connector*:

| Feld | Wert |
|---|---|
| Server-URL | `https://paperless-mcp.<domain>/mcp` |
| Authentication | **No sign-in** |
| Request headers | `authorization` = `Bearer <token agent-claudeai>` (das „Bearer “ mit Leerzeichen gehört in den Wert; claude.ai setzt kein Schema davor), *Required* |

Request-Header sind bei claude.ai eine Beta-Funktion. Fehlt der Abschnitt *Request headers* im
Dialog, ist sie für das Konto nicht freigeschaltet. Authentifizierungseinstellungen lassen sich
nach dem Anlegen nicht ändern: Bei neuem Token den Connector entfernen und neu anlegen.

**Tools zusätzlich sperren** (*Customize → Connectors →* Connector *→* Tool auf *Blocked*).
Paperless lehnt die meisten davon ohnehin ab; die Sperre ist die zweite Schicht und greift auch
für Aktionen, die das Ändern-Recht technisch erlaubt:

- alle `delete_*`-Tools
- `bulk_edit_documents` (kann u. a. Seiten löschen)
- `upload_document`, `upload_document_version`
- Benutzer- und Gruppen-Tools, Mail-Regel-Tools, Workflow-Tools
- `bulk_set_object_permissions`

## Claude Code

**Aktuelle Einrichtung (2026-10-31):** Claude Code nutzt den claude.ai-Connector, der dort
automatisch als „claude.ai Paperless (Privat)“ erscheint. Ein eigener Eintrag wurde wieder
entfernt, um Paperless nicht doppelt (je ~120 Tools) im Kontext zu haben. Folge: Änderungen aus
Claude Code erscheinen in der Paperless-Historie unter dem Benutzer des claude.ai-Connectors;
`agent-claudecode` wird derzeit nicht von einem Client genutzt.

Alternative mit eigener Zuordnung (dann den claude.ai-Connector in Claude Code über `/mcp`
deaktivieren):

    claude mcp add --transport http --scope user paperless \
      https://paperless-mcp.<domain>/mcp \
      --header "Authorization: Bearer <token agent-claudecode>"

Prüfen: `claude mcp list` zeigt `paperless` als verbunden. Tool-Freigaben für ändernde Tools
nicht dauerhaft erteilen („always allow“), damit jede Änderung bestätigt wird.

## n8n

MCP-Client-Node (bzw. MCP-Client-Tool in einem AI-Agent-Node) mit Endpunkt
`https://paperless-mcp.<domain>/mcp`, Transport *HTTP Streamable*, Authentifizierung
*Header Auth* mit Name `Authorization` und Wert `Bearer <token agent-n8n>`. Den Token als
n8n-Credential anlegen, nicht im Workflow selbst.

## Was Agents damit tun können

Suchen und Filtern (auch nach Custom Fields, z. B. offene Rechnungen ohne „Überwiesen“),
Dokumente und Notizen lesen, Tags/Korrespondenten/Dokumenttypen/Custom Fields setzen und
anlegen, Notizen anlegen. Nicht: löschen, hochladen, Rechte oder Benutzer verwalten,
Mail-Regeln oder Workflows anlegen.
