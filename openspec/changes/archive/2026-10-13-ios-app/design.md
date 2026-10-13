# Design

## Context

Zur Motivation siehe `proposal.md` (Abschnitt „Why“). Für diesen Entwurf zählt der heutige
Stand:

- **Sitzungen** (`app/auth.py`, Tabelle `web_sessions`):
  - Das Cookie `lector_session` trägt nur die Sitzungskennung `sid`. Sie ist mit
    `itsdangerous.TimestampSigner` signiert, die Signatur hat höchstens 30 Tage Gültigkeit.
  - Mit jeder angemeldeten Antwort wird das Cookie neu signiert. So entsteht die gleitende
    Laufzeit im Browser.
  - Ob eine Sitzung gültig ist, entscheidet die Zeile in `web_sessions`: Sie darf höchstens
    30 Tage ungenutzt und höchstens 90 Tage alt sein (`_load_session`).
- **`AuthMiddleware`**:
  - prüft bei jeder nicht lesenden Anfrage zuerst die Herkunft (`origin_allowed`), danach die
    Sitzung
  - offene Pfade sind `/healthz`, `/login` und `/static/*`
  - `_deny` antwortet bei Fragmenten, `/events`, `/auth/status` und Anfragen, die kein HTML
    erwarten, mit 401, sonst mit 303 auf die Anmeldeseite
- **Anmeldung** (`login_submit` in `app/main.py`): `LoginThrottle.try_begin`, dann
  `obtain_token` (Paperless), dann `throttle.finish` bzw. `record_success`, dann
  `repo.create_web_session`.
- **Daten für das Dashboard:**
  - `repo.list_documents(status, search, since, limit=200, offset)` liefert die neuesten
    Vorgänge zuerst. `repo.status_counts()` gilt ungefiltert für den ganzen Bestand.
  - `get_document` und `list_events` liefern das Detail. Gefiltert wird über `_filters()`;
    ein unbekannter Zustand wird dabei ignoriert.
  - Zeitstempel liegen in der Datenbank als UTC ohne Zonenangabe
    (`%Y-%m-%d %H:%M:%S`).
- **Entscheidungen:** `release_document` und `discard_document` (`app/decisions.py`) liefern
  einen `DecisionResult`: `RELEASED`, `DISCARDED`, `NOT_FOUND`, `NOT_BLOCKED` oder
  `DISCARD_FAILED`.
- **Upload:** `POST /upload` setzt sich aus `sanitize_upload_filename`,
  `detection.is_supported` und `store_upload` (über den Default-Executor) zusammen und
  antwortet mit einer Umleitung samt Rückmeldung in Query-Parametern.
- **Ereignisstrom:** `/events` sendet `data: doc:<document_id>` für Vorgänge (daneben
  `inv:`, `rec:` und `batch:` für die Paperless-Funktionen) und alle 15 Sekunden ein Keepalive.
- **Referenz für die iOS-Seite** ist das Projekt „Smoking Tracker“:
  - XcodeGen mit `project.yml` und gemeinsamer `xcodegen/base.yml`, Team `J3P792SJ75`,
    Präfix `me.krinke`
  - iOS 26, Swift 6 mit strikter Concurrency-Prüfung
  - Netzwerkschicht aus `APIClient`, `AuthSession` und `TokenStore` (Keychain mit
    Zugriffsgruppe)
  - Tests mit Swift Testing und `TransportAttrappe`

## Goals / Non-Goals

**Goals:**

- Die Server-Seite bleibt eine dünne Schicht. Keine neue Fachlogik, keine Schemaänderung,
  keine neue Abhängigkeit. Login, Upload und Entscheidungen teilen ihren Kern mit den
  bestehenden HTML-Routen, statt ihn zu duplizieren.
- Für Anmeldung und Sitzung gibt es genau ein Regelwerk für Browser und App.
- Die iOS-App übernimmt Aufbau, Werkzeuge und Konventionen der Referenz-App, damit Build,
  Signierung und TestFlight ohne neue Einrichtung laufen.

**Non-Goals:**

- Eigene Geräte-Token oder eine Geräteverwaltung in der Weboberfläche. Eine App-Sitzung ist
  eine Zeile in `web_sessions` wie jede andere.
