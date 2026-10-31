# Design

## Context

Siehe `proposal.md` (Why). Ausgangslage:

- Paperless läuft im `paperless-ngx-stack` auf dem NAS; Dienstname `webserver`, intern
  `http://webserver:8000`, öffentlich `https://paperless.nerd-wg.eu` hinter einem
  Reverse-Proxy im Heimnetz. Die echte Compose liegt nur auf dem NAS; im Repo gibt es
  `docker-compose.example.yml` als Vorlage, abgesichert durch `tests/test_compose_files.py`.
- Der Stack wird künftig über Komodo mit Auto-Update aller `:latest`-Images betrieben
  (Repository `nas-stacks`). Ein dort gepinntes Image wird nicht automatisch aktualisiert.
- MCP-Server `OrellBuehler/paperless-mcp`, aktuell **v1.4.1** (2026-10-10), Image
  `ghcr.io/orellbuehler/paperless-mcp:<version>`. Geprüft im Quellcode v1.4.1:
  - `src/http.ts`: Eine neue Sitzung ohne Token (`Authorization: Bearer` oder
    `X-Paperless-Token`) wird mit 401 abgewiesen. Jede Sitzung nutzt ausschließlich den Token
    des Clients (`clientFor(token)`); es gibt keinen Rückfall auf den Dienst-Token.
    Folgeanfragen werden über die zufällige `mcp-session-id` (UUID) zugeordnet.
    `MCP_ALLOWED_HOSTS` → 403 bei fremdem Host, `MCP_ALLOWED_ORIGINS` leer → Browser-Origins
    gesperrt.
  - `src/config.ts`: `PAPERLESS_TOKEN` muss gesetzt sein, sonst beendet sich der Prozess. Im
    HTTP-Modus wird der daraus gebaute `adminClient` nur für die semantische Suche verwendet
    (`src/server.ts`, nur wenn `EMBEDDINGS_ENABLED`). Sendet ein Client genau diesen Wert als
    Token, bekommt er den `adminClient`.
  - Der Server bietet auch Lösch-, Benutzer-, Gruppen-, Mail-Regel- und Workflow-Tools an;
    einen Nur-Lesen-Modus gibt es nicht.
- claude.ai-Custom-Connectors können feste Request-Header senden (Beta, im Konto des Anwenders
  verfügbar); Authentifizierung „No sign-in“ + Header `authorization: Bearer <token>`.

## Goals / Non-Goals

**Goals:**

- Rechte- und Sichtbarkeitsgrenzen vollständig in Paperless verankern (Spec `agenten-zugang`).
- Den Begleitdienst so konfigurieren, dass er selbst kein lohnendes Ziel ist.

**Non-Goals:**

- Semantische Suche (Embeddings) — bräuchte einen Indexierungs-Token mit Vollzugriff.
- OAuth vor dem MCP-Server; MCP-Tunnel (nur Enterprise).
- Eigener MCP-Server in Lector.
- Rate-Limiting oder IP-Allowlist am Proxy (claude.ai kommt aus der Anthropic-Cloud,
  Claude Code und n8n von anderen Adressen).

## Decisions

### D1 — Begleitdienst im Paperless-Compose, Image gepinnt

Dienst `paperless-mcp` im selben Compose wie `webserver`, `PAPERLESS_URL:
http://webserver:8000` (interner Weg, kein Umweg über den Proxy). Image auf
`ghcr.io/orellbuehler/paperless-mcp:1.4.1` gepinnt — weder `latest` (folgt `main`) noch `1`
(folgt Minor-Releases), da Komodo sonst automatisch aktualisieren würde. Port nur für den Proxy
veröffentlicht (`3001`), kein Volume nötig (keine Embeddings).

*Alternative:* eigener Stack. Abgelehnt: bräuchte ein gemeinsames Docker-Netz mit Paperless,
ohne Vorteil.

### D2 — Dienst-Token ist ein Platzhalter

`PAPERLESS_TOKEN` bekommt einen langen Zufallswert, der in Paperless **keinem** Benutzer
gehört (`EMBEDDINGS_ENABLED` aus). Damit hält der Dienst kein Geheimnis mit Wert: Wer den Wert
als Client-Token sendet, landet beim `adminClient` und Paperless lehnt jeden Aufruf ab.
Begründung siehe Quellcodebefund oben. Bei jedem Versionssprung des MCP-Servers ist zu
prüfen, ob der Dienst-Token weiterhin nur für Embeddings dient (Aufgabe in der Doku).

*Alternative:* Token eines rechtelosen Paperless-Benutzers. Gleichwertig, aber ein Benutzer
mehr ohne Nutzen.

### D3 — Ein Paperless-Benutzer pro Client, Gruppe `agents`

Benutzer `agent-claudeai`, `agent-claudecode`, `agent-n8n`, jeweils Mitglied in `agents`,
nicht Superuser, nicht Staff. Je Benutzer ein API-Token (Paperless vergibt einen pro
Benutzer). Rechte nur über die Gruppe:

