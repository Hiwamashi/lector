# Einrichtung und Anmeldung — iOS-App

**Module:** `ios/Shared/Network/` (`APIClient`, `AuthSession`, `ServerKonfiguration`, `ServerAdresse`, `TokenStore`), `ios/Lector/UI/` (Einrichtungsansicht, Anmeldeformular, `SitzungsModell`), `app/api.py` (`/api/info`, `/api/v1/login`, `/api/v1/logout`)

## Zweck

Beim ersten Start fragt die iOS-App nach der Serveradresse und prüft die Erreichbarkeit. Im Modus `AUTH_MODE=paperless` folgt eine Anmeldung gegen Paperless mit optional erforderlichem MFA-Code. Der erhaltene Zugangsschlüssel wird sicher in der Keychain abgelegt und für alle nachfolgenden API-Anfragen verwendet. Die Sitzung bleibt über die Lebensdauer des Geräts erhalten, bis die App abgemeldet wird oder der Schlüssel abläuft.

## Serveradresse und Normalisierung

### Eingabe und Validierung

Die Person gibt eine Basis-Adresse ein (z. B. `lector.nerd-wg.eu` oder `192.168.1.42`). Die App normalisieret diese:

1. **Schema ergänzen:** Fehlt das Schema, wird `https://` ergänzt.
2. **Trailing Slash entfernen:** Ein `/` am Ende wird gelöscht.
3. **Beispiele nach Normalisierung:**
   - `lector.nerd-wg.eu` → `https://lector.nerd-wg.eu`
   - `http://192.168.1.42/` → `http://192.168.1.42`

### ATS-Regeln (`NSAllowsLocalNetworking`)

Apples **App Transport Security** (`NSAllowsLocalNetworking`, nicht `NSAllowsArbitraryLoads`) erlaubt `http://` nur für lokale Adressen:

- **.local-Domänen** (Bonjour): `*.local`
- **Private IPv4-Bereiche:** `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`
- **Lokale IPv6:** `fe80::/10` (Link-Local)
- **Hostnamen ohne Punkt** (Single-Label): `meinrouter` oder `nas` (keine TLD)

Alle anderen `http://`-Adressen werden von ATS blockiert. Die App prüft dies zusätzlich selbst (in `ServerAdresse`), damit die Fehlermeldung verständlich bleibt und nicht `NSError(domain: NSURLErrorDomain, code: -1200)` angezeigt wird.

### Info-API-Prüfung

Bevor die Adresse gespeichert wird, ruft die App `GET <adresse>/api/info` auf. Die Antwort muss sein:

```json
{
  "service": "lector",
  "api_version": 1,
  "auth_mode": "none" oder "paperless"
}
```

- **Feld `service`:** Muss exakt `"lector"` sein (sonst ist es nicht der richtige Dienst).
- **Feld `api_version`:** Muss `1` sein. Bei Abweichung zeigt die App einen Hinweis wie „Diese App unterstützt die Schnittstellen-Version nicht" (keine Fehlerkaskaden).
- **Feld `auth_mode`:** Bestimmt, ob Anmeldung erforderlich ist (`paperless`) oder die App sofort zur Historie geht (`none`).

Fehlt die Antwort oder hat einen anderen Inhalt, meldet die App „Kein Lector gefunden unter dieser Adresse".

## Anmeldung (Modus `paperless`)

### Vier Ablehnungsgründe

Die Anmeldung über `/api/v1/login` (POST mit `Content-Type: application/json`) kann vier Fehler zurückgeben:

| HTTP-Status | `error.code` | Anzeige | Passwort erhalten |
|---|---|---|---|
| 401 | `invalid_credentials` | „Anmeldung fehlgeschlagen" | ja (behalten) |
| 401 | `mfa_required` | „MFA-Code erforderlich" | ja (behalten) |
| 503 | `paperless_unavailable` | „Paperless ist nicht erreichbar" | ja (behalten) |
| 429 | `throttled` | „Zu viele Fehlversuche. Bitte später erneut versuchen" | ja (behalten) |

Bei `invalid_credentials` und `mfa_required` zählen die Versuche gegen die serverseitige Drosselung. Bei `throttled` verbietet der Server weitere Versuche. Bei `paperless_unavailable` wird die Verbindung zu Paperless nicht versucht oder schlägt fehl (der Dienst zählt dies nicht als Fehlversuch).

### MFA-Workflow

Die App stellt drei Eingabefelder dar:

1. **Nutzername** (Textfeld)
2. **Passwort** (Passwort-Typ)
3. **MFA-Code** (optional Zahlenfeld, je nach Konfiguration)