- CORS für die Schnittstelle. Sie ist ausdrücklich nicht für Browser anderer Herkunft gedacht.
- Hintergrund-Uploads (`URLSession` im Hintergrundmodus), Push und Widgets.
- Eine Versionierung, die mehrere Schnittstellenversionen parallel bedient. Es gibt `v1`;
  die Selbstauskunft nennt die Version, damit eine spätere App einen zu alten Server
  erkennt.

## Decisions

### D1: Eigenes Modul `app/api.py` mit `APIRouter`, Pfade unter `/api/`

| Pfad | Zweck | offen |
|---|---|---|
| `GET /api/info` | Selbstauskunft `{service: "lector", api_version: 1, auth_mode}` | ja |
| `POST /api/v1/login` | Anmeldung, liefert `{token, username}` | ja |
| `POST /api/v1/logout` | Sitzung beenden | nein |
| `GET /api/v1/documents?status&q&period&limit&offset` | Liste + `counts` | nein |
| `GET /api/v1/documents/{id}` | Vorgang + `events` (+ `page_limit`, `retry_max`) | nein |
| `POST /api/v1/documents/{id}/release` bzw. `/discard` | Entscheidung, liefert den aktualisierten Vorgang | nein |
| `POST /api/v1/upload` | Multipart-Feld `files`, Rückmeldung je Datei | nein |
| `GET /events` | bestehender Ereignisstrom, unverändert | nein |

Die Selbstauskunft liegt bewusst nicht unter `v1`. Nur so kann die App die Version erfragen,
bevor sie weiß, welche sie sprechen muss. `/events` bekommt keinen eigenen API-Pfad: Der
Stream ist schon maschinenlesbar, und über den Zugangsschlüssel (D3) ist er auch für die App
zugänglich.

*Alternative:* die JSON-Routen in `app/main.py` ergänzen. Verworfen, weil die Datei schon
über 1 200 Zeilen hat. Der Router kapselt außerdem die JSON-Fehlerbehandlung.

### D2: Zugangsschlüssel = signierte `sid` mit eigenem Salt, ohne Altersprüfung der Signatur

Der Schlüssel ist dieselbe Sitzungskennung wie im Cookie. Sie wird mit demselben Geheimnis,
aber mit `salt="lector-app-token"` signiert. Beim Prüfen gelten drei Regeln:

- Die Signatur wird ohne `max_age` geprüft. Über Gültigkeit und Laufzeit entscheidet allein
  die Zeile in `web_sessions`, mit derselben Leerlauf- und Höchstgrenze wie beim Cookie.
- `last_seen_at` wird über dieselbe einminütige Drosselung fortgeschrieben.
- Die App muss den Schlüssel nie erneuern. Das verlangt die Spec.

Gründe:

- **Keine Schemaänderung.** Abmelden, Ablauf und Aufräumen (`purge_web_sessions`)
  funktionieren für App-Sitzungen ohne neuen Code.
- **Ein Wechsel des Geheimnisses macht alle Schlüssel ungültig**, wie die Spec verlangt, weil
  die Signatur dann nicht mehr passt.
- **Durch das eigene Salt sind Cookie-Wert und Schlüssel nicht austauschbar.** Ein
  abgegriffenes Cookie taugt nicht als Header-Schlüssel und umgekehrt.

*Alternative 1:* ein zufälliger, undurchsichtiger Schlüssel, gehasht in einer neuen Spalte.
Er ist etwas robuster, falls die Datenbank ausgelesen wird. Er bringt aber eine Migration
und einen zweiten Prüfweg und schützt dabei nicht mehr als die heutigen Cookie-Sitzungen,
deren `sid` ebenfalls im Klartext in der Datenbank steht.

*Alternative 2:* die Signatur mit `max_age` prüfen und den Schlüssel in jeder Antwort
erneuern, wie beim Cookie. Das würde einen Refresh-Ablauf in der App erzwingen. Verworfen.

### D3: Weiche in `AuthMiddleware` nach `Authorization: Bearer`

Die Middleware wird um eine Weiche erweitert. Trägt eine Anfrage den Header
`Authorization: Bearer …`, gilt:

