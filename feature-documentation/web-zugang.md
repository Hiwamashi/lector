# Web-Zugang — Anmeldung und Zugangsschutz

**Module:** `app/auth.py` (Drosselung, Herkunftsprüfung, Sitzungs-Middleware, Zugangsprüfung),
`app/main.py` (Routen `/login`, `/logout`, `/auth/status`, App-Konfiguration, Security-Header),
`app/config.py` (`auth_mode`, `lector_secret_key`, `session_cookie_secure`, `load_session_secret`,
`warn_auth_proxy_config`), `app/paperless.py` (`obtain_token`, `LoginResult`),
`app/templates/login.html`, `app/templates/base.html`, `app/static/app.js`

## Zweck

Der Dienst kann in zwei Zugangsmodi betrieben werden:

- **`AUTH_MODE=none`** (Standard): Weboberfläche vollständig offen, wie bisheriger LAN-Betrieb. Alle Routen sind ohne Anmeldung erreichbar.
- **`AUTH_MODE=paperless`**: Weboberfläche erfordert Anmeldung über ein gültiges Paperless-Konto. Ermöglicht öffentlichen Betrieb hinter einem HTTPS-Proxy.

Die Anmeldung selbst wird gegen die Paperless-REST-API (`POST {PAPERLESS_URL}/api/token/`) geprüft. Lector speichert den von Paperless zurückgegebenen Token **nicht**; stattdessen wird eine eigene, signierte Sitzung (Cookie `lector_session`) erzeugt.

## Anmeldungsablauf

1. **Anfrage ohne Sitzung** auf einer geschützten Seite (z. B. `/`) → Umleitung auf `/login?next=<pfad>` (HTTP 303).
2. **Anmeldeseite** (`/login`): Formulareingaben Nutzername, Passwort, optionaler MFA-Code.
3. **`POST /login`**:
   - **Drosselung prüfen:** Sind von dieser IP oder für diesen Nutzernamen bereits ≥5 Fehlversuche in den letzten 15 Minuten protokolliert? → Anfrage abweisen, ohne Paperless zu befragen.
   - **Herkunftsprüfung:** Der `Origin`- oder `Referer`-Header muss auf die eigene Seite zeigen (Schutz vor Schwester-Subdomains bei `same-site`-Cookies).
   - **Paperless-Abfrage:** Anfrage an `POST {PAPERLESS_URL}/api/token/` mit Nutzername, Passwort und optional MFA-Code.
   - **Fehlerbehandlung nach `LoginResult`:**
     - `OK`: Neue Sitzung erzeugen (Cookie signieren, neue `sid`), Fehlversuch-Zähler für den Nutzernamen zurücksetzen, Weiterleitung auf `next` (oder Startseite).
     - `MFA_REQUIRED`: Meldung „MFA-Code erforderlich" auf der Anmeldeseite, **als Fehlversuch gezählt** (sonst wäre es ein kostenloses Orakel, ob ein Passwort stimmt).
     - `INVALID`: Meldung „Anmeldung fehlgeschlagen" (keine Details zum Grund), Fehlversuch gezählt.
     - `UNAVAILABLE`: Meldung „Paperless ist nicht erreichbar", **kein** Fehlversuch gezählt (bestehende Sitzungen bleiben gültig).
4. **`POST /logout`**: Sitzungs-Cookie leeren (HTTP 303 zur Anmeldeseite).

## Sitzung (Session)

**Server-seitig** (Tabelle `web_sessions`): Das signierte Cookie trägt nur die Sitzungs-ID (`sid`), die tatsächliche Sitzung lebt in der Datenbank.

- **Merkmal:** Signiertes Cookie namens `lector_session`, Inhalt `{"sid": "<token>"}` (base64-JSON). Der Nutzername und Zeitstempel liegen serverseitig in der Tabelle `web_sessions`.
- **Gültigkeitsprüfung:** Eine Anfrage mit Cookie ist gültig, wenn:
  1. Die Signatur passt und höchstens 30 Tage alt ist (Cookie-Signierung, unabhängig von DB-Zustand).
  2. Die `sid` in der Tabelle `web_sessions` existiert.
  3. `last_seen_at` höchstens 30 Tage zurückliegt (**gleitende Laufzeit:** jede Nutzung erneuert sie).
  4. `created_at` höchstens 90 Tage zurückliegt (**absolute Grenze:** auch bei Nutzung längstens 90 Tage gültig).
  
  Fehlt einer dieser Punkte, ist die Sitzung ungültig.

