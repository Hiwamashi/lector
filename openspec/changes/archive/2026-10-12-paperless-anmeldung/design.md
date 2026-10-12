# Design

## Context

Motivation und Umfang stehen in `proposal.md`, das Verhalten in `specs/web-zugang/spec.md`.

Ausgangslage im Code:

- **`app/main.py`:**
  - Erzeugt die App mit `FastAPI(title="Lector", lifespan=lifespan)`, also mit offener
    Schnittstellenbeschreibung unter `/docs`, `/redoc` und `/openapi.json`.
  - Die Routen hängen direkt an `app`, ohne Router und ohne Middleware.
  - Zustandsändernde Routen sind klassische Formular-`POST`s (`/upload`,
    `/documents/{id}/release|discard`, `/invoices/{id}/giro|export|paid`,
    `/empfaenger/...`).
- **`app/static/app.js`:**
  - `loadFragment()` ruft `/fragment/*` per `fetch` ab und wirft bei `!r.ok` einen Fehler.
  - Live-Aktualisierungen kommen über `new EventSource("/events")`. `onerror` setzt nur
    einen Statushinweis.
- **`app/paperless.py`:**
  - `PaperlessClient` verlangt `base_url` **und** Dienst-Token und setzt den
    `Authorization`-Header fest.
  - Für eine Anmeldung ohne Dienst-Token passt die Klasse nicht.
- **Startprüfung:** `app/config.py` sammelt in `validate_settings()` alle Beanstandungen
  schalterabhängig, `get_settings_and_problems()` ergänzt Typfehler.
- **Container:** `Dockerfile:55` startet `uvicorn ... --host 0.0.0.0 --port 8001`. uvicorn
  wertet `X-Forwarded-*` standardmäßig nur von `127.0.0.1` aus.
- **Templates:** keine Inline-Skripte, aber Inline-`style`-Attribute für Fortschrittsbalken
  (`partials/history_rows.html`, `detail_body.html`, `batch_status.html`).
- **Paperless-Anmelde-API:**
  - `OPTIONS https://paperless.nerd-wg.eu/api/token/` bestätigt `POST` mit `username`,
    `password` und optional `code` („MFA Code“).
  - Erfolg liefert `200 {"token": ...}`, abgelehnte Angaben liefern `400`.
  - Wie sich „Code fehlt“ von „Code falsch“ in der Antwort unterscheidet, ist noch zu
    verifizieren (siehe Open Questions).

## Goals / Non-Goals

**Goals:**

- Zugangsschutz als eine zentrale Schicht, nicht als Prüfung in jeder einzelnen Route, damit
  künftige Routen automatisch geschützt sind.
- Möglichst wenig neue Persistenz: die Datei mit dem Sitzungsgeheimnis und eine kleine
  Sitzungstabelle in der bestehenden SQLite-Datenbank (D10). Ein Neustart verliert nichts.
- `AUTH_MODE=none` verhält sich bis auf die Schutz-Header und die entfernte
  Schnittstellenbeschreibung exakt wie heute. Bestehende Tests laufen ohne Anpassung.

**Non-Goals:**

- Single Sign-on mit der Paperless-Browsersitzung (Cookie-Weitergabe) oder OIDC.
- Rollen und Rechte in Lector. Auch Paperless-Aktionen erfolgen weiter mit dem Dienst-Token
  `PAPERLESS_TOKEN` und nicht im Namen der angemeldeten Person.
- Eine Oberfläche zum Verwalten fremder Sitzungen (z. B. „alle Geräte abmelden“ oder
  Sitzungen anderer Personen beenden). Die Sitzungstabelle aus D10 würde das später
  ermöglichen.
- Proxy-, TLS- und DNS-Konfiguration als Code. Sie wird nur dokumentiert.

## Decisions

### D1 — Signiertes Cookie über eine schlanke eigene ASGI-Sitzungs-Middleware

Die Sitzung ist ein mit `itsdangerous.TimestampSigner` signiertes Cookie `lector_session`. Es
enthält nur `{"user": "<paperless-username>"}` (base64-JSON).

- `max_age=30 Tage`, `SameSite=Strict`, `HttpOnly`, `Path=/`, `Secure` nach
  `SESSION_COOKIE_SECURE`.