1. Die Herkunftsprüfung entfällt.
2. Die Sitzung wird allein aus dem Schlüssel geladen. Ein Cookie wird ignoriert, auch wenn
   der Schlüssel ungültig ist; es gibt dann keinen Rückfall auf das Cookie.
3. Es wird kein `Set-Cookie` gesetzt.

Ohne diesen Header bleibt alles wie bisher. Die Ausnahme von der Herkunftsprüfung ist sicher,
weil es keine CORS-Konfiguration gibt. Ein Browser darf einen selbst gesetzten
`Authorization`-Header an eine fremde Herkunft nur nach erfolgreichem Preflight schicken, und
der Dienst erteilt keinen. Ein Test hält das fest: Eine `OPTIONS`-Anfrage bekommt kein
`Access-Control-Allow-*`.

`_OPEN_PATHS` wird um `/api/info` und `/api/v1/login` erweitert. `/api/v1/login` ist auch von
der Herkunftsprüfung ausgenommen, verlangt dafür aber `Content-Type: application/json`. Ein
HTML-Formular kann diesen Typ nicht ohne Preflight senden. So ist eine untergeschobene
Anmeldung (Login-CSRF) ausgeschlossen. `_deny` antwortet für jeden Pfad unter `/api/` mit 401
und dem JSON-Fehler `not_authenticated`, nie mit einer Umleitung.

Im Modus `none` bleibt die Middleware wie heute vollständig durchlässig.
`/api/v1/login` und `/api/v1/logout` antworten dort mit 404, wie `_auth_routes_absent`.

### D4: Gemeinsamer Anmeldekern für Formular und Schnittstelle

Aus `login_submit` wird eine Funktion `authenticate(request, username, password, code)`
herausgelöst. Sie übernimmt Drosselung, `obtain_token`, Protokollierung und
`create_web_session` und liefert `(LoginResult | THROTTLED, sid | None)`. Die HTML-Route und
`POST /api/v1/login` rufen beide diese Funktion auf. Die Fehlversuche teilen sich damit
zwangsläufig eine `LoginThrottle`. Zuordnung zur Antwort der Schnittstelle:

| Ergebnis | HTTP | `error.code` |
|---|---|---|
| OK | 200 | – (`{token, username}`) |
| INVALID | 401 | `invalid_credentials` |
| MFA_REQUIRED | 401 | `mfa_required` |
| UNAVAILABLE | 503 | `paperless_unavailable` |
| gebremst | 429 | `throttled` |

### D5: Einheitliches Fehlerformat

Jeder Fehler der Schnittstelle hat die Form `{"error": {"code": "...", "message": "..."}}`.
Die Meldung ist ein deutscher Klartext für die Anzeige, der Code ist für die Logik da. Feste
Codes:

- `not_authenticated`
- `not_found`
- `not_blocked` (409)
- `discard_failed` (500)
- `no_files` (400)
- `invalid_request` (422; ersetzt FastAPIs Validierungsantwort unter `/api/`)
- dazu die Codes aus D4

### D6: Serialisierung mit Pydantic-Modellen, Zeitangaben als ISO 8601 in UTC

Pydantic-Modelle (`DocumentOut`, `EventOut`, `DocumentListOut`, `DocumentDetailOut`) in
`app/api.py` bilden die Dataclasses aus `app/models.py` ab. `source_path` und `output_path`
werden **nicht** ausgeliefert. Für die App sind sie wertlos, und sie verraten die
Verzeichnisstruktur des NAS. Zeitpunkte liegen in der Datenbank als UTC ohne Zonenangabe.
Sie werden als UTC markiert und mit `Z` ausgegeben. Die App zeigt sie in der Zeitzone des
Geräts an. Das `TZ` des Servers bleibt eine Sache der Weboberfläche.

Die Liste übernimmt `_filters()` unverändert, damit sich Filter in Weboberfläche und App
identisch verhalten. `limit` wird auf 1 bis 200 begrenzt (Standard 200), `offset` auf
Werte ≥ 0.

### D7: Gemeinsamer Upload-Kern

