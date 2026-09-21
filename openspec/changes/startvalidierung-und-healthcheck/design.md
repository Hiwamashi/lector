# Design

## Context

Motivation in `proposal.md`, Verhaltenszusicherungen in den beiden Delta-Specs. Hier stehen
nur die Gegebenheiten, die den Weg bestimmen.

**Die Konfiguration kann heute nicht scheitern.** `Settings` ist eine
`pydantic_settings.BaseSettings` (`app/config.py:12`), in der **jedes** der rund 60 Felder
einen Standardwert trägt. Es gibt kein `Field(...)` ohne `default=`. Ein fehlendes
`GCP_PROJECT_ID` ist deshalb kein Validierungsfehler, sondern der leere String. Was pydantic
heute schon abfängt, ist allein der **falsche Typ** (`RETRY_MAX=abc`) — und zwar beim ersten
`get_settings()`, also in `lifespan`.

**`get_settings()` hat genau eine produktive Aufrufstelle:** `app/main.py:161`, in
`lifespan`. Das Ergebnis wird von dort per Konstruktor an `Repository`, `get_adapter`,
`PaperlessSync` und `Worker` weitergereicht (`app/main.py:162-174`). Kein Pfad holt die
Einstellungen pro Dokument neu. Eine Prüfung an dieser einen Stelle deckt den gesamten
produktiven Betrieb ab.

**Die Testsuite umgeht `get_settings()` fast vollständig.** Der Großteil der rund 320 Tests
baut `Settings(**overrides)` direkt (`tests/test_pipeline.py:46`, `tests/test_recovery.py:18`,
`tests/test_decisions.py:9`, `tests/test_ocr_chunk_reuse.py:46`) und ruft
`get_settings()` nie auf. Nur `tests/test_web.py` durchläuft den echten `lifespan` — über
die Fixture `client` (Zeilen 11-25) und einen zweiten Aufbau ab Zeile 672. Diese Asymmetrie
bestimmt die zentrale Entscheidung unten (D1).

**Vom Zustand der Laufzeitbestandteile ist heute nichts abfragbar, aber alles vorhanden.**
Der Worker hält seine fünf Tasks in `self._tasks` (`app/worker.py:68`, gefüllt 79-88) und
den Observer in `self._observer` (Zeile 69) — beides wird nie befragt. Die `Worker`-Instanz
selbst liegt **nicht** in `app.state` (dort nur `settings`, `repo`, `bus`, `sync`,
`app/main.py:174-177`), ist also aus einer Route heraus zurzeit nicht erreichbar. Das
Repository hält **eine** SQLite-Verbindung pro Prozess hinter einem `threading.Lock`
(`app/repository.py:126-129`).

**Jede Schleife heilt sich pro Durchlauf selbst.** `_scan_loop`, `_process_loop`,
`_retry_loop`, `_retention_loop` und `_paperless_loop` fangen `Exception` **innerhalb** der
`while`-Schleife und protokollieren (`app/worker.py:151,177,188,208,217`). Eine wirklich
beendete Task bedeutet daher, dass etwas außerhalb dieses Netzes zerbrochen ist — der
seltene, aber folgenschwere Fall.

**Das Betriebsabbild hat kein `curl` und kein `wget`.** `python:3.12-slim` bringt beides
nicht mit, und das Dockerfile installiert nur `libglib2.0-0`, `libgl1`, `tini`
(`Dockerfile:5-9`). Der Prozess läuft als **root** (kein `USER`), `PUID`/`PGID` wirken erst
auf die geschriebenen Dateien (`app/fileops.py:40`).

**Es gibt im Repo keine Vorlage für einen `healthcheck`-Block** — kein Service in
`docker-compose.example.yml` hat einen, auch Paperless nicht. `tests/test_compose_files.py`
prüft bisher nur das Registry-Image.

## Goals / Non-Goals

**Goals:**

- Eine Prüfung an einer Stelle, die den produktiven Start vollständig abdeckt, ohne die
  Testsuite in Sippenhaft zu nehmen.
- Eine Begründung, die ohne Rückfrage handlungsfähig macht: Name der Variablen, was ihr
  fehlt, unter welcher Bedingung sie Pflicht ist.