- **Gleitende Laufzeit:** Jede Antwort auf eine Anfrage mit nicht leerer Sitzung signiert das
  Cookie mit frischem Zeitstempel und `Max-Age` neu. Jede Nutzung startet die 30-Tage-Frist
  also neu. Eine geleerte Sitzung löscht das Cookie.
- Die Sitzung liegt wie bei Starlette in `scope["session"]`, damit funktioniert
  `request.session`.

*Abweichung in der Umsetzung:* Ursprünglich war Starlettes `SessionMiddleware` vorgesehen.
Deren Secret muss aber schon beim Einhängen feststehen. In Lector liegt es erst im
Lifespan vor (Settings und `session.key`, D2). Die eigene Middleware ist immer eingehängt,
liest Settings und Secret pro Anfrage aus `app.state` und reicht im Modus `none` unverändert
durch.

*Alternativen:*

- Eigene HMAC-Signatur mit der Standardbibliothek: spart eine Abhängigkeit, aber
  Kryptografie-Kleincode selbst zu schreiben und zu testen lohnt sich nicht.
- Rein zustandsloses Cookie: zunächst so umgesetzt, im Security-Review aber verworfen. Ein
  kopiertes Cookie bliebe nach dem Abmelden gültig und würde sich gleitend verlängern (siehe
  D10).

### D2 — Sitzungsgeheimnis: ENV oder persistierte Datei

- `LECTOR_SECRET_KEY` ist gesetzt: Dieser Wert wird verwendet.
- Sonst liest Lector `<DB_PATH-Verzeichnis>/session.key`. Fehlt die Datei, erzeugt er sie
  beim Start mit `secrets.token_urlsafe(48)`, Dateirechte `0600`.
- Eine Datei neben der DB überlebt Container-Neustarts, weil `/data` ohnehin ein Volume ist.
  Wechselt der Wert, sind alle Cookies ungültig, wie in der Spec gefordert.
- Das Erzeugen geschieht nur bei `AUTH_MODE=paperless`. Im Modus `none` bleibt das
  Datenverzeichnis unberührt.

*Alternativen:*

- Schlüssel pro Prozessstart zufällig: Jeder Neustart würde alle abmelden.
- Pflicht-ENV: ein zusätzliches Geheimnis, das der Betreiber pflegen muss, ohne
  Sicherheitsgewinn gegenüber einer `0600`-Datei im Volume.

### D3 — Zugangsprüfung als ASGI-Middleware in `app/auth.py`

Eine Middleware, eingehängt nur bei `AUTH_MODE=paperless`, prüft vor jeder Route:

1. **Offene Pfade:** `/healthz`, `/static/*`, `GET|POST /login`. Diese laufen durch.
2. **Herkunftsprüfung** für jede Methode außer `GET`/`HEAD`/`OPTIONS` (siehe D5).
3. **Sitzung** mit `request.session.get("user")`. Fehlt sie:
   - Pfade unter `/fragment/` und `/events`, sowie Anfragen mit `Accept`, das kein
     `text/html` bevorzugt: `401` mit leerem Body.
   - Sonst `303` auf `/login?next=<pfad+query>`.

Die Middleware liegt **innerhalb** der `SessionMiddleware`, also in der Reihenfolge der
Registrierung *nach* ihr, damit `request.session` bereits befüllt ist.

Für Formular-`POST`s ohne Sitzung (Sitzung zwischen Seitenaufruf und Absenden abgelaufen)
gilt `303` auf `/login`, ohne `next`. Das Formular wird nicht wiederholt. Eine Aktion soll
nach dem Anmelden bewusst erneut ausgelöst werden.

*Alternative:* FastAPI-Dependency pro Route. Verworfen, weil jede künftige Route sie
vergessen kann. Die Middleware schützt standardmäßig („deny by default“).

### D4 — Prüfung gegen Paperless: eigene schlanke Funktion statt `PaperlessClient`

In `app/paperless.py` kommt eine freie async-Funktion
`obtain_token(base_url, username, password, code) -> LoginResult` hinzu. Sie öffnet einen
eigenen kurzlebigen `httpx.AsyncClient` ohne `Authorization`-Header und mit kurzem Timeout
(10 s). Den Token aus der Antwort reicht sie **nicht** heraus. `LoginResult` ist ein Enum:

