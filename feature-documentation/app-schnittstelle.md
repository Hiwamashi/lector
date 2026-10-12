# App-Schnittstelle — JSON-REST-API

**Module:** `app/api.py` (Routen, Fehlerformat, Ausgabemodelle), `app/auth.py` (Zugangsschlüssel, Bearer-Token-Weiche), `app/main.py` (gemeinsamer Kern: `authenticate`, `accept_uploads`, `UploadOutcome`)

## Zweck und Abgrenzung

Die REST-API (`/api/v1/`) liefert dieselben Daten und Aktionen wie die Weboberfläche, maschinenlesbar als JSON. Die Schnittstelle ist ausdrücklich **nicht für Browser anderer Herkunft** gedacht (kein CORS). Sie dient der iOS-App über `Authorization: Bearer`-Token und läuft im Container auf demselben uvicorn-Prozess wie die HTML-Routen.

Anmeldung, Upload und Entscheidungen (Freigabe/Verwerfen) teilen ihren Kern mit den HTML-Routen statt ihn zu duplizieren. Das Modul `app/api.py` ist eine dünne Schicht: kein neuer Geschäftscode, keine Schemaänderung, keine neuen Abhängigkeiten.

## Endpunkte

### Selbstauskunft (offen)

```
GET /api/info
```

Ohne Anmeldung erreichbar. Antwort (200):

```json
{
  "service": "lector",
  "api_version": 1,
  "auth_mode": "paperless" oder "none"
}
```

Die Route liegt bewusst nicht unter `/api/v1/`. Nur so kann die App die Schnittstellenversion erfragen, bevor sie weiß, welche sie sprechen muss.

### Anmeldung

#### Login (offen, nur im Modus `paperless`)

```
POST /api/v1/login
Content-Type: application/json
```

Request:

```json
{
  "username": "string",
  "password": "string",
  "code": "string oder null"
}
```

Erfolg (200):

```json
{
  "token": "iTdDzNTIqcEcEr3...",
  "username": "sascha"
}
```

Der `token` ist ein signierter Zugangsschlüssel (siehe unten), der statt eines Cookies in jeden nachfolgenden Request als `Authorization: Bearer <token>` mitgesendet wird.

**Fehler:**

| HTTP | `error.code` | Grund |
|---|---|---|
| 401 | `invalid_credentials` | Nutzername oder Passwort falsch |
| 401 | `mfa_required` | MFA-Code erforderlich (fehlerhaft oder fehlt) |
| 429 | `throttled` | Zu viele Fehlversuche von dieser IP oder diesem Nutzernamen (5 in 15 min) — bitte später erneut versuchen |
| 503 | `paperless_unavailable` | Paperless ist nicht erreichbar (Timeout, 5xx, Netzwerkfehler) |
| 404 | `not_found` | Modus `AUTH_MODE=none`: Anmelden und Abmelden gibt es dort nicht (alle übrigen Routen sind ohne Anmeldung nutzbar) |

Die Anmeldung verlangt `Content-Type: application/json`. Ein HTML-Formular kann diesen Typ nicht ohne CORS-Preflight senden → Schutz vor untergeschobenen Anmeldungen (Login-CSRF).

#### Logout

```
POST /api/v1/logout
Authorization: Bearer <token>
```

Antwort: 204 No Content

Beendet genau diese Sitzung; andere Sitzungen derselben Person (z. B. im Browser) bleiben bestehen. Nur im Modus `paperless` vorhanden (404 im Modus `none`).

### Vorgänge (Dokumenten)

#### Liste

```
GET /api/v1/documents?status=<Zustand>&q=<Text>&period=<Zeitraum>&limit=<Zahl>&offset=<Zahl>
Authorization: Bearer <token>
```

Antwort (200):

```json
{
  "documents": [
    {
      "id": 42,
      "original_filename": "scan_2026-10-12.pdf",
      "status": "done",
      "doc_type": "pdf",
      "total_pages": 5,
      "processed_pages": 5,
      "attempt_count": 1,
      "next_retry_at": null,
      "error_message": null,
      "page_limit_approved": false,
      "created_at": "2026-10-12T10:30:45Z",
      "started_at": "2026-10-12T10:30:50Z",
      "finished_at": "2026-10-12T10:31:15Z"
    }
  ],
  "counts": {
    "pending": 0,
    "processing": 0,
    "blocked": 2,
    "done": 42,
    "skipped_erechnung": 5,
    "failed": 1
  },
  "limit": 200,
  "offset": 0
}
```

**Parameter:**

