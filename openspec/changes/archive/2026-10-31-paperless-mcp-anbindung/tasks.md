# Tasks

Testbefehle: `uv run pytest`, `uv run ruff check .`. Aufgaben mit **(manuell)** führt der
Anwender in Paperless, auf dem NAS, am Proxy oder in den Clients aus; der Agent bereitet Werte
und Befehle vor und hakt erst nach Rückmeldung ab. Tokens erscheinen nie im Repository oder im
Chat.

## 1. Vorlage und Regressionstest

- [x] 1.1 In `tests/test_compose_files.py` Tests für den Dienst `paperless-mcp` ergänzen: Image `ghcr.io/orellbuehler/paperless-mcp:` mit exakter Version `X.Y.Z` (kein `latest`, kein reiner Major-Tag); `PAPERLESS_URL` = `http://webserver:8000`; `PAPERLESS_TOKEN` aus einer `${…}`-Variable; `EMBEDDINGS_ENABLED` nicht `true`; `MCP_ALLOWED_HOSTS` gesetzt; `MCP_ALLOWED_ORIGINS` leer oder fehlend; kein `build:`. Prüfen: Tests schlagen vor 1.2 fehl.
- [x] 1.2 Dienst `paperless-mcp` in `docker-compose.example.yml` ergänzen (Design D1, D2, D5), Image `1.4.1`, mit Kommentar zu Platzhalter-Token, Pinning und Proxy. In `.env.example` die Variablen `PAPERLESS_MCP_SERVICE_TOKEN` (Hinweis: Zufallswert, kein echter Token) und `PAPERLESS_MCP_HOST` mit Platzhaltern ergänzen. Prüfen: Tests aus 1.1 grün, `uv run pytest` und `uv run ruff check .` grün.

## 2. Paperless einrichten (manuell)

- [x] 2.1 **(manuell)** Gruppe `agents` mit den Rechten aus Design D3 anlegen; Benutzer `agent-claudeai`, `agent-claudecode`, `agent-n8n` (nicht Superuser, nicht Staff) als Mitglieder anlegen und je einen API-Token erzeugen. Prüfen: Gruppenrechte entsprechen der Tabelle in D3. — *Vom Anwender am 2026-10-31 als erledigt erklärt; Prüfung nicht durch den Agent nachvollzogen.*
- [x] 2.2 **(manuell)** Bestand freigeben: alle Dokumente auswählen → Rechte → Gruppe `agents` Ansehen + Ändern. Prüfen: `curl -H "Authorization: Token <agent-token>" https://paperless.nerd-wg.eu/api/documents/?page_size=1` liefert `count` gleich der Gesamtzahl.
- [x] 2.3 **(manuell)** Workflow „Agents freigeben“: Auslöser *Dokument hinzugefügt*, Aktion *Rechte zuweisen* → Gruppe `agents` Ansehen + Ändern. Prüfen: Ein über Lector eingeliefertes Testdokument ist mit dem Agent-Token abrufbar.
- [x] 2.4 **(manuell, mit Agent)** Grenzen mit einem Agent-Token direkt gegen die Paperless-API prüfen: Dokument löschen, Tag löschen, Benutzer anlegen, Mail-Regel anlegen, Dokument hochladen, Rechte eines Dokuments ändern → jeweils abgelehnt; Tag setzen → erlaubt. Zusätzlich festhalten, ob `bulk_edit` mit `delete_pages` mit reinem Ändern-Recht durchgeht. Prüfen: Ergebnisse in `feature-documentation/agenten-zugang/rechte.md` eingetragen; abweichende Befunde in `design.md` unter Risks ergänzt.

## 3. Dienst auf dem NAS (manuell)

- [x] 3.1 **(manuell)** Dienst aus der Vorlage in die NAS-Compose des `paperless-ngx-stack` übernehmen, `PAPERLESS_MCP_SERVICE_TOKEN` als Zufallswert (`openssl rand -hex 32`) setzen, Stack deployen. Prüfen: Container läuft, Log zeigt `paperless-mcp HTTP server listening on :3001/mcp`.
- [x] 3.2 **(manuell)** Proxy-Route `paperless-mcp.<domain>` → `paperless-mcp:3001` (HTTPS). Prüfen: `curl -i -X POST https://paperless-mcp.<domain>/mcp` ohne Header → 401; mit `-H "Host: anders.example"` direkt gegen den Dienst → 403. — *Vom Anwender am 2026-10-31 als erledigt erklärt; Prüfung nicht durch den Agent nachvollzogen.*

## 4. Clients anbinden (manuell)

- [x] 4.1 **(manuell)** claude.ai: Custom Connector nach Design D6 anlegen, die dort genannten Tools auf *Blocked* setzen. Prüfen: In einem Chat liefert „Liste die fünf neuesten Dokumente“ Ergebnisse; ein Löschversuch scheitert. — *Vom Anwender am 2026-10-31 als erledigt erklärt; Prüfung nicht durch den Agent nachvollzogen.*
- [x] 4.2 **(manuell)** Claude Code: `claude mcp add …` nach Design D6. Prüfen: `claude mcp list` zeigt `paperless` als verbunden. — Ergebnis: eigener Eintrag war verbunden, wurde aber auf Wunsch wieder entfernt; Claude Code nutzt den automatisch eingeblendeten claude.ai-Connector (siehe `clients.md`).
- [x] 4.3 **(manuell)** n8n: MCP-Client-Node mit Header-Auth. Prüfen: Ein Test-Workflow liest ein Dokument. — *Vom Anwender am 2026-10-31 als erledigt erklärt; Prüfung nicht durch den Agent nachvollzogen.*
- [x] 4.4 **(manuell)** In Paperless die Historie eines von einem Agent geänderten Dokuments ansehen. Prüfen: Die Änderung ist dem jeweiligen `agent-*`-Benutzer zugeordnet. — *Vom Anwender am 2026-10-31 als erledigt erklärt; Prüfung nicht durch den Agent nachvollzogen.*

## 5. Dokumentation

- [x] 5.1 `feature-documentation/agenten-zugang/README.md`: Überblick (Architektur, Clients, Grenzen), Verweis auf Spec und die Einzeldokumente. Prüfen: Datei vorhanden.
- [x] 5.2 `feature-documentation/agenten-zugang/rechte.md`: Gruppe, Benutzer, Rechtetabelle, Freigabe von Bestand und neuen Dokumenten, Verbergen einzelner Dokumente, Ergebnisse aus 2.4, Token-Widerruf. Prüfen: Datei vorhanden, keine echten Tokens.
- [x] 5.3 `feature-documentation/agenten-zugang/mcp-dienst.md`: Begleitdienst, Platzhalter-Token mit Quellcodebefund, Pinning und Prüfliste für Versions-Updates (Dienst-Token weiterhin nur für Embeddings? neue Tools? Changelog), Proxy, Fehlerbilder (401, 403, leere Ergebnislisten wegen fehlender Freigabe). Prüfen: Datei vorhanden.
- [x] 5.4 `feature-documentation/agenten-zugang/clients.md`: Anbindung claude.ai (inkl. Tool-Sperren), Claude Code, n8n. Prüfen: Datei vorhanden.
- [x] 5.5 `feature-documentation/README.md` (Index) und `prd/PROGRESS.md` ergänzen; `graphify update .` ausführen. Prüfen: Index verlinkt den Ordner, PROGRESS nennt den Stand, graphify ohne Fehler.
