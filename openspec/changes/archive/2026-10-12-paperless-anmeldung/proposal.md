# Proposal

## Why

Lector soll künftig hinter dem öffentlich erreichbaren HTTPS-Proxy unter
`https://lector.nerd-wg.eu` laufen. Bisher ist die Weboberfläche bewusst ohne Anmeldung
gebaut („LAN-only, Einzelnutzer“). Öffentlich erreichbar könnte damit jeder Dokumente
einsehen, Dateien hochladen, Rechnungen als bezahlt markieren oder SevDesk-Exporte
auslösen. Eine eigene Benutzerverwaltung lohnt sich für Lector nicht. Die bestehende
Paperless-Instanz kennt die berechtigten Personen aber bereits und bietet mit
`POST /api/token/` eine offizielle Möglichkeit, Nutzername, Passwort und optional einen
MFA-Code zu prüfen.

## What Changes

- Neuer Schalter `AUTH_MODE` (`none` | `paperless`, Standard `none`). Bei `paperless`
  verlangt die Weboberfläche eine Anmeldung, und `PAPERLESS_URL` wird Pflicht, unabhängig
  von `FEATURE_PAPERLESS_SYNC`.
- Neue Anmeldeseite mit Nutzername, Passwort und optionalem MFA-Code. Lector prüft die
  Angaben gegen `POST {PAPERLESS_URL}/api/token/`, verwirft den zurückgegebenen Token
  sofort und stellt ein eigenes signiertes Session-Cookie aus. Jeder Nutzer, den Paperless
  akzeptiert, ist berechtigt.
- Die Session gilt gleitend 30 Tage. Ein Abmelde-Button beendet sie. Ein Wechsel von
  `LECTOR_SECRET_KEY` meldet alle Sessions ab. Fehlt der Schlüssel, erzeugt Lector ihn beim
  ersten Start und speichert ihn neben der Datenbank.
- Kein Notfallzugang: Ist Paperless nicht erreichbar, schlägt eine neue Anmeldung mit einer
  eindeutigen Meldung fehl. Bestehende Sessions bleiben gültig.
- Schutz aller Routen außer `/healthz`, `/static/*` und der Anmeldung selbst, also auch
  `/fragment/*` und `/events`. Seiten leiten zur Anmeldung um, Fragmente und der
  Ereignisstrom antworten mit `401`, und die Oberfläche wechselt dann selbst zur Anmeldung.
- Härtung für den öffentlichen Betrieb:
  - Session-Cookie mit `HttpOnly`, `SameSite=Strict` und, per `SESSION_COOKIE_SECURE`,
    `Secure`.
  - Prüfung der Herkunft (Origin/Referer) bei allen zustandsändernden Anfragen, weil
    `lector.nerd-wg.eu` und `paperless.nerd-wg.eu` *same-site* sind und `SameSite` allein
    Anfragen von anderen `*.nerd-wg.eu`-Subdomains nicht abwehrt.
  - Drosselung von Fehlversuchen pro Client-IP und pro Nutzername.
  - Einheitliche Fehlermeldung bei falschen Anmeldedaten.
  - Protokollierung von Fehlversuchen ohne Passwort.
  - Security-Header (`Content-Security-Policy` inkl. `frame-ancestors 'none'`,
    `X-Frame-Options`, `Referrer-Policy`, `X-Content-Type-Options`).
  - **BREAKING (gering):** Die automatische FastAPI-Doku `/docs`, `/redoc` und
    `/openapi.json` entfällt in jedem Modus.
- Betrieb hinter Proxy: Doku zu `FORWARDED_ALLOW_IPS`, damit uvicorn `X-Forwarded-Proto`
  und `X-Forwarded-For` des Proxys vertraut, zur Proxy-Einrichtung (SSE ohne Pufferung) und
  zum DNS-Eintrag für `lector.nerd-wg.eu`.
- Die Grundsätze in `PRODUCT.md`, `CLAUDE.md`, `prd/PROGRESS.md` und der
  Feature-Dokumentation werden von „keine Authentifizierung, LAN-only“ auf „Anmeldung über
  Paperless, optional“ umgestellt.

## Capabilities

### New Capabilities

- `web-zugang`: Zugangsschutz der Weboberfläche. Umfasst die Anmeldung über Paperless,
  Session-Lebensdauer und Abmeldung, die geschützten und offenen Routen, das Verhalten
  bei abgelaufener Session, die Drosselung von Fehlversuchen, die Herkunftsprüfung, die
  Security-Header sowie den Betrieb ohne Anmeldung (`AUTH_MODE=none`).

### Modified Capabilities

- `verarbeitungs-historie`: Die Anforderung „Der Dienst verlangt keine Authentifizierung“
  entfällt. Das Zugangsverhalten regelt künftig `web-zugang`, das den bisherigen
  anmeldefreien Betrieb als Modus `AUTH_MODE=none` fortführt. Die Health-Endpunkt-Anforderungen
  bleiben unverändert und gelten ausdrücklich ohne Anmeldung.

## Impact

- **Code:**
  - `app/main.py`: Middleware, Anmelde- und Abmelde-Routen, Abschaltung der
    FastAPI-Doku, Security-Header.
  - Neues Modul `app/auth.py` für die Prüfung gegen Paperless, die Drosselung und die
    Herkunftsprüfung.
  - `app/config.py`: neue Variablen und Startvalidierung.
  - `app/paperless.py`: Token-Abruf ohne Dienst-Token.
  - `app/static/app.js`: `401` bei Fragmenten und SSE.
  - `app/templates/`: neues `login.html`, Abmelde-Button in `base.html`.
- **Abhängigkeiten:** `itsdangerous` (signierte Session-Cookies über Starlettes
  `SessionMiddleware`).
- **Konfiguration:** neue ENV `AUTH_MODE`, `LECTOR_SECRET_KEY`, `SESSION_COOKIE_SECURE`
  sowie die dokumentierte uvicorn-Variable `FORWARDED_ALLOW_IPS`. Betroffen sind
  `.env.example`, `docker-compose.example.yml` und `feature-documentation/konfiguration.md`.
- **Tests:**
  - `tests/test_web.py`: Fixtures für beide Modi, Paperless-Token-Endpunkt gemockt.
  - `tests/test_config.py`: neue Variablen und Validierung.
  - `tests/test_app_js.py`: Umleitung zur Anmeldung bei `401`.
  - `tests/test_compose_files.py`, sofern sich die Compose-Datei ändert.
- **Betrieb:** DNS-Eintrag `lector.nerd-wg.eu`, Proxy-Host mit TLS, Weiterleitung auf
  `lector:8001` mit ungepuffertem SSE und `FORWARDED_ALLOW_IPS` passend zum Proxy-Netz.
- **Bestehende Installationen:** Mit dem Standard `AUTH_MODE=none` ändert sich nur der
  Wegfall von `/docs`, `/redoc` und `/openapi.json` sowie die neuen Security-Header.