| Paperless-Antwort | Ergebnis | Zählt als Fehlversuch |
|---|---|---|
| `200` mit `token` | `OK` | nein (setzt den Zähler für den Nutzernamen zurück) |
| `400` ohne mitgeschickten Code, Body weist auf fehlenden MFA-Code hin | `MFA_REQUIRED` | ja |
| `400`/`401`/`403` sonst, auch bei abgelehntem MFA-Code | `INVALID` | ja |
| Netzwerkfehler, Timeout, `5xx`, `3xx` (Redirects werden nicht verfolgt) | `UNAVAILABLE` | nein |

*Nachtrag aus dem Security-Review:*
- `MFA_REQUIRED` zählt als Fehlversuch. Sonst wäre es ein kostenloses Orakel dafür, dass ein
  Passwort stimmt.
- Ein falscher Code ergibt `INVALID`, sonst ließe sich der TOTP-Code ungebremst durchprobieren.
- Redirects werden nicht verfolgt, weil httpx bei 307/308 den Body samt Passwort an das
  Weiterleitungsziel sendet.
- Die Drosselung reserviert jeden Versuch vor dem Paperless-Aufruf und lässt höchstens einen
  gleichzeitigen Versuch je Nutzername zu.

Ohne Sonderzweig in `PaperlessClient` bleibt dessen Pflicht-Token-Invariante unangetastet.

Für die URL wird `PAPERLESS_URL` (die container-interne Adresse) genutzt, nicht
`PAPERLESS_PUBLIC_URL`: Der Aufruf erfolgt serverseitig, und im Stack ist das
`http://webserver:8000`, also ohne Umweg über den öffentlichen Proxy und ohne dessen eigene
Drosselung.

*Alternative:* Session-Login über das Paperless-Webformular (`/accounts/login/`). Verworfen,
weil das CSRF-Token-Handling und HTML-Parsing erfordert und keine stabile API ist.

### D5 — Herkunftsprüfung über `Origin`, ersatzweise `Referer`

Als eigene Herkunft gilt `request.url.scheme + "://" + Host-Header`. Hinter dem Proxy liefert
uvicorn dank `FORWARDED_ALLOW_IPS` das korrekte Schema `https`, und der Proxy reicht `Host`
unverändert durch (`lector.nerd-wg.eu`). Regel für zustandsändernde Anfragen:

- `Origin` vorhanden: muss exakt der eigenen Herkunft entsprechen.
- `Origin` fehlt, `Referer` vorhanden: dessen Schema und Host müssen passen.
- Beide fehlen: ablehnen (`403`).

Alle unterstützten Browser senden `Origin` bei `POST` (auch bei `same-origin`-Formularen).
Ein fehlender Header deutet also auf einen Nicht-Browser hin, und der braucht ohnehin eine
Sitzung.

*Warum zusätzlich zu `SameSite=Strict`:* `lector.nerd-wg.eu` und `paperless.nerd-wg.eu`
sind *same-site*. `SameSite` schützt nur vor *cross-site*. Eine XSS-Lücke oder ein Upload
mit HTML-Inhalt auf einer Schwester-Subdomain könnte sonst Aktionen in Lector auslösen.

*Alternative:* Synchronizer-CSRF-Token in jedem Formular. Verworfen, weil die Formulare über
viele Templates und Fragmente verteilt sind und `app.js` Formulare teils per `fetch`
abschickt. Die Header-Prüfung ist zentral und deckt dasselbe Bedrohungsmodell ab.

Die Prüfung greift **nur** im Modus `paperless`. Im Modus `none` gibt es nichts zu
erschleichen, was nicht ohnehin offen wäre.

### D6 — Drosselung: Gleitfenster im Speicher

`LoginThrottle` in `app/auth.py` hält zwei `dict[str, deque[float]]` mit Zeitstempeln von
Fehlversuchen: einen je Client-IP, einen je kleingeschriebenem Nutzernamen.

- Vor dem Paperless-Aufruf: Hat einer der beiden Schlüssel mindestens 5 Einträge jünger als
  15 Minuten, wird sofort abgewiesen, und es gibt einen Logeintrag.
- Ältere Einträge werden beim Zugriff verworfen. Eine einfache Obergrenze für die Zahl der
  Schlüssel (z. B. 10 000, älteste zuerst raus) verhindert Speicherwachstum durch
  rotierende Nutzernamen.
- Ein Neustart setzt alles zurück. Das ist akzeptiert, weil ein Angreifer den Dienst nicht
  neu starten kann.