- Ein Health-Endpunkt, der auf vorhandene Tatsachen zugreift, statt neue Buchführung
  einzuführen.

**Non-Goals (Design-Ebene, zusätzlich zum Proposal):**

- **Keine Registratur des Konfigurationszustands im Prozess.** Die Prüfung läuft einmal und
  entscheidet; sie hinterlässt kein Feld, das später abgefragt würde. Folgt aus dem harten
  Abbruch: Läuft der Dienst, war die Konfiguration gültig.
- **Keine Aussage über die Richtigkeit von Werten.** Geprüft wird Vorhandensein,
  Typ, Wertebereich und Lesbarkeit von Pfaden — nicht, ob ein Token gilt oder eine
  Prozessor-Kennung existiert.
- **Kein neuer Endpunkt** neben `/healthz` (kein `/readyz`, kein `/metrics`). Der Dienst hat
  keine Trennung zwischen „lebt" und „bereit": Er nimmt entweder Arbeit an oder er startet
  nicht.

## Decisions

### D1 — Eigene Prüffunktion statt pydantic-Validator

Die Prüfung wird eine gewöhnliche Funktion in `app/config.py`, die ein `Settings`-Objekt
entgegennimmt und die Liste der Beanstandungen zurückgibt. Sie wird ausdrücklich aus
`lifespan` aufgerufen.

**Alternative: ein `model_validator(mode="after")` auf `Settings`.** Naheliegender — die
Prüfung wäre unumgehbar, weil sie an jeder Konstruktion hängt. Genau das ist der Grund
dagegen: Sie hinge auch an den rund 280 Tests, die `Settings(**overrides)` direkt bauen und
keine Document-AI-Angaben setzen. Statt der 33 Tests, die den echten Start durchlaufen,
bräche praktisch die gesamte Suite — und jeder künftige Testaufbau müsste Angaben mitführen,
die für seinen Prüfgegenstand bedeutungslos sind. Die Prüfung gehört an den **Start**, nicht
an die Datenstruktur; eine direkt konstruierte `Settings` ist ein Testwerkzeug und kein
Dienststart.

Zwei weitere Gründe: Die Form der Meldung wäre pydantic überlassen (`ValidationError` mit
Feldnamen in `snake_case`, nicht mit den ENV-Namen, unter denen der Nutzer sie setzt) — die
Spec verlangt aber den Namen, „unter dem sie gesetzt wird". Und die Prüfung der
Beschreibbarkeit ist Dateisystem-Zugriff, der in einem Modellvalidator nichts zu suchen hat.

**Rückgabe als Liste, nicht als erste Ausnahme.** Ergibt sich aus dem Requirement „alle
Beanstandungen in einem Durchgang": Die Funktion sammelt, der Aufrufer entscheidet.

### D2 — Was Pflicht ist, und warum diese Menge

| Prüfung | Bedingung | Begründung |
|---|---|---|
| `OCR_PROVIDER` ist ein bekannter Wert | immer | `get_adapter` wirft sonst `ValueError` (`app/ocr/__init__.py:15`) — heute erst beim Start, aber mit einer Meldung, die die zulässigen Werte nicht nennt |
| `GCP_PROJECT_ID`, `DOCAI_PROCESSOR_ID`, `DOCAI_LOCATION` nicht leer | wenn die gewählte Engine sie braucht | leere Werte laufen heute unbemerkt bis in den `process_document`-Aufruf und kommen als `InvalidArgument` von Google zurück |
| `GOOGLE_APPLICATION_CREDENTIALS` gesetzt **und** lesbare Datei | wenn die gewählte Engine sie braucht | die Google-Bibliothek liest den Pfad selbst und wirft erst beim Client-Bau (`app/ocr/documentai.py:115-126`), also beim ersten Dokument |
| `RETRY_DELAY_MINUTES` mindestens 1 | wenn `RETRY_MAX` > 0 | bei 0 oder negativ liegt `retry_at` im Jetzt oder in der Vergangenheit (`app/repository.py:331`) — die Pause zwischen den Versuchen entfällt vollständig, und ein dauerhaft scheiterndes Dokument verbraucht alle Versuche in Sekunden, jeden mit einem bezahlten OCR-Aufruf. Kostet nur Geld, wenn überhaupt wiederholt wird: bei `RETRY_MAX` ≤ 0 wird `schedule_retry` (`app/pipeline.py:188`) nie erreicht, der Wert bliebe folgenlos |
| Paperless-Angaben nicht leer | wenn `FEATURE_PAPERLESS_SYNC` gesetzt | heute schaltet `PaperlessSync.enabled` das Feature lautlos ab (`app/paperless_sync.py:114-117`) |
| SevDesk-Token nicht leer | wenn `FEATURE_SEVDESK_EXPORT` gesetzt | dito (`app/paperless_sync.py:120-122`) |
| Anthropic-Schlüssel nicht leer | wenn `FEATURE_RECIPIENT_LLM` gesetzt | dito (`app/paperless_sync.py:130-133`) |
| Arbeitsordner und Ort der Datenbank beschreibbar | immer | siehe D4 |

