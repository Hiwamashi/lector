# Begleitdienst `paperless-mcp`

MCP-Server [OrellBuehler/paperless-mcp](https://github.com/OrellBuehler/paperless-mcp) im
HTTP-Modus, als Dienst neben `webserver` im Paperless-Compose. Vorlage:
`docker-compose.example.yml`, Dienst `paperless-mcp`; abgesichert durch die
`test_mcp_*`-Tests in `tests/test_compose_files.py`.

## Konfiguration

| Variable | Wert | Zweck |
|---|---|---|
| Image | `ghcr.io/orellbuehler/paperless-mcp:1.4.1` | exakt gepinnt |
| `MCP_TRANSPORT` / `PORT` | `http` / `3001` | Streamable HTTP unter `/mcp` |
| `PAPERLESS_URL` | `http://webserver:8000` | interner Weg, nicht über den Proxy |
| `PAPERLESS_TOKEN` | `${PAPERLESS_MCP_SERVICE_TOKEN}` | Zufallswert, siehe unten |
| `EMBEDDINGS_ENABLED` | `false` | keine semantische Suche |
| `MCP_ALLOWED_HOSTS` | `${PAPERLESS_MCP_HOST}` | 403 bei fremdem `Host`-Header (DNS-Rebinding) |
| `MCP_ALLOWED_ORIGINS` | nicht gesetzt | Browser-Anfragen fremder Herkunft gesperrt |

Kein Volume nötig, solange die Embeddings aus sind.

## Warum der Dienst-Token ein Platzhalter ist

Laut README braucht der HTTP-Modus einen Admin-Token. Im Quellcode v1.4.1 geprüft:

- `src/config.ts`: `PAPERLESS_TOKEN` muss nur gesetzt sein, sonst beendet sich der Prozess.
  Daraus entsteht `adminClient`.
- `src/server.ts`: `adminClient` wird nur verwendet, wenn `EMBEDDINGS_ENABLED` an ist.
- `src/http.ts`: Eine neue Sitzung ohne `Authorization: Bearer` bzw. `X-Paperless-Token`
  bekommt 401. Jede Sitzung arbeitet mit `clientFor(<Client-Token>)`; es gibt keinen Rückfall
  auf den Dienst-Token. Sendet ein Client genau den Dienst-Token, erhält er `adminClient`.

Ein Zufallswert, der keinem Paperless-Benutzer gehört, genügt also. Der Container hält damit
kein Geheimnis mit Wert, und wer den Wert als Client-Token sendet, wird von Paperless
abgewiesen. Erzeugen: `openssl rand -hex 32`.

## Prüfliste für einen Versionssprung

Das Image wird **nicht** automatisch aktualisiert (auch nicht durch Komodo). Vor dem Anheben:

1. Changelog und Diff seit der gepinnten Version lesen.
2. `src/config.ts`, `src/server.ts`, `src/http.ts`: Wird `PAPERLESS_TOKEN` weiterhin nur für
   Embeddings genutzt? Gibt es einen Rückfall auf ihn bei fehlendem Client-Token? Bleibt die
   401 bei fehlendem Token?
3. Neue Tools: Brauchen sie Rechte, die `agents` nicht hat (dann harmlos), oder öffnen sie
   etwas über vorhandene Rechte (dann in claude.ai sperren, siehe [clients.md](clients.md))?
4. Version in `docker-compose.example.yml`, dieser Datei und auf dem NAS anheben; Tests
   `uv run pytest tests/test_compose_files.py`.

## Proxy

Route `paperless-mcp.<domain>` → `paperless-mcp:3001`, nur HTTPS. Der Endpunkt ist
`https://paperless-mcp.<domain>/mcp`. `PAPERLESS_MCP_HOST` muss genau diese Domain sein.

## Sitzungen

Nach dem Initialisieren ordnet der Server Folgeanfragen über die Kopfzeile `mcp-session-id`
(zufällige UUID) zu, ohne den Token erneut zu prüfen. Das ist bei Übertragung nur über HTTPS
akzeptiert. Nach einem Neustart des Dienstes initialisieren die Clients neu.

## Fehlerbilder

| Symptom | Ursache | Behebung |
|---|---|---|
| HTTP 401 „Missing Paperless token“ | Client sendet keinen `Authorization`-Header | Header mit `Bearer ` + Token konfigurieren (bei claude.ai das „Bearer “ mit eintragen) |
| HTTP 403 „Host not allowed“ | `PAPERLESS_MCP_HOST` passt nicht zur aufgerufenen Domain | Variable und Proxy-Route abgleichen |
| HTTP 403 „Origin not allowed“ | Browser-Client mit fremder Herkunft | gewollt; nur bei Bedarf `MCP_ALLOWED_ORIGINS` setzen |
| HTTP 404 „Unknown or expired session“ | Dienst neu gestartet | Client verbindet sich neu |
| Tools liefern leere Listen | Dokumente nicht für `agents` freigegeben | Freigabe nach [rechte.md](rechte.md) |
| Tool-Aufruf scheitert mit 401/403 von Paperless | Token falsch/widerrufen oder Recht fehlt | Token prüfen; fehlendes Recht ist bei Löschen usw. gewollt |
| Container beendet sich sofort | `PAPERLESS_TOKEN` oder `PAPERLESS_URL` leer | Variablen in der `.env` setzen |