- `status`: Zustand zum Filtern (`pending`, `processing`, `blocked`, `done`, `skipped_erechnung`, `failed`). Unbekannte Werte werden ignoriert. Standard: alle.
- `q`: Freitext-Suche im Dateinamen. Standard: keine.
- `period`: Zeitraum zum Filtern (`today`, `week`, `month`, `all`). Unbekannte Werte werden ignoriert. Standard: `all`.
- `limit`: Einträge pro Anfrage (1–200, Standard 200). Wird auf diesen Bereich begrenzt, größere Werte nicht abgelehnt.
- `offset`: Startposition (ab 0). Wird auf Werte ≥ 0 begrenzt.

Die Antwort nennt die tatsächlich verwendeten `limit` und `offset`. `counts` gilt ungefiltert für den gesamten Bestand (alle Zustände, alle Zeiträume).

**Fehler:**

| HTTP | `error.code` | Grund |
|---|---|---|
| 401 | `not_authenticated` | Sitzung fehlerhaft oder abgelaufen |
| 422 | `invalid_request` | Parameter ungültig (z. B. `limit=abc`) |

#### Detail

```
GET /api/v1/documents/{id}
Authorization: Bearer <token>
```

Antwort (200):

```json
{
  "document": {
    "id": 42,
    "original_filename": "scan_2026-10-12.pdf",
    "status": "done",
    "doc_type": "pdf",
    "total_pages": 5,
    "processed_pages": 5,
    "attempt_count": 1,
    "next_retry_at": null,
    "error_message": null,
    "page_limit_approved": false,
    "created_at": "2026-10-12T10:30:45Z",
    "started_at": "2026-10-12T10:30:50Z",
    "finished_at": "2026-10-12T10:31:15Z"
  },
  "events": [
    {
      "id": 100,
      "timestamp": "2026-10-12T10:30:50Z",
      "event_type": "detected",
      "message": "scan_2026-10-12.pdf erkannt"
    },
    {
      "id": 101,
      "timestamp": "2026-10-12T10:30:55Z",
      "event_type": "ocr_chunk",
      "message": "Seiten 1–5 verarbeitet"
    }
  ],
  "page_limit": 1000,
  "retry_max": 3
}
```

**Fehler:**

| HTTP | `error.code` | Grund |
|---|---|---|
| 401 | `not_authenticated` | Sitzung fehlerhaft oder abgelaufen |
| 404 | `not_found` | Vorgang existiert nicht oder ID außerhalb von 1…2⁶³−1 |
| 422 | `invalid_request` | ID nicht ganzzahlig |

#### Freigabe

```
POST /api/v1/documents/{id}/release
Authorization: Bearer <token>
```

Gibt einen angehaltenen Vorgang frei (Status wechselt von `blocked` auf `failed`, um den Fehler zu behalten). Das Original wird in `consume` kopiert, der Vorgang wird protokolliert.

Antwort (200): Das aktualisierte Vorgang-Objekt wie `GET /api/v1/documents/{id}`.

**Fehler:**

| HTTP | `error.code` | Grund |
|---|---|---|
| 401 | `not_authenticated` | Sitzung fehlerhaft oder abgelaufen |
| 404 | `not_found` | Vorgang existiert nicht oder ID außerhalb von 1…2⁶³−1 |
| 409 | `not_blocked` | Vorgang ist nicht angehalten (nicht im Zustand `blocked`) |
| 500 | `discard_failed` | Fehler beim Verschieben des Originals (Dateisystem) |
| 422 | `invalid_request` | ID nicht ganzzahlig |

#### Verwerfen

```
POST /api/v1/documents/{id}/discard
Authorization: Bearer <token>
```

Verwirft einen angehaltenen Vorgang (Status wechselt auf `failed`). Das Original wird in den Fehlerordner verschoben, der Vorgang wird protokolliert.

Antwort (200): Das aktualisierte Vorgang-Objekt wie `GET /api/v1/documents/{id}`.

**Fehler:** Dieselben wie bei `/release`.

### Upload

```
POST /api/v1/upload
Authorization: Bearer <token>
Content-Type: multipart/form-data
```

Request: `files`-Feld mit einer oder mehreren Dateien (UploadFile).

Antwort (200):

```json
{
  "results": [
    {
      "filename": "scan_1.pdf",
      "accepted": true,
      "reason": null,
      "stored_as": "scan_1.pdf"
    },
    {
      "filename": "scan_2.txt",
      "accepted": false,
      "reason": "unsupported_format",
      "stored_as": null
    },
    {
      "filename": "../../../etc/passwd",
      "accepted": false,
      "reason": "unusable_name",
      "stored_as": null
    },
    {
      "filename": "scan_3.pdf",
      "accepted": false,
      "reason": "store_failed",
      "stored_as": null
    }
  ]
}
```