**Was bewusst nicht geprüft wird, und warum genau diese Zahlen nicht.** Die erste Fassung
dieser Tabelle verlangte einen Wertebereich für `CHUNK_SIZE_PAGES` und Nicht-Negativität
für fünf Zähler. Der Pre-Flight-Scan hat beide Begründungen widerlegt, und die Prüfungen
sind daraufhin entfallen:

- `CHUNK_SIZE_PAGES` wird von `DocumentAiAdapter.page_limit`
  (`app/ocr/documentai.py:94-98`) per `min()` auf das Engine-Limit geklemmt, und jeder Wert
  ≤ 0 bedeutet dort „nimm das Engine-Limit". Ein Wert von 0 heißt also **nicht**, dass kein
  Block verarbeitet wird, und ein Wert über 15 wird **nicht** von der Engine abgelehnt. Es
  gibt nichts abzuwenden.
- `MAX_PAGES_PER_DOCUMENT`, `PROCESSED_RETENTION_DAYS`, `CHUNK_CACHE_RETENTION_DAYS` und
  `DOCAI_MAX_PAGES_PER_MINUTE` haben für ≤ 0 eine **vereinbarte** Bedeutung —
  „abgeschaltet", dokumentiert an der Definition (`app/config.py:36-44`) bzw. am
  Rate-Limit (`app/ocr/base.py:84`). Ein negativer Wert bedeutet dasselbe wie 0.
- `RETRY_MAX` ≤ 0 heißt faktisch „kein Wiederholversuch" — eine nachvollziehbare
  Einstellung, kein Fehler.

Ebenfalls nicht geprüft: Zeitfenster der Vollständigkeitserkennung, `PUID`/`PGID`, Port. Für
sie hat pydantic den Typ, und ein unsinniger, aber typgerechter Wert führt zu sichtbar
seltsamem Verhalten, nicht zu stillem Stillstand.

Übrig bleibt genau das Kriterium, nach dem die Lückenliste aufgestellt wurde: ein plausibel
aussehender Wert, der **still** scheitert oder Geld kostet. `RETRY_DELAY_MINUTES` ist der
einzige Zähler, der es erfüllt. Der Preis dieser Einengung steht im Ledger: ein vertippter
`CHUNK_SIZE_PAGES` bleibt still geklemmt, statt beim Start benannt zu werden — nachrüstbar,
falls es je störend wird.

**`GOOGLE_APPLICATION_CREDENTIALS` als Pflicht statt als Kür.** Die Google-Bibliothek
findet Zugangsdaten auch ohne diese Variable, etwa über den Metadatendienst einer
GCP-Instanz. Dieser Dienst läuft laut PRD ausschließlich im lokalen Netz in einem
Docker-Stack; dort gibt es keine zweite Quelle. Die Variable leer zu lassen ist deshalb
hier immer ein Fehler, und ihn zu benennen ist mehr wert als eine Freiheit, die in dieser
Betriebsumgebung nicht existiert. Wer den Dienst je in GCP betreibt, muss diese Prüfung
lockern — dann liegt der Fall aber vor und ist entscheidbar.