Die Schleife aus `upload()` wird zu
`async def accept_uploads(files, settings) -> list[UploadOutcome]` herausgelöst.
`UploadOutcome` enthält Dateiname, `accepted`, `reason ∈ {unsupported_format,
unusable_name, store_failed}` und `stored_as`. Die HTML-Route baut daraus wie bisher ihre
Query-Parameter. `POST /api/v1/upload` gibt die Liste als JSON zurück, mit Status 200 auch
dann, wenn einzelne Dateien abgewiesen werden. Ohne Datei antwortet sie mit 400 `no_files`.
Die Spec verlangt eine unveränderte Übergabe. Das ist schon heute so, weil `store_upload`
die Bytes nur kopiert. Ein Test vergleicht trotzdem die Hashes.

### D8: Entscheidungen

Die Routen rufen `release_document` bzw. `discard_document` wie die HTML-Routen über
`asyncio.to_thread` auf. Zuordnung: `RELEASED` oder `DISCARDED` ergibt 200 mit dem frisch
gelesenen Vorgang, `NOT_FOUND` ergibt 404, `NOT_BLOCKED` ergibt 409 und `DISCARD_FAILED`
ergibt 500 mit `discard_failed`.

### D9: iOS-Projektaufbau

`ios/` folgt der Referenz-App:

- **XcodeGen:** `project.yml` und `xcodegen/base.yml` werden kopiert. Das `.xcodeproj` wird
  nicht eingecheckt.
- **Targets:**

  | Target | Typ | Bundle-ID |
  |---|---|---|
  | `Lector` | App | `me.krinke.lector` |
  | `LectorShare` | Share Extension | `me.krinke.lector.share` |
  | `LectorTests` | Unit-Tests | – |
  | `LectorUITests` | UI-Tests, eigenes Schema | – |

- **Gemeinsam genutzt:** App Group `group.me.krinke.lector` für die Serveradresse in
  geteilten `UserDefaults`, Keychain-Zugriffsgruppe `$(AppIdentifierPrefix)me.krinke.lector.shared`
  für den Zugangsschlüssel.
- **Ordner:** `App/`, `UI/`, `Network/` (`APIClient`, `AuthSession`, `TokenStore`,
  `ServerKonfiguration`, `EreignisStrom`, DTOs), `Capture/` (Scanner, Fotoauswahl,
  PDF-Erzeugung), `Design/`.
- **Gemeinsamer Code** von App und Extension (Netzwerk, `TokenStore`, PDF-Erzeugung, DTOs)
  liegt in einem gemeinsamen Quellordner `Shared/`, der in beide Targets eingebunden wird.
  Ein eigenes Framework-Target lohnt sich bei dieser Größe nicht.

*Abweichung von der Referenz:* keine Build-Einstellung `API_BASE_URL`, denn die Adresse kommt
aus der Einrichtung. Debug-Builds gegen `localhost` brauchen damit keinen Sonderweg.

### D10: Serveradresse und ATS

Die Person gibt eine Basis-Adresse ein. Fehlt das Schema, wird `https://` ergänzt, ein `/` am
Ende wird entfernt. Danach ruft die App `GET <adresse>/api/info` auf. Gespeichert wird nur,
wenn dort `service == "lector"` und `api_version == 1` steht. `http://` ist nur für Adressen
im lokalen Netz zulässig: Hosts auf `.local`, private IPv4-Bereiche und Namen ohne Punkt.
`Info.plist` setzt dafür `NSAllowsLocalNetworking`, aber nicht `NSAllowsArbitraryLoads`. Die
App prüft das zusätzlich selbst, damit die Fehlermeldung verständlich bleibt.

### D11: Netzwerk, Sitzung und Live-Aktualisierung

`APIClient` arbeitet mit `async`/`await` und `URLSession`. Den Header `Authorization` setzt
der Client zentral. Ein 401 löscht den Schlüssel und setzt den Sitzungszustand auf
„Anmeldung nötig“; Netz- und 5xx-Fehler lassen den Schlüssel unangetastet. Gegenüber der
Referenz-App entfällt der Refresh-Ablauf (D2).

`EreignisStrom` liest `/events` über `URLSession.bytes(for:)` zeilenweise und meldet
Dokument-IDs. Die Historie lädt daraufhin gezielt `GET /documents/{id}` nach. Ist der Vorgang
unbekannt, wird er oben eingefügt. Abbrüche werden mit wachsender Wartezeit
(1, 2, 5, 10, 30 Sekunden) neu aufgebaut, nach jedem Wiederaufbau wird die Liste vollständig
neu geladen. Beim Wechsel in den Hintergrund (`scenePhase`) wird der Stream beendet, bei der
Rückkehr neu geöffnet.