Die Antwort ist **immer** 200, auch wenn einzelne Dateien abgewiesen werden. Jedes Ergebnis trägt:

- `filename`: Der Client-Name der Datei (ggf. gekürzt).
- `accepted`: `true`, wenn die Datei im Eingangsordner abgelegt wurde.
- `reason`: Ablehnung­grund, oder `null` wenn `accepted=true`.
  - `unsupported_format`: Die Datei-Endung wird nicht unterstützt (kein PDF, TIFF, JPG, PNG, etc.).
  - `unusable_name`: Der Name besteht nur aus Pfad-Trennzeichen oder Punkten (`.`, `..`).
  - `store_failed`: Fehler beim Speichern (Schreibfehler, Speicherplatz).
- `stored_as`: Der tatsächliche Dateiname im Eingangsordner, oder `null` wenn abgewiesen.

Eine hochgeladene Datei läuft ab sofort durch die bestehende Verarbeitungs-Pipeline (Watch-Folder, Vorverarbeitung, OCR, Sandwich-PDF). Sie erscheint **nicht sofort** im Dashboard; es können bis zu 2 + 6 = 8 Sekunden vergehen, bis die Datei sichtbar wird (Scan-Intervall + Stabilitätsfenster).

**Fehler:**

| HTTP | `error.code` | Grund |
|---|---|---|
| 400 | `no_files` | Keine Datei in der Anfrage |
| 401 | `not_authenticated` | Sitzung fehlerhaft oder abgelaufen |
| 422 | `invalid_request` | Anfrage-Format ungültig (z. B. kein `multipart/form-data`) |

### Ereignisstrom (Server-Sent Events)

```
GET /events
Authorization: Bearer <token>
Accept: text/event-stream
```

Dieser Endpunkt ist **nicht** unter `/api/`. Er sendet Echtzeitaktualisierungen über Server-Sent Events (SSE). Die Schnittstelle kann ihn über den Zugangsschlüssel nutzen wie über das Cookie.

**Datenformat:**

```
data: doc:42
data: inv:37
data: rec:10
data: batch:1
: keepalive
```

Präfixe:
- `doc:<id>`: Ein Vorgang wurde aktualisiert (Status, Fehler, Ereignisse).
- `inv:<id>`: Eine Rechnung wurde synchronisiert (Paperless-Integration).
- `rec:<id>`: Ein Empfänger-Status änderte sich.
- `batch:<id>`: Der Batch-Fortschritt für KI-Empfänger-Vorschläge änderte sich.
- Keepalive (`: keepalive`) alle 15 Sekunden (hält die Verbindung offen).

Die App sollte nach Erhalt einer `doc:`-Nachricht die Vorgang-Details (`GET /api/v1/documents/{id}`) abrufen, um die neuesten Daten zu bekommen.

**Fehler bei Sitzungsablauf:** Die Verbindung wird beendet, wenn die Sitzung abläuft. Der Client erhält kein Fehler-Event, sondern einen `onerror` der EventSource.

## Zugangsschlüssel (Authentifizierung über Bearer-Token)

Ein Zugangsschlüssel ist eine signierte Variante der Sitzungskennung (`sid`). Im Gegensatz zum Cookie trägt er keine Session-Laufzeit — über Gültigkeit entscheidet allein die Zeile in der Tabelle `web_sessions`.

### Aufbau

```
token = TimestampSigner(session_secret, salt="lector-app-token").sign(sid)
```

Der Schlüssel wird beim Login (`POST /api/v1/login`) erzeugt und ist ein BASE64-kodierter String.

### Gültigkeit

- **Signatur:** Mit dem Sitzungsgeheimnis (`LECTOR_SECRET_KEY` oder Datei `session.key`) signiert. Ein falsches Geheimnis invalidiert alle Schlüssel.
- **Datenbank-Zeile:** Die `sid` muss in der Tabelle `web_sessions` existieren.
- **Leerlauf:** höchstens 30 Tage seit letzter Nutzung. Mit jedem Request wird `last_seen_at` fortgeschrieben (gedrosselt auf einmal pro Minute).
- **Höchstdauer:** höchstens 90 Tage seit der Anmeldung, auch bei Nutzung.

**Wichtig:** Der Schlüssel wird nie erneuert. Die App sendet denselben Schlüssel mit jedem Request.

### Verwendung

In jeden Request den Header mitgeben:

```
Authorization: Bearer <token>
```