Beim ersten Versuch werden alle drei Felder gesendet. Antwortet der Server mit `401 mfa_required`, wird **Nutzername und Passwort behalten** (nicht gelöscht), und ein Hinweis „Code erforderlich" angezeigt. Die Person kann dann nur den Code-Feld korrigieren und erneut versuchen.

Ein falscher MFA-Code ergibt `invalid_credentials` (Unterscheidung möglich, aber beide gelten als Fehlversuch).

## Zugangsschlüssel (Bearer-Token)

### Speicherung in der Keychain

Nach erfolgreicher Anmeldung erhält die App einen `token` (Zugangsschlüssel), den die Funktion `sign_app_token()` auf dem Server erzeugt hat. Dieser Token wird **ausschließlich** in der Keychain des Geräts gespeichert, nicht im Arbeitsspeicher oder in Dateien.

- **Klasse:** `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly` — Der Token ist lesbar, nachdem das Gerät zum ersten Mal entsperrt wurde, und bleibt nur auf diesem Gerät verfügbar. Beim Entsperren (Face ID, PIN) wird der Zugriff erneut überprüft.
- **Zugriffsgruppe:** `$(AppIdentifierPrefix)me.krinke.lector.shared` — Beide Targets (`Lector` und `LectorShare`-Extension) können den Token lesen und schreiben. Dies ermöglicht der Share Extension, Dateien ohne erneute Anmeldung hochzuladen.
- **Schlüssel:** `lector_app_token` (oder ähnlich, siehe `TokenStore`-Implementierung).

### Kein Refresh erforderlich

Der Token wird **nach der Anmeldung nie erneuert**. Er bleibt gültig, solange die Zeile in der Server-Tabelle `web_sessions` existiert:

- **30 Tage Leerlauf:** Jede erfolgreiche API-Anfrage erneuert die `last_seen_at` auf dem Server.
- **90 Tage absolut:** Unabhängig von der Nutzung ist der Token nach 90 Tagen ungültig.

Das unterscheidet sich bewusst vom Cookie-Ablauf in der Weboberfläche, wo das Cookie bei jeder Anfrage neu signiert wird. Die iOS-App muss nicht mitbekommen, dass der Server die Sitzung „erneuert" hat.

## Sitzungszustände

Die App verwaltet drei Sitzungszustände:

1. **Nicht eingerichtet:** Keine Serveradresse vorhanden → Einrichtungsansicht zeigen.
2. **Angemeldet:** Serveradresse + gültiger Token in der Keychain → Historie zeigen.
3. **Abgemeldet/Sitzung ungültig:** Serveradresse vorhanden, aber Token fehlt oder ist ungültig (oder `401` vom Server) → Anmeldeformular zeigen, Adresse beibehalten.