Die Client-IP ist `request.client.host`. Das stimmt nur, wenn uvicorn dem Proxy vertraut
(`FORWARDED_ALLOW_IPS`). Sonst stünde dort immer die Proxy-IP, und ein einziger Angreifer
würde alle aussperren. Deshalb ist die Variable Teil der Betriebsdoku und wird beim Start
geprüft (D9).

*Alternativen:*

- Persistente Zähler in SQLite: unnötig, siehe oben.
- Drosselung am Proxy: je nach Proxy möglich und gern zusätzlich. Lector soll aber auch ohne
  Proxy-Unterstützung sicher sein.

### D7 — Schutz-Header und keine Schnittstellenbeschreibung

- Die App wird mit `docs_url=None, redoc_url=None, openapi_url=None` erzeugt, in jedem Modus.
- Eine kleine Middleware setzt auf jede Antwort:
  - `Content-Security-Policy: default-src 'self'; img-src 'self' data:; style-src 'self';
    style-src-attr 'unsafe-inline'; frame-ancestors 'none'; base-uri 'self';
    form-action 'self'`
  - `X-Frame-Options: DENY` (für ältere Browser)
  - `Referrer-Policy: same-origin`
  - `X-Content-Type-Options: nosniff`
- `style-src-attr 'unsafe-inline'` ist nötig für die Breitenangaben der Fortschrittsbalken.
  Es erlaubt nur `style=`-Attribute, keine `<style>`-Blöcke und kein Skript.
- `Referrer-Policy: same-origin` sorgt dafür, dass der `Referer` für D5 bei eigenen Anfragen
  vollständig bleibt.
- Kein `Strict-Transport-Security`. Das gehört an den TLS-terminierenden Proxy, sonst
  sperrt es lokale HTTP-Zugriffe aus.

**Ausnahme Rechnungsvorschau:** `invoice_detail_body.html` bettet
`/invoices/{id}/preview` per `<object type="application/pdf">` ein. Die Route setzt heute
bewusst `X-Frame-Options: SAMEORIGIN` (`app/main.py:775`). Für diese Antwort darf die
Middleware die Header nicht überschreiben. Sie setzt dort
`frame-ancestors 'self'` und `X-Frame-Options: SAMEORIGIN`, sonst bleibt die Vorschau leer.
Umgesetzt wird das so: Die Middleware setzt Header nur, wenn die Antwort sie nicht schon
mitbringt, und die Vorschau-Route liefert ihre eigene CSP mit.

Für die Antworten der SSE- und Vorschau-Routen (`/events`, `/invoices/{id}/preview`) ist zu
prüfen, dass `nosniff` keinen Medientyp bricht. Beide setzen ihren `Content-Type` explizit.

### D8 — Oberfläche: `401` führt zur Anmeldeseite

- **`app.js`:** In `loadFragment()` und bei allen weiteren `fetch`-Aufrufen löst `401`
  `window.location.assign("/login?next=" + encodeURIComponent(location.pathname + location.search))`
  aus, statt den Fehlerzweig zu nehmen.
- **`EventSource`:** Er meldet keinen Statuscode. Bei `onerror` fragt das Skript deshalb
  (höchstens alle 5 s) den Statusendpunkt `GET /auth/status` ab. Liefert der `401`, folgt
  dieselbe Umleitung, sonst (`204`, `404` im Modus `none`, Netzwerkfehler) bleibt es beim
  bisherigen Hinweis „Live-Verbindung unterbrochen“. Der Endpunkt (`204` angemeldet, `401`
  sonst) wird von der Middleware wie jeder andere geschützte Pfad
  behandelt.
- **Anmeldeseite:** `login.html` erbt von `base.html`, mit Feldern Nutzername, Passwort und
  MFA-Code (immer sichtbar, als optional beschriftet), dazu verstecktem `next`.
  - Meldungen: „Anmeldung fehlgeschlagen“, „Bitte MFA-Code eingeben“, „Paperless ist
    nicht erreichbar“, „Zu viele Fehlversuche, bitte in einigen Minuten erneut versuchen“.
  - Bei Seitenaufruf über `http` und gesetztem `SESSION_COOKIE_SECURE` erscheint ein Hinweis,
    weil die Anmeldung sonst stumm scheitert.
- **`base.html`:** Im Modus `paperless` zeigt die Navigation rechts den Nutzernamen und einen
  Abmelde-Button, als Formular-`POST /logout`, damit kein `GET` abmeldet.