### D3 — Abbruch durch eine Ausnahme aus `lifespan`, mit vorangestelltem Protokoll

Die Beanstandungen werden als mehrzeilige Meldung über den Logger ausgegeben (`log.error`),
**dann** wird eine eigene Ausnahme geworfen. Starlette bricht den Start damit ab, uvicorn
meldet „Application startup failed" und beendet den Prozess; der Container geht mit
`restart: unless-stopped` in einen Neustartzyklus, in dem jeder Durchlauf die Begründung
erneut protokolliert.

**Warum zusätzlich protokollieren, wenn die Ausnahme die Meldung schon trägt?** Weil sie
sonst nur als Teil eines Tracebacks erscheint, zwischen Starlette- und uvicorn-Rahmen. Die
eigene Zeile steht davor, in einem Block, und ist die erste Zeile, die man beim Lesen von
`docker logs` findet.

**Alternative: `sys.exit()` direkt.** Verworfen — es umgeht den `finally`-Zweig von
`lifespan` und wäre im `TestClient` nicht prüfbar. Eine Ausnahme ist testbar, ein
Prozessabbruch nicht.

**Verifiziert am 2026-09-21, Exit-Code 3.** Ein lokal gebautes Abbild wurde ohne
Restart-Policy (`docker run` im Vordergrund, ohne `--restart`) mit absichtlich
unvollständiger ENV gestartet. `docker logs` zeigt den erwarteten Ablauf: die eigene
Protokollzeile `ERROR lector.main: Konfiguration unvollständig — der Dienst startet
nicht:` mit den drei Beanstandungen als Block, danach `ERROR: Application startup
failed. Exiting.` Der Prozess blieb nicht lauschend stehen — `$?` nach `docker run` ergab
`3`, und `docker inspect --format '{{.State.ExitCode}}'` bestätigte denselben Wert bei
`State.Status=exited`, `State.Running=false`. Die Framework-Annahme aus diesem Abschnitt
trifft zu; Aufgabe 7.2 (härterer Abbruch über Signal) war nicht nötig, `app/main.py` blieb
unverändert. Nachweis in `.superpowers/sdd/tasks/task-7-report.md`, Abschnitt 7.1.

### D4 — Zwei Stufen: erst die Angaben, dann das Dateisystem

Die Prüfung sitzt in `lifespan` unmittelbar nach `get_settings()` (`app/main.py:161`) und
läuft in zwei Stufen:

1. **Angaben** — reine Auswertung des `Settings`-Objekts, plus ein `stat` auf die
   Credentials-Datei. Keine Wirkung nach außen.
2. **`ensure_dirs()` wie heute, danach eine Schreibprobe** je Arbeitsordner und für den Ort
   der Datenbank.

Scheitert Stufe 1, ist nichts entstanden — die Zusicherung „ein abgelehnter Start
hinterlässt keine Wirkung" gilt ohne Einschränkung. Die Ordner anzulegen ist Teil von
Stufe 2 und in der Spec ausdrücklich ausgenommen; es ist beliebig wiederholbar und
verändert keinen Vorgang.

**Die Schreibprobe schreibt tatsächlich**, statt `os.access` zu befragen: Der Prozess läuft
als root, und `os.access` beantwortet die Frage für root fast immer mit „ja" — auch auf
einem schreibgeschützt eingehängten Volume. Eine Datei anzulegen und wieder zu entfernen ist
die einzige Antwort, die dem Ernstfall entspricht. Der ehrliche Preis: Gegen falsche
Berechtigungen hilft das bei root ohnehin nicht; der Fall, den die Probe wirklich fängt,
ist der **falsch eingehängte** Ordner (`:ro`, fehlendes Volume, vollgelaufenes Volume) —
und das ist der Fall, der im Compose-Stack passiert.

### D5 — Der Health-Endpunkt fragt drei vorhandene Tatsachen ab

`Worker` erhält eine Methode, die zurückgibt, welche Tasks beendet sind und ob der
Observer-Thread lebt; `Repository` eine, die eine triviale Abfrage versucht. `/healthz`
setzt beides zusammen. Der Worker wird dafür in `app.state` abgelegt — die einzige
strukturelle Ergänzung, die dieser Teil braucht.