- **Lebensdauer:** 
  - **Gleitend:** 30 Tage seit letzter Nutzung (Cookie wird bei jeder angemeldeten Antwort mit frischem Zeitstempel neu signiert).
  - **Absolut:** 90 Tage seit der Anmeldung (Höchstdauer, auch bei Nutzung).
  
- **Signierung:** `itsdangerous.TimestampSigner(secret)`, `secret` ist entweder:
  - **ENV `LECTOR_SECRET_KEY`** (wenn gesetzt) — über die Umgebung konfiguriert.
  - **Datei `<DB_PATH-Verzeichnis>/session.key`** (wenn ENV leer) — von Lector beim ersten Start erzeugt (Rechte `0600`), beim Neustart wiederverwendet (überdauert Container-Neustarts, da `/data` ein Volume ist).

- **Cookie-Attribute:**
  - `HttpOnly`: Nicht von JavaScript lesbar.
  - `SameSite=Strict`: Nicht an Anfragen von fremden Seiten mitgesendet (auch nicht an same-site Schwester-Subdomains — weitere Sicherung unter „Herkunftsprüfung").
  - `Path=/`: Für alle Routen gültig.
  - `Secure`: Nur wenn `SESSION_COOKIE_SECURE=true` (Betrieb über HTTPS hinter Proxy).

- **Abmelden einer Sitzung:** `POST /logout` löscht die Zeile mit dieser `sid` aus `web_sessions`. Andere Sitzungen derselben Person (von anderen Geräten) bleiben gültig und funktionieren weiter.

- **Kopierte Cookies:** Ein mit `Set-Cookie` übernommenes und an einem anderen Gerät genutztes Cookie trägt dieselbe `sid` — ist diese Sitzung nach dem Abmelden gelöscht, funktioniert die Kopie nicht mehr.

- **Neue `sid` bei jeder Anmeldung:** Eine vom Client mitgebrachte `sid` wird **nie** übernommen (Schutz vor Session Fixation). Bei erfolgreichem Login wird immer eine neue `sid` vergeben.

**Abmelden aller Sitzungen:** Schlüssel wechseln (ENV `LECTOR_SECRET_KEY` umschreiben oder Datei `session.key` löschen und Dienst neu starten) oder alle Zeilen aus der Tabelle `web_sessions` löschen. Alle ausstehenden Cookies werden beim nächsten Aufruf abgelehnt.

## Drosselung (Rate-Limiting)

**Klasse `LoginThrottle`** (`app/auth.py`) verhindert Brute-Force-Angriffe in-memory (kein Netzwerk, kein Speicher).

- **Fenster:** 15 Minuten (gleitend), 5 Fehlversuche (oder laufende Versuche).
- **Zweifach gezählt:** pro Client-IP **und** pro Nutzername (kleingeschrieben). Eine Anfrage blockiert, wenn **einer** der beiden Zähler das Limit überschreitet.
- **Parallele Versuche:** `try_begin()` reserviert einen Versuch **vor** dem Paperless-Aufruf; erst nach dessen Abschluss wird `finish()` aufgerufen. Damit zählen reservierte Versuche wie Fehlversuche — sonst ließe sich die Sperre mit parallelen Anfragen umgehen. Pro Nutzername darf höchstens ein Versuch gleichzeitig laufen.
- **Was zählt als Fehlversuch:**
  - `LoginResult.INVALID` (Passwort falsch, falscher MFA-Code).
  - `LoginResult.MFA_REQUIRED` (Code vergessen).
  
  **Nicht gezählt:**
  - `LoginResult.OK` (setzt den Nutzernamen-Zähler zurück).
  - `LoginResult.UNAVAILABLE` (Paperless nicht erreichbar).
  
- **IP-Normalisierung:** IPv4-gemappte IPv6-Adressen werden auf ihre IPv4-Form normalisiert; reine IPv6-Adressen auf ihr `/64`-Präfix (typisches Subnet für einen Angreifer). Das verhindert, dass ein einziger Angreifer mit rotierenden IPs aus einem großen IPv6-Block alle anderen aussperrt.
- **Speicherverwaltung:** Obergrenze der gespeicherten Keys pro Zähler auf 10.000. Bei Überschreitung wird der älteste, nicht aktiv gesperrte Schlüssel entfernt (aktiv gesperrte bleiben bevorzugt).
- **Neustart-Verhalten:** Speicher liegt nur im RAM; ein Neustart setzt alle Zähler zurück. Ein Angreifer kann den Dienst nicht neu starten.
- **Abhängigkeit von uvicorn-Config:** Die Client-IP (`request.client.host`) ist nur korrekt, wenn uvicorn dem Proxy vertraut (`FORWARDED_ALLOW_IPS`). Ist die Variable falsch oder nicht gesetzt, sieht Lector für alle Anfragen dieselbe (Proxy-)IP, sperrt also alle Nutzer, wenn einer angegriffen wird. Darum wird ein Warnlog beim Start ausgegeben, wenn `AUTH_MODE=paperless` gesetzt ist und `FORWARDED_ALLOW_IPS` fehlt oder `*` ist (siehe `warn_auth_proxy_config()` in `app/config.py`). Mit `FORWARDED_ALLOW_IPS=*` muss der Proxy die `X-Forwarded-For` **ersetzen** (nicht anhängen), sonst kann ein Angreifer im LAN die Quell-IP fälschen.

**Protokollierung:** Jeder Fehlversuch und jede Sperre wird mit Zeitpunkt, IP und Nutzername geloggt, **ohne Passwort oder MFA-Code**.

## Herkunftsprüfung (CSRF-Schutz)

Alle zustandsändernden Anfragen (POST, PUT, DELETE) werden geprüft, ob ihre `Origin`- oder `Referer`-Header auf die eigene Seite zeigen. Diese Prüfung erfolgt **nur bei `AUTH_MODE=paperless`**; im Modus `none` gibt es nichts zu erschleichen.

**Warum nötig trotz `SameSite=Strict`:** Das Cookie wird zwar nicht an andere Sites mitgesendet — aber bei same-site Subdomains (`lector.nerd-wg.eu` und `paperless.nerd-wg.eu`) genügt `SameSite=Strict` nicht. Eine XSS-Lücke oder ein hochgeladener HTML-Inhalt auf einer Schwester-Subdomain könnte sonst von dort aus eine Aktion in Lector auslösen. Daher wird zusätzlich die Herkunft geprüft.

**Logik (Funktion `origin_allowed()` in `app/auth.py`):**

- `GET`/`HEAD`/`OPTIONS`: Immer erlaubt (sicher und nötig für CORS-Preflight).
- Übrige Methoden:
  - `Origin` vorhanden: Muss exakt `{scheme}://{host}` der eigenen Seite entsprechen.
  - `Origin` fehlt, `Referer` vorhanden: Dessen Schema und Netzwerk (`scheme://host`) müssen passen.
  - Beide Header fehlen: `403` (ungültig, verdächtig oder Nicht-Browser).
  - Beide Header sind present but disagree (selten): `Origin` gewinnt.

**Im Browser:** Alle modernen Browser senden `Origin` bei `POST` von Formularen. Ein fehlender Header deutet auf einen Nicht-Browser (Script/Tool) hin, braucht ohnehin eine Sitzung.

## Security-Header

**Middleware `SecurityHeadersMiddleware`** (`app/auth.py`) setzt folgende Header auf jede Antwort:

```
Content-Security-Policy: default-src 'self'; img-src 'self' data:; style-src 'self'; 
  style-src-attr 'unsafe-inline'; frame-ancestors 'none'; base-uri 'self'; 
  form-action 'self'
X-Frame-Options: DENY
Referrer-Policy: same-origin
X-Content-Type-Options: nosniff
```

- **CSP `style-src-attr 'unsafe-inline'`:** Ermöglicht `style=`-Attribute in HTML (z. B. für Fortschrittsbalken), verbietet aber `<style>`-Blöcke und Skripte.
- **`Referrer-Policy: same-origin`:** Der Browser sendet Referer nur bei Anfragen auf die eigene Site (nicht an fremde Ziele). Damit bleibt die URL in der Herkunftsprüfung (D5) vollständig.

**Ausnahme für die Rechnungsvorschau:** `GET /invoices/{id}/preview` liefert eine PDF-Datei und setzt eigene Header:

```
Content-Security-Policy: default-src 'self'; frame-ancestors 'self'
X-Frame-Options: SAMEORIGIN
Content-Type: application/pdf
```

- Die Route prüft den `Accept`-Header und lehnt Anfragen ab, die nicht `application/pdf` akzeptieren (HTTP 415 Unsupported Media Type). Damit lässt sich die URL nicht als HTML oder Script einbetten.
- Die CSP ist enger als auf anderen Routen: `frame-ancestors 'self'` erlaubt die Einbettung per `<object>` nur von der gleichen URL aus.
- Die Middleware überschreibt diese Header nicht, wenn die Antwort sie bereits mitbringt.

**Entfernte `/docs`-Routen:** Unabhängig vom Modus (`AUTH_MODE=none` oder `paperless`) liefert der Dienst keine automatisch erzeugten FastAPI-Dokumentationen unter `/docs`, `/redoc` oder `/openapi.json` aus.

## Verhalten bei abgelaufener Sitzung

- **Seitenanfrage auf HTML** (z. B. `GET /documents/123`): HTTP 303 Umleitung zu `/login?next=/documents/123`.
- **Fragment-Abfrage** (z. B. `GET /fragment/history?status=done`): HTTP 401 mit leerem Body.
- **SSE-Anfrage** (`GET /events`): HTTP 401 mit leerem Body — Die Verbindung wird direkt unterbrochen (kein `event`-Strom).
- **Status-Check** (`GET /auth/status`): Angemeldet = `204 No Content`, abgemeldet = `401`.
- **Anfrage ohne `text/html` im `Accept`-Header** (z. B. Abruf über `curl` oder Tool): HTTP 401.

**Im Frontend** (`app/static/app.js`):

- `fetch`-Aufrufe prüfen auf `401`; bei Erhalt erfolgt `window.location.assign("/login?next=…")`.
- `EventSource` (`/events`) meldet keinen Status-Code; bei `onerror` fragt das Skript höchstens alle 5 Sekunden `GET /auth/status` ab. Antwortet dieser mit `401`, erfolgt die gleiche Umleitung.

**Offene SSE-Ströme nach Abmelden:** Ein Strom bleibt offen, wenn eine Sitzung abgemeldet wird (z. B. auf einem anderen Gerät). Der Browser schließt die Seite nach dem Logout normalerweise ohnehin; ein von einer gestohlenen Kopie offen gehaltener Strom endet spätestens beim nächsten Reconnect, wenn `EventSource` ein fehlgeschlagenes `onerror` erhält (Verbindung unterbrochen, da die Sitzung fehlt).

## Proxy-Einrichtung (öffentlicher Betrieb)

Der Dienst läuft im Container auf Port `8001`. Zur öffentlichen Erreichung über `lector.nerd-wg.eu` wird ein TLS-terminierender Reverse Proxy davor geschaltet (z. B. nginx, Caddy, Traefik).

### DNS & Host-Header

- **DNS-Eintrag:** `lector.nerd-wg.eu` → Proxy-IP.
- **Proxy-Ziel:** `http://lector:8001` (container-interner DNS-Name im Docker-Netz).
- **Host-Header durchreichen:** Der Proxy MUSS den `Host`-Header unverändert als `lector.nerd-wg.eu` weitergeben. Lector nutzt ihn für die Herkunftsprüfung (D5).

### TLS & X-Forwarded-Header

- **TLS endet am Proxy,** nicht im Container (Zertifikat dort, privater Schlüssel dort).
- **Proxy setzt Header:**
  - `X-Forwarded-Proto: https` — Lector erfährt, dass die äußere Verbindung HTTPS ist.
  - `X-Forwarded-For: <echte-client-ip>` — Lector erfährt die Quell-IP des Clients.

- **uvicorn vertraut diesen Headern:** Nur wenn `FORWARDED_ALLOW_IPS` auf die Proxy-IP (oder deren Subnetz) gesetzt ist. Sonst ignoriert uvicorn sie, und:
  - `request.url.scheme` bleibt `http` statt `https` (Cookie `Secure` wird nicht gesendet, wenn `SESSION_COOKIE_SECURE=true`; Login funktioniert stumm nicht).
  - `request.client.host` bleibt die Proxy-IP (Drosselung sperrt alle Nutzer gemeinsam).

- **`X-Forwarded-For` richtig setzen:** Der Proxy darf den Header **ersetzen** (nicht anhängen). Anhängen ließe nur multiple Proxy-Layer zu (z. B. CDN + eigener Proxy), führt aber hier dazu, dass ein Angreifer im LAN mehrere IP-Adressen anhängen kann und die Drosselung umgeht. Mit `nginx` z. B.:
  ```
  proxy_set_header X-Forwarded-For $remote_addr;
  ```
  (nicht `$proxy_add_x_forwarded_for`, das würde den Header anhängen).

**Beispiel FORWARDED_ALLOW_IPS:**

- **Proxy im gleichen Docker-Netz** (z. B. `nginx` auf `172.17.0.2`): `FORWARDED_ALLOW_IPS=172.17.0.2` oder Subnetz `FORWARDED_ALLOW_IPS=172.17.0.0/16`.
- **Proxy auf eigenem Host** (nicht in Compose, aber erreichbar): `FORWARDED_ALLOW_IPS=<Proxy-Hostadresse>`.
- **Ohne Proxy / nur LAN:** Nicht setzen (leer lassen).
- **Wildcard `FORWARDED_ALLOW_IPS=*`:** Bequem, aber **nur akzeptabel, wenn Port `8001` nicht am Host veröffentlicht ist** (keine direkte Erreichung von außen). Mit `*` vertraut uvicorn jedem, der sich verbindet — steht Port 8001 offen, kann jeder Anfragen fälschen und die Drosselung umgehen. Der Proxy **muss** dann `X-Forwarded-For` ersetzen (siehe oben).

### SSE-Pufferung

Der SSE-Stream `/events` soll ungepuffert fließen (Live-Updates ohne Verzögerung). Manche Proxies (z. B. nginx) puffern Text-Streams standardmäßig. Das muss explizit deaktiviert werden:

**nginx-Beispiel:**
```
location / {
  proxy_pass http://lector:8001;
  proxy_buffering off;       # SSE ungepuffert
  proxy_http_version 1.1;
  proxy_set_header Connection "upgrade";
  # ... weitere Headers (Host, X-Forwarded-*, etc.)
}
```

## Prüfung gegen Paperless (`obtain_token`)

Die Funktion `obtain_token(base_url, username, password, code)` in `app/paperless.py` prüft Anmeldedaten gegen `POST {PAPERLESS_URL}/api/token/` und liefert ein `LoginResult`-Enum:

| Paperless-Antwort | `LoginResult` | Zählt als Fehlversuch |
|---|---|---|
| `200` mit `token` | `OK` | nein (setzt Zähler zurück) |
| `400` ohne Code, Body deutet auf fehlenden MFA-Code hin | `MFA_REQUIRED` | ja |
| `400`/`401`/`403` sonst, auch bei abgelehntem MFA-Code | `INVALID` | ja |
| Netzwerkfehler, Timeout, `5xx`, `3xx` (Redirects) | `UNAVAILABLE` | nein |

**Wichtige Details:**

- **Keine Redirects:** Der `httpx.AsyncClient` wird mit `follow_redirects=False` erstellt. Redirects (z. B. `307 Temporary Redirect`) gelten als `UNAVAILABLE` und **werden nicht verfolgt** — sonst würde uvicorn das Passwort an ein fremdes Ziel senden.
- **Token wird nicht zurückgegeben:** Lector speichert den Token nicht und loggt ihn niemals. Nur das Ergebnis zählt.
- **Timeout:** 10 Sekunden. Zu lange Antwortzeiten gelten als `UNAVAILABLE`.
- **MFA-Erkennung:** Heuristik im `400`-Body: Ist kein Code mitgeschickt worden und der Body enthält „code" als DRF-Feldname oder erwähnt eines der Keywords `mfa`, `two-factor`, `2fa`, `one-time`, `totp`, wird es als `MFA_REQUIRED` klassifiziert. Ein falscher Code ergibt `INVALID`. Das bloße Wort „code" im Text genügt nicht.

## Bekannte Grenzen

### Kein Notfallzugang

Ist Paperless bei einer Anmeldung nicht erreichbar (z. B. der PostgreSQL-Host ist down), kann sich niemand neu anmelden. Bestehende Sessions bleiben gültig. Das ist bewusst so entschieden: Die 30-Tage-Gleitsitzung macht den Fall selten, und ein „Root-Mode ohne Paperlicht"-Zugang hätte Sicherheitslücken.

### Gesperrter Paperless-Nutzer

Ein Nutzer, der in Paperless deaktiviert oder gelöscht wird, bleibt bis zu 30 Tage angemeldet (wenn seine Session noch gültig ist). Um alle Sitzungen sofort zu beenden, wechselt der Betreiber das Sitzungsgeheimnis (`LECTOR_SECRET_KEY` oder Löschen von `session.key`).

### MFA-Erkennung (heuristisch)

Die Unterscheidung zwischen „MFA-Code fehlt" (→ Seite zeigt „MFA erforderlich") und „MFA-Code ist falsch" (→ „Anmeldung fehlgeschlagen") basiert auf dem Antworttext von Paperless bei `400`-Fehlern. Ändert Paperless die Fehlermeldung, fällt der Fall auf `INVALID` zurück — die Seite zeigt nur „Anmeldung fehlgeschlagen", und der Nutzer sieht nicht explizit „MFA nötig". Das MFA-Feld ist aber immer sichtbar, daher kein großer Fehler.

