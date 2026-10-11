# Tasks

## 1. Konfiguration und Abhängigkeiten

- [x] 1.1 `itsdangerous` in `pyproject.toml` aufnehmen und `uv.lock` aktualisieren. Prüfen: `uv sync` läuft durch, und `python -c "import itsdangerous"` gelingt.
- [x] 1.2 `Settings` um `auth_mode` (`Literal["none","paperless"]`, Standard `none`), `lector_secret_key` und `session_cookie_secure` erweitern (D9). Prüfen: Tests in `tests/test_config.py` decken Standardwerte und das Parsen aus der ENV ab.
- [x] 1.3 `validate_settings()` ergänzen: Bei `AUTH_MODE=paperless` ist leeres `PAPERLESS_URL` eine Beanstandung (unabhängig von `FEATURE_PAPERLESS_SYNC`). Ein unbekannter Wert von `AUTH_MODE` erscheint gemeinsam mit anderen Beanstandungen. Prüfen: Tests für beide Fälle und für die Kombination mit einer weiteren Beanstandung.
- [x] 1.4 Startwarnung im Log, wenn `AUTH_MODE=paperless` gesetzt ist und `FORWARDED_ALLOW_IPS` fehlt. Prüfen: Ein Test mit `caplog` bestätigt die Warnung, und der Start wird nicht abgelehnt.
- [x] 1.5 Sitzungsgeheimnis laden bzw. erzeugen (D2): ENV, sonst `<DB-Verzeichnis>/session.key` mit Rechten `0600`; nur bei `AUTH_MODE=paperless`. Prüfen: Tests für „ENV gewinnt“, „Datei wird erzeugt und beim zweiten Start wiederverwendet“, „im Modus `none` entsteht keine Datei“.

## 2. Prüfung gegen Paperless

- [x] 2.1 `obtain_token()` in `app/paperless.py` mit dem Enum `LoginResult` (`OK`, `MFA_REQUIRED`, `INVALID`, `UNAVAILABLE`) gemäß der Tabelle in D4 umsetzen. Eigener `httpx.AsyncClient` ohne `Authorization`-Header, Timeout 10 s, Token wird nicht zurückgegeben. Prüfen: Tests mit `httpx.MockTransport` für 200, 400 (MFA fehlt), 400 (falsch), 5xx, ConnectError und Timeout.
- [ ] 2.2 MFA-Antwort von Paperless verifizieren (Open Question): Der Nutzer führt einen Anmeldeversuch gegen `https://paperless.nerd-wg.eu/api/token/` mit einem MFA-Konto ohne `code` und mit falschem `code` aus. Den Antwort-Body als Testfixture übernehmen und die Erkennung in `obtain_token()` daran anpassen. Prüfen: Der Test aus 2.1 nutzt die echte Antwort.

## 3. Zugangsschicht