**Warum keine eigene Buchführung** (etwa ein `last_seen`-Zeitstempel, den jede Schleife
setzt, und eine Frist, nach der sie als tot gilt)? Weil sie eine Tatsache ersetzt durch
eine Vermutung. `task.done()` ist eine Tatsache. Ein überschrittener Zeitstempel kann auch
eine lange, völlig gesunde OCR-Verarbeitung bedeuten — eine Frist, die 800 Seiten Document
AI aushält, ist so lang, dass sie keinen Fehler mehr zeitnah meldet.

**Drei Fallen, die den Weg bestimmen:**

- **`task.exception()` wirft**, wenn die Task abgebrochen wurde (`CancelledError`) — der
  Aufruf muss das abfangen, sonst reißt der Health-Endpunkt an genau dem Zustand, den er
  melden soll.
- **Die abgeschaltete Paperless-Schleife ist keine tote Schleife.** Der Worker legt diese
  Task nur an, wenn das Feature wirksam ist (`app/worker.py:85`). Der Endpunkt muss „nicht
  gestartet, weil abgeschaltet" von „gestartet und beendet" unterscheiden; sonst meldet jede
  Standardinstallation dauerhaft ungesund.
- **Die Datenbankprüfung darf nicht warten.** Alle Zugriffe teilen eine Verbindung hinter
  einem `threading.Lock` (`app/repository.py:129`). Die Prüfung nimmt den Lock mit kurzer
  Frist; läuft sie ab, gilt die Datenbank als **benutzt, nicht als kaputt** — der Endpunkt
  antwortet weiter mit Erfolg und weist die Prüfung als „beschäftigt" aus. Sonst würde ein
  Container unter Last als ungesund markiert, und der Zustandstest wäre bei genau der
  Gelegenheit unbrauchbar, bei der man ihn liest.

**Antwortform:** weiter JSON, aber je Prüfung aufgeschlüsselt; `200` bei Erfolg, `503`
sonst. `503` und nicht `500`, weil es keinen Fehler der Anfrage beschreibt, sondern eine
vorübergehend fehlende Betriebsbereitschaft — und weil ein Container-Zustandstest nur den
Statuscode auswertet, nicht den Inhalt.

Der bestehende Test `tests/test_web.py:28-30` prüft heute auf `{"status": "ok"}` und wird
von der Aufschlüsselung berührt. Er wird angepasst statt ergänzt: Die alte Zusicherung ist
genau die, die diese Change ablöst.

### D6 — Der Zustandstest des Containers läuft über Python

Kein `curl`, kein `wget`, und für einen Zustandstest ein Apt-Paket aufzunehmen, vergrößert
das Abbild für eine Aufgabe, die der ohnehin vorhandene Interpreter erledigt. Der Test
fragt `/healthz` über `urllib.request` aus der Standardbibliothek gegen `127.0.0.1` ab.

**Ohne `uv run`:** Die Standardbibliothek braucht keine Projektumgebung, und ein Zustandstest,
der das Auflösen von Abhängigkeiten voraussetzt, prüft nebenbei Dinge, die er nicht prüfen
soll.

**Ein Zustandstest ist ein Zeitfenster, kein Kommando.** Ohne Anlaufzeit wäre der Container
während des regulären Starts (Migrationen, Auflösung hängengebliebener Vorgänge) als
ungesund gemeldet. Die Anlaufzeit wird bewusst großzügig gesetzt, weil die Auflösung
beliebig viele Vorgänge betreffen kann; Intervall und Anzahl der Versuche bleiben knapp,
damit ein echter Ausfall zeitnah erscheint. Die konkreten Werte gehören in `tasks.md`.

**`depends_on` bleibt unverändert.** Andere Services auf den neuen Zustand zu verdrahten,
wäre eine Änderung am Zusammenspiel des Stacks und hat mit diesen beiden Lücken nichts zu
tun. Der Kommentar in `docker-compose.example.yml:94`, der das Fehlen eines Health-Checks
begründet, wird entsprechend berichtigt: Es gibt nun einen, er wird für `depends_on` nur
nicht herangezogen.