### D12: Erfassung und PDF-Erzeugung

- **Scanner:** `VNDocumentCameraViewController`, eingebettet als
  `UIViewControllerRepresentable`.
- **Fotos:** `PhotosPicker` mit Mehrfachauswahl.
- **PDF:** Alle Bilder eines Vorgangs werden mit `UIGraphicsPDFRenderer` zu einem PDF, ein Bild
  je Seite. Die Seitengröße folgt dem Seitenverhältnis des Bildes.
- **Qualität:** Bilder werden als JPEG mit Qualität 0,85 eingebettet. Ist die lange Kante
  größer als 3 000 px, wird sie auf 3 000 px verkleinert. Das reicht für die Texterkennung
  und hält einen Kassenbon unter etwa 1 MB.
- **Dateiname:** `Scan JJJJ-MM-TT HHMMSS.pdf` in Ortszeit. Inhalte werden nicht ausgewertet,
  denn Klassifizierung bleibt Aufgabe von Paperless.

Die Begradigung durch VisionKit und das anschließende Deskew von Lector bleiben bewusst
beide aktiv. Ein schon gerades Bild ändert das Deskew nicht nennenswert. Das wird im
Abnahmetest geprüft (Task 7).

### D13: Share Extension

Die Extension wird aktiviert durch `NSExtensionActivationRule` für PDF, XML (`public.xml`),
TIFF und Bilder (`public.image`), bis zu 20 Dateien. Sie liest die Serveradresse aus der App
Group und den Schlüssel aus der gemeinsamen Keychain-Gruppe. Ist eines von beiden nicht
vorhanden, erscheint der Hinweis „Bitte zuerst in der Lector-App anmelden“.

Die Formatentscheidung fällt nach dem `UTType` der Datei:

- `pdf`, `xml` und `tiff` bleiben byte-genau unverändert.
- Andere `image`-Typen werden über D12 zu einem PDF.
- Alles andere wird abgewiesen.

Hochgeladen wird im Vordergrund der Extension mit sichtbarem Fortschritt, jede Datei als
eigene Datei, und je Datei wird das Ergebnis angezeigt.

TIFF wird nicht umgewandelt. Der Server unterstützt es, mehrseitige TIFFs (Fax, Scanner)
ließen sich auf dem Gerät nur mit mehr Aufwand sauber umwandeln, und die Spec verlangt die
Umwandlung nur für Bilder aus Kamera und Mediathek.

### D14: Gestaltung

Die App nutzt SwiftUI-Systemkomponenten (`NavigationStack`, `List`, `searchable`, Menüs für
Filter) mit Lectors Akzentfarbe und Zustandsfarben aus `DESIGN.md`. Die Bezeichnungen der
Zustände übernimmt sie aus `feature-documentation/ui-texte.md`, damit Web und App dieselben
Begriffe verwenden. Eine eigene Designsprache wie im Smoking Tracker ist nicht vorgesehen.

## Risks / Trade-offs

- **[Speichergrenze der Share Extension (~120 MB)]** → Dateien werden direkt von ihrer URL
  hochgeladen (`upload(for:fromFile:)` bzw. Multipart als gestreamte Datei im temporären
  Ordner), nicht vollständig in den Speicher geladen. Die PDF-Erzeugung aus Bildern läuft
  Bild für Bild.
- **[Proxy puffert den Ereignisstrom oder entfernt `Authorization`]** → Das ist eine
  Prüfaufgabe im Abnahmetest gegen die echte Instanz. Ohne Live-Strom funktioniert die App
  weiter, Aktualisierungen kommen dann nur beim Nachladen. Die Doku nennt die nötige
  Proxy-Einstellung.
- **[Schlüssel auf einem verlorenen Gerät]** → Der Schlüssel gilt höchstens 90 Tage. Alle
  Sitzungen lassen sich über einen Wechsel von `LECTOR_SECRET_KEY` sofort beenden (bekannte
  Grenze aus `web-zugang.md`). Eine gezielte Geräteabmeldung ist ein Kandidat für später.