Das Modell `SitzungsModell` speichert den aktuellen Zustand und triggert die entsprechende Ansicht über SwiftUI-Binding. Beim App-Start wird `api_version` geprüft (siehe „Start-Prüfung" unten).

## 401-Verhalten vs. Netzwerkfehler

### Ein 401 ist eine echte Anmeldung

Ein `401 not_authenticated` vom Server bedeutet, dass der Zugangsschlüssel ungültig ist — entweder weil er abgelaufen ist oder die Sitzung wurde auf dem Server gelöscht (z. B. weil der Nutzer sich abgemeldet hat oder das Sitzungsgeheimnis geändert wurde).

**Verhalten:**

- Der `APIClient` **löscht** den Token aus der Keychain.
- Das `SitzungsModell` wechselt auf „Angemeldet nötig" und zeigt das Anmeldeformular.
- Die Serveradresse bleibt erhalten (wechseln nicht auf „Nicht eingerichtet").

### Netzwerkfehler und 5xx löschen den Token nicht

Fehler wie Timeout, Verbindungsabbruch, DNS-Fehler oder `5xx`-Fehler (Server-Fehler) bedeuten, dass die Kommunikation fehlschlagen ist — nicht, dass der Token ungültig ist.

**Verhalten:**

- Der Token bleibt in der Keychain.
- Der `APIClient` wirft einen `NetworkError` (oder ähnlich).
- Die Ansicht zeigt „Verbindung fehlgeschlagen" und bietet „Erneut versuchen".
- Beim nächsten erfolgreichen Aufruf wird der Token weiterhin verwendet.

Dies verhindert, dass die App den Token bei kurzfristigem Netzwerkausfall oder Server-Wartungsfenster verwirft.

## Abmelden

Die Person kann sich in den Einstellungen abmelden. Dabei:

1. **Server benachrichtigen (beste Mühe):** `POST /api/v1/logout` wird aufgerufen, falls der Server erreichbar ist. Der Request trägt den aktuellen Token als `Authorization: Bearer`.
2. **Token löschen:** Der Token wird in jedem Fall aus der Keychain entfernt, unabhängig davon, ob der Server antwortet.
3. **Zustand wechseln:** Das `SitzungsModell` zeigt das Anmeldeformular, die Serveradresse bleibt.

Ist der Server nicht erreichbar (Netzwerkfehler, Offline-Modus), wird der Token trotzdem gelöscht — die App bleibt anmeldefrei und kann später neu eingerichtet werden.

## Serverwechsel

Die App bietet in den Einstellungen die Möglichkeit, eine neue Serveradresse einzurichten. Beim Wechsel:

1. **Alter Token gelöscht:** Der bisherige Token wird aus der Keychain entfernt.
2. **Neue Adresse validiert:** Die neue Adresse wird wie bei der Ersteinrichtung gegen `/api/info` geprüft.
3. **Anmeldung erforderlich:** Die App wechselt zur Anmeldeansicht für den neuen Server.

Dies verhindert, dass der alte Token versehentlich bei einer anderen Lector-Instanz verwendet wird.

## Modus `none` (keine Anmeldung)

Wenn `/api/info` die Antwort `"auth_mode": "none"` liefert:

- Die Anmeldeansicht wird **nicht gezeigt**.
- Die App fährt direkt zur Historie fort.
- Der `APIClient` sendet keinen `Authorization`-Header.
- Die Routen `/api/v1/login` und `/api/v1/logout` sind nicht vorhanden (würden `404` antworten).

Im Modus `none` ist die ganze Lector-Instanz offen (wie die Weboberfläche ohne `AUTH_MODE=paperless`). Die App schränkt nicht ein, wer Zugang hat.

## Start-Prüfung von `api_version`

Jedes Mal, wenn die App startet und bereits eine Serveradresse vorhanden ist, wird `GET /api/info` erneut aufgerufen, um die Version zu prüfen. Dies geschieht, bevor die Historie oder andere Daten geladen werden.

**Zweck:**

- **Server-Update erkannt:** Wurde der Server auf ein neueres Image mit einer anderen `api_version` aktualisiert, erkennt die App das und zeigt einen klaren Hinweis (z. B. „Diese App-Version unterstützt die neue Schnittstelle nicht").
- **Rollback erkannt:** Wurde der Server auf ein älteres Image zurückgesetzt, erkennt die App das ebenfalls.
- **Downtime:** Bei einem Server-Downgrade von `api_version: 1` auf `404` oder fehlender Antwort zeigt die App „Kein Lector gefunden", nicht Fehlerkaskaden.

Sollte die Versionsabfrage fehlschlagen (Netzwerkfehler, Timeout), wird das offline akzeptiert und die App fährt mit den zuletzt bekannten Einstellungen fort.

## Code-Orte

| Datei | Rolle |
|---|---|
| `ios/Shared/Network/APIClient.swift` | HTTP-Client, `async`/`await`, Header setzen, 401-Behandlung, Fehlerklassifikation |
| `ios/Shared/Network/AuthSession.swift` | Sitzungsverwaltung, Anmeldestatus (eingerichtet/angemeldet/abgemeldet), Token-Validierung |
| `ios/Shared/Network/ServerKonfiguration.swift` | Speicherung der Serveradresse in App-Group-`UserDefaults`, Lesezugriff |
| `ios/Shared/Network/ServerAdresse.swift` | Normalisierung, ATS-Prüfung (lokal/öffentlich), IPv4/IPv6-Erkennung, `/api/info`-Prüfung |
| `ios/Shared/Network/TokenStore.swift` | Keychain-Verwaltung (`kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`), Zugriffsgruppe `$(AppIdentifierPrefix)me.krinke.lector.shared` |
| `ios/Lector/UI/EinrichtungsAnsicht.swift` | Eingabeformular für Adresse, Validierung, Error-Handling |
| `ios/Lector/UI/AnmeldungAnsicht.swift` | Formular (Nutzername, Passwort, MFA-Code), Vier-Fehler-Unterscheidung, Feld-Erhaltung bei MFA |
| `ios/Lector/UI/SitzungsModell.swift` | Zustandsverwaltung, Triggers für Ansicht-Wechsel, Start-Prüfung von `api_version` |
| `app/api.py` | Routen `GET /api/info`, `POST /api/v1/login`, `POST /api/v1/logout` |
| `app/auth.py` | `sign_app_token()`, `load_app_session()`, Bearer-Token-Weiche |
| `app/main.py` | Funktion `authenticate()` (gemeinsamer Kern mit HTML-Anmeldung) |
