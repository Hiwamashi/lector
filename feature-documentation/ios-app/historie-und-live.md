# Historie und Live-Aktualisierung — iOS-App

**Module:** `ios/Lector/UI/Historie/` (`HistorieModell`, `DetailModell`, `HistorieAnsicht`), `ios/Lector/Live/` (`EreignisStrom`), `app/api.py` (`GET /api/v1/documents`, `GET /api/v1/documents/{id}`, `GET /events`)

## Zweck

Die Historie zeigt eine durchsuchbare Liste aller Vorgänge (Dokumente), neueste zuerst, mit Zählern nach Zustand. Solange die App sichtbar ist, wird die Liste durch einen Ereignisstrom (Server-Sent Events) automatisch aktualisiert — neue oder geänderte Vorgänge erscheinen ohne Zutun der Person. Das Detail zu einem Vorgang zeigt den vollständigen Verlauf und erlaubt Entscheidungen bei angehaltenen Vorgängen.

## HistorieModell

### Filterung und Pagingierung

Das Modell filtert die Liste nach:

- **Zustand:** `pending`, `processing`, `blocked`, `done`, `skipped_erechnung`, `failed` (oder alle).
- **Zeitraum:** `today`, `week`, `month`, `all` (von `ui-texte.md`).
- **Suchtext:** Freitext im Dateinamen.

Die API-Route `GET /api/v1/documents` wird mit diesen Parametern aufgerufen und liefert maximal 200 Einträge pro Seite. Das Modell speichert den `offset` für das Nachladen älterer Vorgänge.

### Seitengröße und Offsets

- **Seitengröße:** Fest auf 50 Einträge pro Lade-Vorgang eingestellt (nicht 200, um schneller zu laden und die UI responsiver zu halten).
- **Naechster Offset:** Das Modell speichert den `offset` für die nächste Seite, um Verschleißverschleiß beim Nachladen zu vermeiden. Ist `offset >= gesamte_anzahl`, sind alle Einträge geladen.

### Duplikatfilter und Generationen

Der Ereignisstrom meldet Änderungen über Dokument-IDs. Um zu vermeiden, dass eine alte Antwort vom Server eine neuere überschreibt, nutzt das Modell **Generationen**:

- Jeder vollständigen Liste-Ladung wird eine Generationsnummer zugeordnet.
- Das Detail eines Vorgangs trägt die Generationsnummer der Liste, von der es stammt.
- Liegt ein Detail von einer älteren Generation vor und es kommt ein Live-Update von einer neueren, wird das Detail verworfen.

Beispiel: Die Liste wurde mit `generation=2` geladen. Der Stream meldet `doc:42`. Das Modell lädt das aktuelle Detail von `doc:42`. Inzwischen wird die Liste erneut geladen (`generation=3`). Wenn die alte Antwort von `doc:42` eintrifft, wird sie ignoriert, weil `generation=2 < generation=3`.

### Vormerken von Live-Ids

Während die Liste geladen wird, treffen Änderungsmeldungen vom Stream ein (z. B. `doc:42`). Das Modell **merkt sie vor**:

- Ankommendes Event `doc:42` → In Menge `pending_updates` eintragen.
- Nach List-Ladung → Diese Vorgen nachtragen, um Lücken zu vermeiden.

Dies verhindert, dass eine Änderung „verlorengeht", weil das Event traf, während wir die Liste noch laden.

### Zähler

Die API liefert `counts` mit jedem Request: `{pending: int, processing: int, blocked: int, done: int, skipped_erechnung: int, failed: int}`. Diese Zähler gelten für den **gesamten Bestand** (ungefiltert nach Zustand oder Zeit). Die UI zeigt sie oben in der Liste.

## Zeit in Gerätezeitzone

**Speicherung auf dem Server:** Alle Zeitpunkte in der Datenbank liegen als UTC ohne Zonenangabe vor (`%Y-%m-%d %H:%M:%S`).

**Übertragung:** Die API gibt Zeitpunkte als ISO-8601-Strings in UTC aus (mit `Z`-Suffix): `2026-10-12T10:30:45Z`.