- **[Sitzungskennung im Klartext in der Datenbank]** → Das gilt unverändert schon heute
  für Cookies. Durch D2 kommt kein neues Risiko hinzu, es wird aber in der Doku vermerkt.
- **[`AUTH_MODE=none` mit öffentlich erreichbarem Dienst]** → Dann ist auch die
  Schnittstelle offen, genau wie heute die Weboberfläche. Die Doku zur Schnittstelle weist
  ausdrücklich darauf hin.
- **[Versionssprung der Schnittstelle]** → Die App prüft `api_version` bei der Einrichtung
  und bei jedem Start. Bei Abweichung zeigt sie einen klaren Hinweis statt Fehlerkaskaden.

## Migration Plan

1. Den Server mit der Schnittstelle ausrollen. Die Änderung ist rein additiv: Die bestehenden
   Routen verhalten sich unverändert, und die Testsuite im Modus `none` und `paperless`
   bleibt grün. Danach das Image wie gewohnt über die Scaleway-Registry verteilen.
2. Gegen die echte Instanz prüfen: `GET /api/info`, Anmeldung mit MFA, Ereignisstrom durch
   den Proxy.
3. App per Archiv mit `-allowProvisioningUpdates` und `ExportOptions.plist` nach TestFlight
   hochladen. Interne Tester brauchen keine Prüfung durch Apple.
4. Rückweg: Den Server auf das vorherige Image zurücksetzen. Die App bekommt dann 404 auf
   `/api/info` und meldet „kein Lector gefunden“. Daten gehen nicht verloren, weil sich am
   Schema nichts ändert.

## Open Questions

- App-Symbol und Anzeigename (Vorschlag „Lector“). Das betrifft weder Specs noch Ablauf und
  kann während der Umsetzung entschieden werden.

## Anhang: Schnittstellenvertrag v1

Verbindliche Form der Antworten. Server und App bauen beide dagegen. Zeitpunkte sind
ISO-8601-Zeichenketten in UTC mit `Z` oder `null`. Authentifiziert wird mit
`Authorization: Bearer <token>`.

```text
GET  /api/info
  200 {"service": "lector", "api_version": 1, "auth_mode": "none" | "paperless"}

POST /api/v1/login            Content-Type: application/json
  body {"username": str, "password": str, "code": str | null}
  200 {"token": str, "username": str}
  401 invalid_credentials | mfa_required, 429 throttled, 503 paperless_unavailable,
  415 invalid_request (falscher Content-Type), 404 im Modus none

POST /api/v1/logout
  204 (leer); 404 im Modus none

GET  /api/v1/documents?status=&q=&period=&limit=200&offset=0
  200 {"documents": [Document], "counts": {<status>: int, ...}, "limit": int, "offset": int}
      counts enthält jeden Zustand (pending, processing, blocked, done,
      skipped_erechnung, failed), fehlende mit 0

GET  /api/v1/documents/{id}
  200 {"document": Document, "events": [Event], "page_limit": int, "retry_max": int}
  404 not_found

POST /api/v1/documents/{id}/release | /discard
  200 {"document": Document}
  404 not_found, 409 not_blocked, 500 discard_failed

POST /api/v1/upload           multipart/form-data, Feld "files" (mehrfach)
  200 {"results": [{"filename": str, "accepted": bool,
                    "reason": null | "unsupported_format" | "unusable_name" | "store_failed",
                    "stored_as": str | null}]}
  400 no_files

GET  /events                  text/event-stream; Vorgang: "data: doc:<document_id>\n\n";
                              andere Präfixe (inv:, rec:, batch:) ignorieren; Keepalive ": keepalive\n\n"

Document = {"id": int, "original_filename": str, "status": str, "doc_type": str | null,
            "total_pages": int | null, "processed_pages": int, "attempt_count": int,
            "next_retry_at": ts | null, "error_message": str | null,
            "page_limit_approved": bool, "created_at": ts | null,
            "started_at": ts | null, "finished_at": ts | null}
Event    = {"id": int, "timestamp": ts, "event_type": str, "message": str | null}
Fehler   = {"error": {"code": str, "message": str}}   // message: deutscher Klartext
```