- [x] 3.1 `LoginThrottle` in `app/auth.py` (D6): Gleitfenster 5 Fehlversuche in 15 Minuten je IP und je Nutzername (kleingeschrieben), Obergrenze der Schlüssel, Rücksetzen nach Erfolg. Prüfen: Unit-Tests mit injizierter Uhr für Sperre je IP, Sperre je Nutzer, Ablauf des Fensters, Reset nach Erfolg und Kappung der Schlüsselzahl.
- [x] 3.2 Herkunftsprüfung (D5) als Funktion in `app/auth.py`: `Origin`, ersatzweise `Referer`, gegen Schema und Host der Anfrage; fehlen beide, wird abgelehnt. Prüfen: Unit-Tests für die eigene Herkunft, eine Schwester-Subdomain (`https://paperless.nerd-wg.eu`), fremdes Schema, nur `Referer` und keinen Header.
- [x] 3.3 Zugangs-Middleware (D3) in `app/auth.py`: offene Pfade, Herkunftsprüfung für Nicht-GET, Sitzungsprüfung, `401` für `/fragment/*`, `/events`, `/auth/status` und Nicht-HTML-Anfragen, sonst `303` auf `/login?next=…` (bei POST ohne `next`). Prüfen: Tests in `tests/test_web.py` für jeden Zweig.
- [x] 3.4 In `app/main.py` nur bei `AUTH_MODE=paperless` `SessionMiddleware` (30 Tage, `same_site="strict"`, `https_only` aus der Konfiguration) und die Zugangs-Middleware in der richtigen Reihenfolge einhängen. Prüfen: Im Modus `none` laufen alle bestehenden Tests in `tests/test_web.py` unverändert grün. Im Modus `paperless` liefert `/` ohne Cookie `303`.
- [x] 3.5 Routen `GET /login`, `POST /login`, `POST /logout`, `GET /auth/status` umsetzen: Drosselung vor dem Paperless-Aufruf, Meldungen je `LoginResult`, Prüfung von `next` (nur ein einzelnes führendes `/`), Weiterleitung, wenn man schon angemeldet ist, und Protokollierung von Fehlversuchen und Sperren mit IP und Nutzername, ohne Passwort. Prüfen: Tests für Erfolg mit `next`, fremdes `next` (`//evil`, `https://evil`), falsches Passwort, MFA nötig, Paperless nicht erreichbar (zählt nicht als Fehlversuch), Sperre nach 5 Fehlversuchen, Abmelden und dass das Passwort nicht in `caplog` auftaucht.
- [x] 3.6 Sitzungsverhalten absichern. Prüfen: Tests zeigen, dass eine angemeldete Antwort ein erneuertes `Set-Cookie` trägt (gleitende Laufzeit), ein manipuliertes Cookie wie „keine Sitzung“ behandelt wird, ein Cookie nach Wechsel des Geheimnisses ungültig ist und `Secure` nur bei `SESSION_COOKIE_SECURE=true` gesetzt wird.
- [x] 3.7 Test-Fixture `auth_client` in `tests/test_web.py` (Modus `paperless`, Paperless-Token-Endpunkt gemockt, angemeldet) ergänzen. Prüfen: Damit funktionieren ein Formular-POST mit passendem `Origin` sowie `/healthz` und `/static/app.css` ohne Sitzung, und ein POST mit `Origin: https://paperless.nerd-wg.eu` wird abgelehnt.

## 4. Härtung

- [x] 4.1 `FastAPI(..., docs_url=None, redoc_url=None, openapi_url=None)`. Prüfen: Ein Test liefert `404` für `/docs`, `/redoc` und `/openapi.json` in beiden Modi.
- [x] 4.2 Middleware für die Schutz-Header (D7) in jedem Modus; bereits gesetzte Header der Antwort haben Vorrang. Die Vorschau-Route liefert `frame-ancestors 'self'` und `X-Frame-Options: SAMEORIGIN`. Prüfen: Tests prüfen die Header auf `/`, ein Fragment, `/events` und die abweichenden Header auf `/invoices/{id}/preview`.

## 5. Oberfläche

- [x] 5.1 `app/templates/login.html` mit Nutzername, Passwort, optionalem MFA-Code, `next` und Meldungsbereich, gestaltet nach `DESIGN.md` und `feature-documentation/ui-texte.md`, plus Hinweis bei HTTP-Aufruf mit `SESSION_COOKIE_SECURE=true`. Prüfen: Ein Test rendert jede Meldung, und die Seite funktioniert unter der CSP ohne Konsolenfehler (manuell im Browser).
- [x] 5.2 Nutzername und Abmelde-Button (Formular-POST) in `base.html`, nur im Modus `paperless`. Prüfen: Ein Test zeigt den Button im Modus `paperless`; im Modus `none` fehlt er.
- [x] 5.3 `app/static/app.js`: Bei `401` auf `fetch` zur Anmeldung mit `next` umleiten. Bei `EventSource.onerror` per `/auth/status` prüfen und bei `401` ebenfalls umleiten. Prüfen: Ein Test in `tests/test_app_js.py` deckt beide Pfade ab.
- [ ] 5.4 Manuelle Browserprüfung im Modus `paperless` mit Schutz-Headern: Dashboard mit Live-Update, Detailansicht, Upload, Rechnungen inkl. PDF-Vorschau und GiroCode, Empfänger inkl. Batch-Lauf, Abmelden, abgelaufene Sitzung (Cookie löschen) während eine Seite offen ist. Prüfen: Alles funktioniert, und die Konsole zeigt keine CSP-Verstöße.

## 6. Betrieb und Dokumentation