**Anzeige in der App:** Die App konvertiert alle Zeitpunkte in die Gerätezeitzone mittels `TimeZone.current` und zeigt sie in lokaler Zeit. Der Server sendet keine Zeitzone; die App kümmert sich selbst darum.

**Beispiel:** Der Server zeigt `created_at: "2026-10-12T08:30:00Z"` (UTC). Auf einem Gerät mit Zeitzone `Europe/Berlin` (UTC+2 im Oktober) wird „12.10.2026, 10:30" angezeigt.

## Begriffe aus `ui-texte.md`

Die App verwendet die deutschen Begriffe aus `feature-documentation/ui-texte.md` zur Anzeige von Zuständen und Ereignistypen. Beispiele:

- Zustand `done` → Anzeige „Abgeschlossen"
- Ereignistyp `ocr_chunk` → Anzeige „OCR-Verarbeitung"

Dies stellt sicher, dass Web-UI und iOS-App dieselben Wörter verwenden. Eine eigene Übersetzungslogik in der App wäre redundant.

## EreignisStrom

### SSE-Verbindung zu `/events`

Die App öffnet einen dauerhaften Stream zu `GET /events` (Server-Sent Events) mit dem Bearer-Token:

```
GET /events
Authorization: Bearer <token>
Accept: text/event-stream
```

Die Verbindung bleibt offen, solange die App im Vordergrund ist und die Historie sichtbar ist.

### Parsing und Filter

Der Stream sendet Events wie:

```
data: doc:42

data: doc:123

: keepalive

data: batch:999
```

Die App **parst nur Events mit Präfix `doc:`** und extrahiert die Dokument-ID. Andere Präfixe (`batch:`, `inv:`, `rec:`) werden ignoriert (diese dienen der Paperless-Integration und sind für die iOS-App nicht relevant).

Das `keepalive`-Event (nur ein `:`) wird ebenfalls ignoriert, dient aber dem Server, um die Verbindung am Leben zu halten.

### Exponentieller Backoff bei Abbau

Wenn die Verbindung bricht (Server sendet `401`, Netzwerk weg, etc.), baut die App sie mit wachsender Wartezeit neu auf:

- **1. Versuch:** Sofort neu verbinden.
- **2. Versuch:** 1 Sekunde warten.
- **3. Versuch:** 2 Sekunden warten.
- **4. Versuch:** 5 Sekunden warten.
- **5. Versuch:** 10 Sekunden warten.
- **6. Versuch:** 30 Sekunden warten.
- **Danach:** Bei jedem weiteren Versuch 30 Sekunden warten.

Dies verhindert, dass die App den Server mit Reconnect-Anfragen bombardiert.

### Wiederaufbau und Nach-Laden

Steht die Verbindung nach einem Abbruch wieder, meldet `EreignisStrom` dies als
`.wiederaufgebaut` (beim ersten Öffnen nicht). `HistorieModell` lädt daraufhin die Liste mit
den aktuellen Filtern neu, und zwar im bisherigen Umfang (`laden(umfang: .behalten)`): so
viele Vorgänge, wie schon angezeigt waren, mindestens eine Seite (50), höchstens 200. So
schrumpft die Liste nach dem Wiederaufbau nicht auf die erste Seite, und Änderungen aus der
Zeit ohne Verbindung gehen nicht verloren. Dasselbe Nachladen läuft bei der Rückkehr aus dem
Hintergrund.

Reihenfolge: erst Verbindung wieder aufgebaut, dann Nachladen. Ereignisse, die währenddessen
eintreffen, werden vorgemerkt und nach dem Übernehmen der Antwort gezielt nachgeladen (siehe
oben, Generationen und Vormerken).

### `401` und Disconnect

Ein `401 not_authenticated` vom Stream wird **nicht** mit Backoff behandelt. Stattdessen:

1. Stream wird beendet.
2. Token wird aus der Keychain gelöscht (dies macht der `APIClient`).
3. Die App wechselt zur Anmeldeansicht.