- **`next`:** Nur Werte, die mit genau einem `/` beginnen (nicht `//`, kein Schema), werden
  übernommen, sonst gilt `/`.

### D9 — Konfiguration und Startprüfung

Neue Felder in `Settings`:

- `auth_mode` als `Literal["none", "paperless"]`, Standard `none`. Ein Typfehler wird über
  den bestehenden Mechanismus in `get_settings_and_problems()` zur Beanstandung.
- `lector_secret_key` als `str`, Standard leer.
- `session_cookie_secure` als `bool`, Standard `False`.

`validate_settings()` ergänzt:

- Bei `auth_mode=paperless` ist leeres `PAPERLESS_URL` eine Beanstandung, unabhängig von
  `FEATURE_PAPERLESS_SYNC`.
- Bei `auth_mode=paperless` gibt es eine **Warnung im Log** (keine Beanstandung), wenn
  `FORWARDED_ALLOW_IPS` nicht gesetzt ist. Lector kann nicht wissen, ob ein Proxy davor
  steht. Eine Warnung macht den Fehlbetrieb aus D6 aber sichtbar.

`FORWARDED_ALLOW_IPS` liest uvicorn selbst aus der Umgebung. Lector führt die Variable nur in
der Doku, in `.env.example` und im Compose-Beispiel.

### D10 — Serverseitige Sitzungsliste in SQLite

Nachgetragen nach dem Security-Review: Ein rein zustandsloses Cookie bleibt nach dem Abmelden
als Kopie gültig. Deshalb gilt jetzt:

- Neue Tabelle `web_sessions` in `app/db.py` (`CREATE TABLE IF NOT EXISTS`, also ohne
  Eingriff in bestehende Tabellen) mit den Spalten `id` (Primärschlüssel), `username`,
  `created_at`, `last_seen_at`.
  - Als `id` dient `secrets.token_urlsafe(32)`, ausschließlich serverseitig erzeugt.
- Das signierte Cookie (D1) enthält nur noch `{"sid": "<id>"}`. Die Middleware prüft
  1. die Signatur und die 30 Tage seit der letzten Signierung,
  2. dass die `sid` in der Tabelle existiert,
  3. dass `last_seen_at` höchstens 30 Tage und `created_at` höchstens 90 Tage zurückliegt.

  Fehlt einer der Punkte, gilt die Anfrage als ohne Sitzung.
- **Gleitend:** `last_seen_at` wird höchstens einmal pro Minute je Sitzung geschrieben, damit
  SSE und Fragment-Polling die Datenbank nicht ständig beschreiben. Das Cookie wird wie
  bisher bei jeder Antwort neu signiert. Läuft die Sitzung nach der 90-Tage-Grenze ab,
  ergibt sich kein Cookie mehr.
- **Anmelden:** Lector legt eine neue Zeile an und vergibt eine neue `sid`. Eine vom Client
  mitgebrachte `sid` wird nie übernommen (Schutz vor Session Fixation).
- **Abmelden:** Die Zeile mit dieser `sid` wird gelöscht. Andere Sitzungen derselben Person
  bleiben bestehen.
- **Aufräumen:** Abgelaufene Zeilen entfernt der bestehende stündliche Retention-Lauf des Workers sowie
  ein Aufruf beim Start.
- Offene SSE-Ströme prüfen die Sitzung nur beim Verbindungsaufbau. Nach dem Abmelden
  schließt der Browser die Seite ohnehin. Ein von einer gestohlenen Kopie offen gehaltener
  Strom endet spätestens beim nächsten Reconnect. Diese Einschränkung ist akzeptiert.
- Der DB-Zugriff ist synchron über das bestehende `Repository`. Die Lese- und Schreibzugriffe
  sind Primärschlüssel-Lookups und damit schnell genug für den Event-Loop. Bestehende
  Muster im Repository (Locking) sind einzuhalten.

*Alternative:* ein Zeitstempel „ungültig vor“ je Nutzer, sodass Abmelden alle Geräte
abmeldet. Verworfen nach Entscheidung des Nutzers: Abmelden soll nur die eigene Sitzung
beenden.

## Risks / Trade-offs

- **[Gleitende Laufzeit hängt an einem Starlette-Detail]** → Ein Test prüft, dass eine
  Antwort auf eine angemeldete Anfrage ein neues `Set-Cookie` trägt. Ändert Starlette das
  Verhalten, schlägt der Test an, und eine eigene Neu-Signatur in der Auth-Middleware wird
  nötig.