Die Middleware (`AuthMiddleware` in `app/auth.py`) prüft den Header:

1. Ist `Authorization: Bearer` vorhanden, wird die Sitzung allein daraus geladen.
2. Cookie und Formulare werden ignoriert.
3. Es gibt keinen Rückfall auf ein Cookie, auch wenn der Schlüssel ungültig ist.
4. Herkunftsprüfung entfällt (keine CORS, kein Browser-Same-Site-Zugriff möglich).
5. Kein `Set-Cookie` wird gesetzt.

### Abmelden einer Sitzung

`POST /api/v1/logout` löscht die Zeile mit dieser `sid` aus `web_sessions`. Der Schlüssel ist danach ungültig. Andere Sitzungen derselben Person bleiben bestehen.

### Geheimniswechsel

Ein Wechsel des Geheimnisses (ENV `LECTOR_SECRET_KEY` oder Löschen der Datei `session.key` und Neustart) invalidiert alle Schlüssel sofort, wie die Spec verlangt.

## Fehlerformat

Jeder Fehler der Schnittstelle hat die Form:

```json
{
  "error": {
    "code": "code_identifier",
    "message": "Lesbare Meldung auf Deutsch"
  }
}
```

Der `code` ist für die Logik der App da (um auf verschiedene Fehler unterschiedlich zu reagieren). Die `message` ist für die Anzeige an den Nutzer gedacht. Die Meldung ist ein Klartext, kein Fehler-Code.

**Alle möglichen Codes:**

- `invalid_credentials` (401)
- `mfa_required` (401)
- `paperless_unavailable` (503)
- `throttled` (429)
- `not_authenticated` (401)
- `not_found` (404)
- `not_blocked` (409)
- `discard_failed` (500)
- `no_files` (400)
- `invalid_request` (422)

**Validierungsfehler:** Anfragen unter `/api/` mit ungültigen Parametern oder Typen erhalten 422 mit `error.code = "invalid_request"`. Dies ersetzt FastAPIs Standard-Validierungsantwort.

## Sicherheit & Architektur

### Keine Herkunftsprüfung für Bearer-Token

Anfragen mit `Authorization: Bearer` sind von der Herkunftsprüfung ausgenommen. Das ist sicher, weil:

- **Kein CORS:** Der Dienst erteilt keine `Access-Control-Allow-*`-Header.
- **Browser-Einschränkung:** Ein Browser darf einen selbst gesetzten `Authorization`-Header an eine fremde Herkunft nur nach erfolgreichem CORS-Preflight senden. Der Dienst verweigert diesen Preflight.
- **Tool:** Ein Command-Line-Tool (wie `curl`) hat ohnehin keine Herkunft.

### Gemeinsame Drosselung (Rate-Limiting)

Anmeldeversuche über die Schnittstelle und das HTML-Formular teilen sich dieselbe `LoginThrottle`:

- **Fenster:** 15 Minuten (gleitend).
- **Limit:** 5 Fehlversuche pro Client-IP oder pro Nutzername (kleingeschrieben), je nachdem, was zuerst erreicht wird.
- **Was zählt:** `INVALID` (Passwort falsch, MFA-Code falsch), `MFA_REQUIRED`. **Nicht gezählt:** `OK`, `UNAVAILABLE` (Paperless offline).
- **Parallele Versuche:** Werden wie Fehlversuche gezählt. Pro Nutzername läuft höchstens ein Versuch parallel.

Ist ein Versuch reserviert aber die IP oder der Nutzername erreicht das Limit, wird der Versuch abgewiesen, bevor Paperless abgefragt wird.

### Maskierung von NAS-Pfaden in der Ausgabe

Alle Freitexte in der Schnittstellen-Antwort (z. B. `error_message` von Fehlern, Verlaufsmeldungen) werden vor der Rückgabe gefiltert:

- Absolute Pfade unter den konfigurierten Ordnern (Eingang, consume, processed, error, Datenbankverzeichnis) werden durch den bloßen Dateinamen ersetzt.
- Dies dient dem Datenschutz: Die App lernt nicht die Verzeichnisstruktur des NAS kennen.
- Die gespeicherten Werte in der Datenbank bleiben unverändert; die Maskierung erfolgt nur bei der Ausgabe.

**Beispiel:**

- Original in DB: `"Datei /data/lector/processed/scan.pdf konnte nicht gefunden werden"`
- Ausgabe in API: `"Datei scan.pdf konnte nicht gefunden werden"`

### Login-CSRF-Schutz