Im Betrieb gegen `https://paperless.nerd-wg.eu` bestätigt (2026-10-12): Die Anmeldung mit MFA-Code funktioniert. Den genauen Antworttext von Paperless gibt es nicht als Testfixture; die Tests in `tests/test_paperless_login.py` arbeiten weiter mit nachgebildeten Antworten.

## Code-Orte

| Datei | Rolle |
|---|---|
| `app/auth.py` | `LoginThrottle` (Drosselung mit `try_begin()`/`finish()`), `origin_allowed()` (Herkunftsprüfung), `AuthMiddleware` (Sitzung + Zugangsschutz), `_load_session()` (Prüfung gegen `web_sessions`), `SecurityHeadersMiddleware` (Header), `SESSION_COOKIE`, `SESSION_MAX_AGE`, `SECURITY_HEADERS`, Hilfsfunktionen. |
| `app/config.py` | `Settings.auth_mode`, `.lector_secret_key`, `.session_cookie_secure`, `load_session_secret()`, `warn_auth_proxy_config()` (Warnung bei fehlendem/leerem/`*` `FORWARDED_ALLOW_IPS`). |
| `app/main.py` | Routes `GET /login`, `POST /login`, `POST /logout`, `GET /auth/status`. Middleware-Einhängung, App-Flags `docs_url=None`. Lifespan: `purge_web_sessions()` beim Start. |
| `app/paperless.py` | Funktion `obtain_token()` (schlanker HTTP-Client, keine Redirects, `LoginResult`-Enum). |
| `app/db.py` | Tabelle `web_sessions` (Schema). |
| `app/repository.py` | `create_web_session()`, `get_web_session()`, `touch_web_session()`, `delete_web_session()`, `purge_web_sessions()` (Repository-Schicht). |
| `app/retention.py` | `purge_web_sessions()` — Aufräum-Wrapper. |
| `app/worker.py` | Stündliche `_retention_loop()` für `purge_web_sessions()`. |
| `app/templates/login.html` | Anmeldeseite (Formulare, Meldungen, HTTP-Warnung). |
| `app/templates/base.html` | Anmeldestatus + Abmelde-Button (nur bei `AUTH_MODE=paperless`). |
| `app/static/app.js` | Umleitung zu `/login` bei `401`, Status-Check bei SSE-Fehler. |

## Abhängigkeiten

- `itsdangerous` (Signierung des Session-Cookies, part of requirements in `pyproject.toml`).