- **[Falsches `FORWARDED_ALLOW_IPS`]** Dann sehen alle Anfragen gleich aus, und die
  Drosselung sperrt alle aus, oder `Secure` und die Herkunftsprüfung scheitern wegen
  `http`. → Doku mit konkretem Wert für den Compose-Stack, Startwarnung (D9) und der
  Hinweis auf der Anmeldeseite (D8).
  - `FORWARDED_ALLOW_IPS=*` ist bequem, aber nur akzeptabel, wenn Port 8001 nicht am Host
    veröffentlicht ist. Sonst kann jeder im LAN die IP fälschen. Die Doku nennt das
    ausdrücklich.
- **[Kein Notfallzugang]** Bei einem Paperless-Ausfall ist keine neue Anmeldung möglich. →
  Bewusst so entschieden. Die 30-Tage-Gleitsitzung macht den Fall selten, und bestehende
  Sitzungen funktionieren weiter.
- **[Gesperrter Paperless-Nutzer bleibt bis zu 30 Tage angemeldet]** → In der Doku steht,
  dass ein Wechsel von `LECTOR_SECRET_KEY` (bzw. das Löschen von `session.key`) alle
  Sitzungen beendet.
- **[`AUTH_MODE=none` bei öffentlichem Betrieb]** Lector kann nicht erkennen, ob er öffentlich
  erreichbar ist. → Deutliche Warnung in der Doku und in `.env.example`.
- **[MFA-Unterscheidung beruht auf dem Antworttext von Paperless]** Ändert Paperless die
  Meldung, fällt der Fall auf `INVALID` zurück. Das zählt dann als Fehlversuch, und die
  Person sieht nur „Anmeldung fehlgeschlagen“. → Akzeptabel, weil das MFA-Feld ohnehin
  immer sichtbar ist. Ein Test mit aufgezeichneter Antwort hält das Verhalten fest.
- **[Strenge CSP bricht etwas Übersehenes]** → Die Tests der Oberfläche laufen mit den
  Headern. Manuelle Prüfung von Dashboard, Detailansicht, Rechnungen, Empfängern und Upload
  im Browser gehört in die Tasks.
- **[SSE durch Proxy gepuffert]** → In die Proxy-Doku kommt ein Hinweis auf
  `proxy_buffering off` bzw. das Äquivalent. Das bestehende Polling in `app.js` fängt den
  Batch-Fortschritt ohnehin ab.

## Migration Plan

1. Deployen mit Standard `AUTH_MODE=none`. Verhalten wie bisher, nur ohne `/docs` und mit
   Schutz-Headern. Kurz prüfen, dass die Oberfläche funktioniert.
2. DNS-Eintrag `lector.nerd-wg.eu` und Proxy-Host mit TLS anlegen. Ziel ist `lector:8001`,
   SSE ungepuffert, `Host` durchreichen.
3. In der Lector-Umgebung setzen: `AUTH_MODE=paperless`, `SESSION_COOKIE_SECURE=true`,
   `FORWARDED_ALLOW_IPS=<Proxy-IP bzw. Docker-Netz>`. `PAPERLESS_URL` ist bereits gesetzt.
   Den Container neu starten.
4. Anmeldung über `https://lector.nerd-wg.eu` testen, einmal mit und, falls vorhanden, einmal
   ohne MFA-Konto. Ein falsches Passwort fünfmal eingeben und die Sperre prüfen. Im Log die
   echte Client-IP kontrollieren.
5. Erst danach Port 8001 am Host schließen, falls er bisher veröffentlicht war.

**Rollback:** `AUTH_MODE=none` setzen und neu starten. Es gibt keine Datenmigration. Die Datei
`session.key` kann liegen bleiben.

## Open Questions

- Wie genau unterscheidet sich die `400`-Antwort von `POST /api/token/` bei fehlendem
  gegenüber falschem MFA-Code? Das ist mit echten Zugangsdaten gegen
  `paperless.nerd-wg.eu` zu klären. Es ändert nur die Erkennung in `obtain_token()`, nicht
  Specs, Ansatz oder Tasks.
- Welcher konkrete Wert für `FORWARDED_ALLOW_IPS` passt? Das hängt davon ab, ob der Proxy im
  selben Docker-Netz läuft oder auf einem anderen Host. Das wird beim Deployment ermittelt.