`POST /api/v1/login` verlangt `Content-Type: application/json`. Ein HTML-Formular kann diesen Content-Type nicht ohne CORS-Preflight senden. So wird verhindert, dass ein Angreifer von einer anderen Website aus heimlich einen Benutzer anmeldet.

## Begrenzungen

### `limit` und `offset` bei Vorgangslisten

- `limit` wird auf 1 bis 200 begrenzt (nicht abgelehnt). Standard: 200.
- `offset` wird auf Werte ≥ 0 begrenzt.
- Kennungen (`id`) außerhalb von 1…2⁶³−1 führen zu 404 (`not_found`), ohne die Datenbank zu fragen (SQLite würde mit OverflowError abbrechen).

### Zeitpunkte

Alle `timestamp`, `created_at`, `started_at`, `finished_at`, `next_retry_at` sind ISO 8601 in UTC mit `Z`-Suffix, z. B. `"2026-10-12T10:30:45Z"`. Die Datenbank speichert UTC ohne Zonenangabe; die Schnittstelle markiert dies explizit.

## Proxy-Einrichtung

Der Ereignisstrom `/events` muss **ungepuffert** fließen. Manche Reverse-Proxies (z. B. nginx) puffern Text-Streams standardmäßig. Das muss deaktiviert werden:

**nginx:**

```
location / {
  proxy_pass http://lector:8001;
  proxy_buffering off;       # SSE ungepuffert
  proxy_http_version 1.1;
  proxy_set_header Connection "upgrade";
  proxy_set_header Host $host;
  proxy_set_header X-Forwarded-Proto $scheme;
  proxy_set_header X-Forwarded-For $remote_addr;  # ersetzen, nicht anhängen
}
```

Der Proxy muss den `Authorization`-Header durchreichen und ihn nicht selbst interpretieren.

## Warnung: Betrieb im Modus `AUTH_MODE=none`

Im Modus `AUTH_MODE=none` (Standard für LAN-Betrieb) sind **auch die Schnittstellen-Routen vollständig offen**:

- `/api/info` antwortet mit `"auth_mode": "none"`.
- `/api/v1/login` und `/api/v1/logout` existieren nicht (404).
- Alle übrigen Routen sind ohne Token erreichbar.

**Niemals öffentlich so betreiben.** Dieser Modus ist nur für private Netzwerke gedacht, in denen alle Nutzer vertraut werden. Für einen öffentlichen Betrieb muss `AUTH_MODE=paperless` gesetzt sein.

## Bekannte Grenzen

### Session-ID im Klartext in der Datenbank

Die `sid` wird in der Tabelle `web_sessions` im Klartext gespeichert. Das ist dieselbe Situation wie beim Cookie-Wert. Ein Abgriff der Datenbank verrät alle aktiven Sitzungen. Eine zufällige, undurchsichtige ID mit Hashing wäre etwas robuster, würde aber eine Migration erzwingen und schützt nicht mehr als die heutigen Cookie-Sitzungen.

### Keine gezielte Geräteabmeldung

Es gibt keine Möglichkeit, einzelne Geräte einer Person aus der Weboberfläche heraus abzumelden. Eine Sitzung ist eine Zeile in `web_sessions` wie jede andere. Um alle Geräte abzumelden, muss das Sitzungsgeheimnis gewechselt werden.

### Keine Erneuerung des Zugangsschlüssels

Der Schlüssel wird nach der Anmeldung nie erneuert. Über Gültigkeit entscheidet allein `web_sessions`. Das ist eine bewusste Vereinfachung: Die App muss keinen Refresh-Ablauf implementieren.

## Code-Orte

| Datei | Rolle |
|---|---|
| `app/api.py` | Router, Endpunkte, Ausgabemodelle (`DocumentOut`, `EventOut`, etc.), Fehlerbehandlung, Pfad-Maskierung. |
| `app/auth.py` | `sign_app_token()` (Schlüssel erzeugen), `load_app_session()` (Schlüssel prüfen), `bearer_token()` (Header parsen), `AuthMiddleware` (Weiche für Bearer-Token, Herkunftsprüfung). |
| `app/main.py` | `authenticate()` (gemeinsamer Anmeldekern für Formular und Schnittstelle), `accept_uploads()` (gemeinsamer Upload-Kern), `UploadOutcome` (Rückmeldung je Datei). |
| `tests/test_api.py` | Tests für alle Endpunkte, Fehlerformat, Zeitangaben, Bearer-Token, Pfad-Maskierung, Upload-Ergebnisse. |

## Abhängigkeiten

- `itsdangerous` (Signierung des Zugangsschlüssels, Teil von `pyproject.toml`).