| Bereich | Ansehen | Hinzufügen | Ändern | Löschen |
|---|---|---|---|---|
| Dokumente | ✓ | – | ✓ | – |
| Tags, Korrespondenten, Dokumenttypen, Custom Fields | ✓ | ✓ | ✓ | – |
| Speicherpfade, Gespeicherte Ansichten | ✓ | – | – | – |
| Notizen | ✓ | ✓ | – | – |
| Benutzer, Gruppen, Mail-Konten, Mail-Regeln, Workflows, Einstellungen, Aufgaben | – | – | – | – |

### D4 — Sichtbarkeit über Objekt-Rechte

- Bestand: Massenbearbeitung in Paperless → *Rechte* → Gruppe `agents`: Ansehen + Ändern
  (Besitzer bleibt).
- Neu: Paperless-Workflow, Auslöser *Dokument hinzugefügt* (alle Quellen), Aktion *Rechte
  zuweisen* → Gruppe `agents`: Ansehen + Ändern. Greift auch für Lector-Ergebnisse aus
  `consume`.
- Verbergen: Freigabe an einzelnen Dokumenten entfernen.

### D5 — Öffentlicher Endpunkt

Proxy-Route `paperless-mcp.<domain>` → `paperless-mcp:3001`, nur HTTPS.
`MCP_ALLOWED_HOSTS` = diese Domain, `MCP_ALLOWED_ORIGINS` leer. Streamable HTTP über `/mcp`.

### D6 — Clients

| Client | Anbindung |
|---|---|
| claude.ai | Custom Connector, URL `https://paperless-mcp.<domain>/mcp`, Authentifizierung „No sign-in“, Request-Header `authorization` = `Bearer <token agent-claudeai>`. Zusätzlich die Tools `delete_*`, `bulk_edit_documents`, `upload_*`, Benutzer-/Gruppen-/Mail-/Workflow-Tools auf **Blocked** setzen. |
| Claude Code | `claude mcp add --transport http --scope user paperless https://paperless-mcp.<domain>/mcp --header "Authorization: Bearer <token agent-claudecode>"` |
| n8n | MCP-Client-Node, Header-Auth mit `Bearer <token agent-n8n>` |

## Risks / Trade-offs

- [Prompt Injection über Dokumentinhalte steuert den Agent] → Grenze in Paperless (D3): kein
  Löschen, keine Rechteverwaltung, kein Upload; zusätzlich Tool-Sperren in claude.ai.
- [„Ändern“ erlaubt destruktive Bearbeitung: Seiten löschen per `bulk_edit_documents`
  (`delete_pages`), Inhalt/Titel überschreiben, Notizen löschen] → in claude.ai blockieren;
  bei Claude Code Tool-Freigaben nicht dauerhaft erteilen; Paperless-Historie zeigt Änderungen
  je Benutzer. Welche Bulk-Methoden Paperless mit reinem Ändern-Recht zulässt, wird bei der
  Einrichtung geprüft (Aufgabe 2.4).
- [Agent ändert Rechte oder Besitzer eines Dokuments] → **Befund aus Aufgabe 2.4:** Paperless
  2.20.15 erlaubt das bei Dokumenten ohne Besitzer jedem Benutzer mit Ändern-Recht (alle 1560
  Dokumente sind besitzerlos); vermutlich gilt dasselbe für `delete_pages`/`rotate`/`merge`.
  **Bewusst akzeptiert**, da nur der Anwender selbst Agents nutzt; Tool-Sperren in claude.ai.
  Umkehr bei Bedarf: Besitzer für alle Dokumente setzen, Workflow um *Besitzer zuweisen* ergänzen.
- [Session-ID gilt ohne erneute Token-Prüfung] → zufällige UUID, nur über HTTPS übertragen;
  akzeptiert.
- [Community-Software mit Zugriff auf Agent-Tokens] → gepinnt, Updates nur nach Blick in den
  Changelog und erneuter Prüfung von D2.
- [claude.ai-Request-Header ist Beta] → fällt das Feature weg, bleiben Claude Code und n8n
  nutzbar; claude.ai bräuchte dann OAuth (nicht Teil dieses Changes).
- [Klartext-Token in der NAS-Compose] → wie bisher nur auf dem NAS; im Repo nur Platzhalter.

## Migration Plan

1. Paperless: Gruppe, Benutzer, Tokens, Freigabe des Bestands, Workflow.
2. Begleitdienst in die NAS-Compose übernehmen, Proxy-Route anlegen.
3. Clients verbinden, Grenzen gegen die Spec-Szenarien prüfen.

Rückbau: Dienst und Proxy-Route entfernen, Tokens der drei Benutzer widerrufen. Paperless-Daten
bleiben unberührt; Workflow und Gruppenfreigaben können bestehen bleiben.