Dies unterscheidet sich von anderen Netzwerkfehlern, die mit Backoff neu verbunden werden.

### Abbau im Hintergrund

Die App überwacht `scenePhase` (SwiftUI):

- **`scenePhase == .active`:** App sichtbar → Stream offen halten, Live-Updates zeigen.
- **`scenePhase == .background` oder `.inactive`:** App im Hintergrund → Stream sofort beenden (kein Reconnect, keine offenen Verbindungen).

Beim Wechsel zurück in den Vordergrund (`.active`) wird die Liste neu geladen und der Stream erneut geöffnet.

Dies verhindert, dass die App im Hintergrund Batterie zieht, und folgt iOS-Best-Practices.

## DetailModell und Verlauf

### Anzeige von Vorgang und Ereignissen

Das Detail zu einem Vorgang ruft `GET /api/v1/documents/{id}` auf und erhält:

```json
{
  "document": { /* Vorgang-Objekt */ },
  "events": [ /* Verlauf */ ],
  "page_limit": 1000,
  "retry_max": 3
}
```

Die `events` sind zeitlich sortiert (älteste zuerst) und werden als Zeitleiste angezeigt. Jedes Event trägt:

- **Zeitpunkt** (in UTC, wird in Gerätezeitzone konvertiert)
- **Ereignistyp** (z. B. `detected`, `ocr_chunk`, `built_pdf`, `done`)
- **Nachricht** (optionaler deutscher Text vom Server)

Die Felder `page_limit` und `retry_max` werden bei einem angehaltenen Vorgang (`status == "blocked"`) angezeigt, um der Person zu helfen, die Situation zu verstehen.

### Entscheidungen mit Bestätigung

Ist der Vorgang angehalten (`status == "blocked"`), bietet das Detail zwei Buttons:

- **Freigeben:** `POST /api/v1/documents/{id}/release`
- **Verwerfen:** `POST /api/v1/documents/{id}/discard`

Vor dem Absenden zeigt die App einen Alert, z. B. „Diesen Vorgang wirklich freigeben?" Die Person muss explizit bestätigen. Dies verhindert versehentliche Entscheidungen.

### 409-Verhalten: Nicht mehr angehalten

Ein `POST /api/v1/documents/{id}/release` oder `/discard` kann mit `409 not_blocked` scheitern, wenn:

- Ein anderes Gerät (z. B. die Weboberfläche) hat inzwischen die Entscheidung getroffen.
- Der Dienst hat den Vorgang automatisch freigegeben (z. B. Seitenobergrenze erhöht).

**Verhalten:**

- Ein Alert zeigt „Dieser Vorgang wurde inzwischen anders entschieden" (oder ähnlich).
- Das Detail wird sofort neu geladen (um den aktuellen Stand zu zeigen).
- Die Entscheidungs-Buttons verschwinden.

## Code-Orte

| Datei | Rolle |
|---|---|
| `ios/Lector/UI/Historie/HistorieAnsicht.swift` | Ansicht: Liste, Filter, Suche, Nachladen, Zähler |
| `ios/Lector/UI/Historie/HistorieModell.swift` | Datenverwaltung: Filterung, Pagination, Duplikatfilter, Generationen, Vormerken |
| `ios/Lector/UI/Historie/DetailAnsicht.swift` | Ansicht: Vorgang, Verlauf, Entscheidungs-Buttons |
| `ios/Lector/UI/Historie/DetailModell.swift` | Datenverwaltung: Laden, Entscheidungen, 409-Handling |
| `ios/Lector/Live/EreignisStrom.swift` | SSE-Parser, Stream-Verwaltung, Reconnect-Backoff, `scenePhase`-Beobachter |
| `ios/Lector/UI/Historie/Anzeige.swift` | Konvertierung: Zeitzone, Begriffe aus `ui-texte.md`, Zustandsfarben |
| `app/api.py` | Routen `GET /api/v1/documents`, `GET /api/v1/documents/{id}`, `GET /events` |
| `feature-documentation/ui-texte.md` | Begriffe für Zustände und Ereignistypen |
