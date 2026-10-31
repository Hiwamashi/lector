# Agenten-Zugang: Paperless über MCP

KI-Agents (claude.ai, Claude Code, n8n) greifen über einen MCP-Server auf Paperless zu: suchen,
lesen, Metadaten pflegen. Das ist **kein Lector-Code**, sondern ein Begleitdienst im
Paperless-Compose. Er steht hier, weil er zum selben Stack gehört und die Vorlage
`docker-compose.example.yml` ihn enthält. Anforderungen: Spec `agenten-zugang`
(OpenSpec-Change `paperless-mcp-anbindung`).

```
claude.ai (Anthropic-Cloud) --+
Claude Code (Mac) ------------+--HTTPS--> Reverse-Proxy --> paperless-mcp:3001/mcp  (gepinnt)
n8n --------------------------+                                  |
   je Client ein eigener Bearer-Token                           | gleicher Token
                                                                v
                                              webserver:8000 -> Paperless prueft Rechte
                                              des Benutzers agent-* (Gruppe agents)
```

## Grundidee

Die Sicherheitsgrenze liegt **in Paperless**, nicht im MCP-Server und nicht im Agent.
Dokumente enthalten Text von Dritten; ein präpariertes PDF kann einen Agent zu Aktionen
verleiten (Prompt Injection). Deshalb dürfen die Agent-Benutzer in Paperless nur das, was im
schlimmsten Fall vertretbar ist: lesen und Metadaten pflegen, aber nicht löschen, nicht
hochladen und keine Rechte oder Mail-Regeln verwalten.

## Funktion ↔ Datei

| Datei | Inhalt |
|---|---|
| [rechte.md](rechte.md) | Gruppe `agents`, Benutzer je Client, Rechtetabelle, Freigabe der Dokumente, Sperren eines Clients |
| [mcp-dienst.md](mcp-dienst.md) | Begleitdienst `paperless-mcp`: Konfiguration, Platzhalter-Token, Pinning, Update-Prüfliste, Proxy, Fehlerbilder |
| [clients.md](clients.md) | Anbindung von claude.ai (mit Tool-Sperren), Claude Code und n8n |

## Abgrenzung

- **paperless-gpt** und die **Empfänger-Zuordnung** in Lector arbeiten automatisch beim
  Import. Der MCP-Zugang ist für Fragen und Aufgaben im Dialog.
- Keine semantische Suche (Embeddings): Sie bräuchte einen Indexierungs-Token mit
  Lesezugriff auf alles.
- Komodo, ntfy und das Ausrollen auf dem NAS: Repository `nas-stacks`.