### D7 — Die Fixtures dokumentieren künftig, was ein startfähiger Dienst braucht

`tests/test_web.py` setzt die Document-AI-Angaben an **einer** gemeinsamen Stelle, die von
der Fixture `client` und vom zweiten Aufbau ab Zeile 672 genutzt wird. Heute setzen beide
Stellen die Verzeichnisse getrennt und wären nach dieser Change zwei Orte, an denen dieselbe
Ergänzung vergessen werden kann.

Die Credentials-Datei in Tests ist eine leere Datei in `tmp_path`. Das ist zulässig und
nicht geschludert: Die Prüfung verspricht Lesbarkeit, nicht Gültigkeit (D2). Ein Test, der
eine echte Dienstkonto-Datei bräuchte, würde eine Zusicherung prüfen, die die Spec
ausdrücklich nicht macht.

## Risks / Trade-offs

**Eine bestehende Installation kann nach dem Rollout nicht mehr starten** → Das ist die
Absicht, aber es trifft den Anwender ohne Vorwarnung, wenn seine `.env` eine Angabe
vermisst, die bisher nur nie gebraucht wurde (etwa `FEATURE_PAPERLESS_SYNC=true` ohne
Token — heute lautlos wirkungslos, künftig ein Startfehler). Mitigation: Der Migrationsplan
unten macht den Abgleich der `.env` zum ersten Schritt, vor dem `pull`.

**uvicorn könnte bei einer Ausnahme in `lifespan` lauschend hängen bleiben** → Dann wäre
das Ergebnis dieser Change das Gegenteil ihres Zwecks. Mitigation: eigene
Verifikationsaufgabe am echten Container; fällt sie negativ aus, muss der Abbruch anders
erzwungen werden (Signal an den eigenen Prozess), und das ist vor dem Abschluss zu
entscheiden, nicht danach.

**Die Schreibprobe fängt als root keine Berechtigungsfehler** → Ehrlich benannt in D4: Sie
fängt falsch eingehängte und vollgelaufene Volumes. Eine Prüfung, die mehr verspricht, wäre
eine Prüfung, die als root nicht zu haben ist.

**Der Zustandstest startet nichts neu** → Dockers `HEALTHCHECK` markiert nur; `unhealthy`
wird in `docker ps` sichtbar, bewirkt aber keinen Neustart (das täte nur Swarm oder ein
Zusatzdienst). Ohne neue Abhängigkeit nicht anders zu haben; bewusst so, und im Proposal
als Nicht-Ziel benannt.

**Ein zu strenger Health-Endpunkt ist schlimmer als ein zu milder** → Ein Container, der
unter Last fälschlich als ungesund gilt, verleitet dazu, den Zustandstest abzuschalten, und
dann ist auch der echte Fall nicht mehr sichtbar. Darum D5: Zeitüberschreitung beim Lock
gilt als beschäftigt, nicht als defekt, und fremde Dienste zählen überhaupt nicht.

**Ein Rollback ist folgenlos** → Diese Change legt keine Spalte an, führt keinen neuen
Zustandswert ein und schreibt keine Daten. Anders als bei `seitenobergrenze-mit-freigabe`
gibt es vor dem Zurückrollen nichts zu entscheiden; das alte Abbild startet wieder wie
zuvor — inklusive der wiederhergestellten Lücken.

## Migration Plan

1. **Vor dem Rollout, am NAS:** die laufende `.env` gegen die neue Tabelle in
   `feature-documentation/konfiguration.md` abgleichen. Besonders die Feature-Schalter: Ein
   gesetzter Schalter ohne die zugehörigen Angaben ist nach dieser Change ein Startfehler.
2. `docker compose pull lector && docker compose up -d lector`.
3. `docker compose ps lector` — der Container muss `healthy` erreichen, nicht nur `running`.
   Das ist der erste Rollout, bei dem diese Unterscheidung überhaupt existiert.
4. Fällt der Start aus, nennt `docker compose logs lector` jede beanstandete Angabe in einem
   Block; nach der Korrektur genügt ein Neustart.
5. **Rollback:** voriges Abbild ziehen. Keine Datenbank-, keine Zustandsüberlegung (siehe
   oben).
