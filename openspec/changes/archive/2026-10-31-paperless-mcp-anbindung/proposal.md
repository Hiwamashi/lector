# Proposal

## Why

Die Dokumente in Paperless sollen für die eigenen KI-Agents nutzbar werden: claude.ai, Claude
Code und n8n sollen im Dialog suchen, lesen und Metadaten pflegen können (z. B. „Welche
Rechnungen von X sind noch nicht überwiesen?“, Tags oder „Überwiesen“ setzen). Bisher
arbeiten KI-Funktionen nur automatisch beim Import (paperless-gpt, Empfänger-Zuordnung in
Lector). Weil Dokumente Text von Dritten enthalten und damit Prompt Injection mitbringen
können, braucht der Zugang eine harte Rechtegrenze, die nicht vom Agent abhängt.

## What Changes

- **Neu:** Ein MCP-Server für Paperless (Community-Projekt `OrellBuehler/paperless-mcp`,
  Image gepinnt) läuft als Begleitdienst im Paperless-Compose und spricht Paperless intern an.
  Er ist über den Reverse-Proxy öffentlich unter HTTPS erreichbar.
- **Neu:** Anmeldung je Client mit einem eigenen Paperless-API-Token als Bearer-Header. Jeder
  Client (claude.ai, Claude Code, n8n) bekommt einen eigenen Paperless-Benutzer; alle gehören
  zur Gruppe `agents`.
- **Neu:** Rechtestufe 2 für `agents`: Dokumente ansehen und ändern, Tags, Korrespondenten,
  Dokumenttypen und Custom Fields ansehen, anlegen und ändern. **Kein** Löschen, **kein**
  Hochladen, **keine** Rechte auf Benutzer, Gruppen, Mail, Workflows und Einstellungen.
- **Neu:** Freigabe der Dokumente an `agents` per Massenbearbeitung (Bestand) und per
  Paperless-Workflow (neue Dokumente, auch die von Lector eingelieferten).
- **Neu:** Der Dienst-Token des MCP-Servers ist ein Platzhalter ohne Rechte, kein Admin-Token
  (semantische Suche bleibt aus).
- `docker-compose.example.yml` erhält den Begleitdienst; ein Regressionstest hält Pinning und
  Sicherheitseinstellungen fest.
- Doku: Einrichtung der Paperless-Rechte, Proxy, Anbindung der drei Clients.

## Capabilities

### New Capabilities

- `agenten-zugang`: Zugang der KI-Agents zu Paperless über MCP: wer sich wie anmeldet, welche
  Rechte gelten, welche Dokumente sichtbar sind und welche Schutzgrenzen unabhängig vom
  Verhalten des Agents greifen.

### Modified Capabilities

_keine_ — der Lector-Dienst selbst ändert sich nicht.

## Impact

- **Compose:** `docker-compose.example.yml` (neuer Dienst `paperless-mcp`), `.env.example`
  (Platzhalter-Variable, `MCP_ALLOWED_HOSTS`).
- **Tests:** `tests/test_compose_files.py` (neue Prüfungen für den Begleitdienst).
- **Doku:** neuer Ordner `feature-documentation/agenten-zugang/`, Eintrag in
  `feature-documentation/README.md`, `prd/PROGRESS.md`.
- **Extern, manuell:** Paperless-Gruppe, Benutzer und Tokens; Paperless-Workflow;
  Proxy-Route; Einbau in die Compose auf dem NAS; Connector in claude.ai, Claude Code, n8n.
- **Abhängigkeit:** Community-Software mit Zugriff auf Paperless-Tokens; Updates nur bewusst
  nach Prüfung (Image gepinnt).
- **Lector-Code, API, iOS-App:** unverändert.