- [x] 6.1 `.env.example` und `docker-compose.example.yml` um `AUTH_MODE`, `LECTOR_SECRET_KEY`, `SESSION_COOKIE_SECURE` und `FORWARDED_ALLOW_IPS` mit Erläuterung ergänzen, inklusive Warnung zu `AUTH_MODE=none` bei öffentlichem Betrieb und zu `FORWARDED_ALLOW_IPS=*`. Prüfen: `tests/test_compose_files.py` ist grün.
- [x] 6.2 Neue Feature-Doku `feature-documentation/web-zugang.md`: Ablauf, Modi, Sitzung, Drosselung, Herkunftsprüfung, Header, Proxy-Einrichtung (Host, TLS, SSE ungepuffert, `FORWARDED_ALLOW_IPS`), Abmelden aller Sitzungen durch Schlüsselwechsel. `konfiguration.md`, `web-ui-sse.md`, `datei-upload.md` und `README.md` dort aktualisieren, wo sie „keine Authentifizierung“ behaupten. Prüfen: `grep -ri "keine Authentifizierung" feature-documentation README.md` findet nur noch zutreffende Aussagen.
- [x] 6.3 `PRODUCT.md` und `CLAUDE.md` (Abschnitte „Keine Authentifizierung“ und Datei-Upload) auf „Anmeldung über Paperless, optional über `AUTH_MODE`“ umstellen. In `prd/PROGRESS.md` einen Abschnitt zum Feature mit Stand und Abweichungen ergänzen. Prüfen: Die Dateien sind entsprechend geändert, und keine Stelle widerspricht mehr dem neuen Verhalten.
- [x] 6.4 Gesamte Testsuite und Linting ausführen. Prüfen: `uv run pytest` und `uv run ruff check .` sind grün.
- [ ] 6.5 Deployment gemäß Migrationsplan im Design: DNS `lector.nerd-wg.eu`, Proxy-Host mit TLS und ungepuffertem SSE, ENV `AUTH_MODE=paperless`, `SESSION_COOKIE_SECURE=true`, `FORWARDED_ALLOW_IPS` passend zum Proxy. Prüfen: Anmeldung über `https://lector.nerd-wg.eu` gelingt, nach fünf Fehlversuchen greift die Sperre, das Log zeigt die echte Client-IP, und `/healthz` antwortet ohne Anmeldung.

## 7. Nachträge aus dem Security-Review

- [x] 7.1 Befunde aus dem Security-Review beheben: Drosselung gegen parallele Anfragen (Versuch vor dem Paperless-Aufruf reservieren, höchstens ein laufender Versuch je Nutzername), falscher MFA-Code zählt als Fehlversuch, engere MFA-Erkennung, Startwarnung auch bei leerem bzw. `*` in `FORWARDED_ALLOW_IPS`, Content-Type-Filter und engere CSP der Rechnungsvorschau, IPv6-/64-Normalisierung und Verdrängung nach letzter Aktivität in der Drosselung, keine Redirects in `obtain_token()`. Prüfen: Je Befund belegt ein Test das korrigierte Verhalten, und `uv run pytest -q` ist grün.
- [x] 7.2 Serverseitige Sitzungsliste (D10): Tabelle `web_sessions`, Cookie trägt nur `sid`, Prüfung auf Existenz sowie 30 Tage seit letzter Nutzung und 90 Tage seit Anmeldung, gedrosseltes Schreiben von `last_seen_at`, neue `sid` bei jeder Anmeldung, Abmelden löscht nur die eigene Zeile, Aufräumen abgelaufener Zeilen. Prüfen: Tests decken ab, dass eine kopierte Sitzung nach dem Abmelden ungültig ist, ein zweites Gerät angemeldet bleibt, die 90-Tage-Grenze greift, eine mitgebrachte `sid` beim Anmelden nicht übernommen wird und ein Neustart die Sitzung erhält.
- [x] 7.3 Dokumentation zu 7.1 und 7.2 nachziehen: `feature-documentation/web-zugang.md`, `datenhaltung.md` (neue Tabelle), `.env.example`/Compose-Kommentare zu `FORWARDED_ALLOW_IPS` (Proxy muss `X-Forwarded-For` ersetzen) und `prd/PROGRESS.md`. Prüfen: Die Doku beschreibt das tatsächliche Verhalten, und es gibt keine Aussage mehr zu einem zustandslosen Cookie.
