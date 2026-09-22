# Startvalidierung und Health-Check

**Module:** `app/config.py` (`validate_settings`, `ConfigurationRejectedError`,
`_ENGINE_REQUIRED_FIELDS`, `_env_name`, `_is_readable_file`), `app/main.py`
(`lifespan`, `_reject_startup`, `_check_writable_paths`, `_health_status`, `/healthz`),
`app/worker.py` (`TaskState`, `background_task_states`, `observer_state`),
`app/repository.py` (`DatabaseHealthState`, `check_health`), `Dockerfile`,
`docker-compose.example.yml` (`healthcheck`-Block am `lector`-Service).

## Wozu

Vor dieser Funktion konnte die Konfiguration nicht scheitern: `Settings` ist eine
`pydantic_settings.BaseSettings` mit einem Standardwert für jedes Feld — ein fehlendes
`GCP_PROJECT_ID` war kein Validierungsfehler, sondern der leere String. Die Lücke fiel
erst beim ersten Dokument auf, als Google-API-Fehler. Ebenso meldete `/healthz` bisher
unbedingt `{"status": "ok"}`, unabhängig davon, ob der Worker überhaupt lief.

## Startverhalten

Ablauf in `lifespan` (`app/main.py`): `get_settings()` → `validate_settings()` →
`ensure_dirs()` → Schreibprobe → `Repository(...)` → … in zwei bewusst getrennten Stufen:

1. **Angaben prüfen** (`validate_settings`) — reine Auswertung des `Settings`-Objekts plus
   ein Lesetest der Credentials-Datei. Keine Wirkung nach außen.
2. **Dateisystem prüfen** — `ensure_dirs()` legt die Arbeitsordner an, danach schreibt
   `_check_writable_paths()` tatsächlich eine Testdatei in jeden der vier Arbeitsordner und
   in das Verzeichnis von `DB_PATH` (`tempfile.NamedTemporaryFile`) und entfernt sie wieder.

Scheitert Stufe 1, ist **nichts** entstanden. Die Schreibprobe sitzt bewusst **vor** dem Bau
des `Repository` — dort entsteht die Datenbankdatei. Läge die Probe danach, wäre die
Zusicherung „ein abgelehnter Start hinterlässt keine Wirkung" für den Ordner-Fehlerfall
gebrochen.

**Warum tatsächlich geschrieben wird, statt `os.access` zu befragen:** Der Prozess läuft im
Container als root, und `os.access` beantwortet die Frage für root fast immer mit „ja" —
auch auf einem schreibgeschützt eingehängten Volume. Ehrlich über die Reichweite: Gegen
falsche Berechtigungen hilft das bei root nicht; der Fall, den die Probe fängt, ist der
**falsch eingehängte** Ordner (`:ro`, fehlendes Volume, vollgelaufenes Volume) — und das ist
der Fall, der im Compose-Stack tatsächlich passiert.

### Warum ein harter Abbruch statt eines Wartezustands

Der Dienst hat keine Zwischenform zwischen „läuft" und „läuft nicht" — er nimmt entweder
Arbeit an oder er startet nicht (kein `/readyz`, kein Feld, das später abgefragt würde).
Ein Wartezustand hätte einen dritten Prozesszustand eingeführt, den jede spätere Prüfung
kennen müsste, für einen Fall, der ohnehin nur durch eine korrigierte `.env` und einen
Neustart behoben wird — der Preis dafür stünde in keinem Verhältnis zum Nutzen. `lifespan`
wirft stattdessen `ConfigurationRejectedError` (`app/config.py`); Starlette bricht den
Start ab, uvicorn meldet „Application startup failed" und beendet den Prozess. Bei
`restart: unless-stopped` geht der Container in einen Neustartzyklus, in dem jeder
Durchlauf die Begründung erneut protokolliert.

### Prüfumfang

Details, welche Angabe unter welcher Bedingung Pflicht ist und was bewusst nicht geprüft
wird, stehen in [konfiguration.md](konfiguration.md#startvalidierung-was-beim-start-pflicht-ist).
Kurzfassung: `OCR_PROVIDER` (bekannter Wert, case-insensitiv), die Engine-Pflichtangaben
der gewählten Engine, `GOOGLE_APPLICATION_CREDENTIALS` (gesetzt und lesbar),
`RETRY_DELAY_MINUTES` (≥ 1) und — falls der jeweilige Feature-Schalter gesetzt ist — die
Paperless-, SevDesk- bzw. Anthropic-Angaben. Jede Beanstandung nennt den **ENV-Namen**
(über `_env_name()` aus dem pydantic-Alias gelesen, nicht als String wiederholt), unter dem
die Angabe gesetzt wird — nicht den Feldnamen der Klasse.

`validate_settings()` wirft selbst nicht und bricht nicht bei der ersten Beanstandung ab:
Sie sammelt alle in einer Liste, damit der Aufrufer sie in einem Durchgang meldet.

**Typfehler sind eine eigene, vorgelagerte Klasse.** Ein Wert, der nicht dem verlangten Typ
entspricht (z. B. `RETRY_MAX=abc`), lässt bereits `get_settings()` mit einer
pydantic-`ValidationError` scheitern — **bevor** `validate_settings()` überhaupt läuft.
Pydantic nennt dabei den Alias (`RETRY_MAX`), nicht den Feldnamen, sammelt aber nur die
eigenen Typfehler in einem Durchgang, nicht gemeinsam mit den Beanstandungen aus
`validate_settings()`: Ein gleichzeitiger Typfehler und eine fehlende Pflichtangabe werden
so über zwei Neustarts sichtbar, nicht über einen.

### Die Ablehnung wird zweimal sichtbar

`_reject_startup()` protokolliert zuerst alle Beanstandungen als zusammenhängenden Block
über `log.error`, dann wirft sie `ConfigurationRejectedError`. Trüge nur die Ausnahme die
Meldung, erschiene sie allein im Traceback zwischen Starlette- und uvicorn-Rahmen; die
eigene Protokollzeile ist die erste, die man beim Lesen von `docker logs` findet.

**Verifiziert am echten Container (2026-09-21, Exit-Code 3):** Ein Abbild wurde ohne
Restart-Policy mit absichtlich unvollständiger ENV gestartet. Der Prozess endete
tatsächlich — `docker run` kehrte mit `EXITCODE:3` zurück, `docker inspect` bestätigte
`ExitCode=3`, `Status=exited`, `Running=false`. Kein lauschendes Hängenbleiben.

## Health-Endpunkt (`GET /healthz`)

`_health_status()` (`app/main.py`) baut die Prüfungen rein lesend aus den fertigen
Zustandsauskünften von `Worker` und `Repository` zusammen — keine der aufgerufenen
Methoden verändert einen Zustand, startet beendete Arbeit neu oder stößt einen Vorgang an.
Geprüft werden sieben Einträge: die vier immer gestarteten Hintergrundarbeiten (`scan`,
`process`, `retry`, `retention`), die Paperless-Sync-Schleife, der Watchdog-Observer des
Eingangsordners und die Datenbank.

### Antwortform

Ein JSON-Objekt mit einem Eintrag `{"state": ..., "error": ...}` je Prüfung, Statuscode
`200` nur wenn alle Prüfungen gesund sind, sonst `503` (nicht `500`, weil keine
fehlerhafte Anfrage vorliegt, sondern eine vorübergehend fehlende Bereitschaft — und weil
ein Container-Zustandstest ohnehin nur den Statuscode auswertet). Beispiel eines
Eintrags, wenn eine Hintergrundarbeit gestorben ist (aus der Verifikation, siehe unten):

```json
"retry": {"state": "stopped", "error": "RuntimeError: ..."}
```

### Zwei Zustände gelten ausdrücklich als gesund

Das ist die tragende Entscheidung des Endpunkts, an den jeweiligen Enums verankert
(`TaskState.healthy`, `DatabaseHealthState.healthy`), damit sie nicht an jeder
Verbrauchsstelle erneut abgeleitet werden müssen:

- **`not_started`** für die Paperless-Sync-Schleife bei abgeschaltetem
  `FEATURE_PAPERLESS_SYNC`. Jede Standardinstallation läuft mit diesem Schalter auf
  `false` — würde `not_started` als krank gelten, meldete **jede** solche Installation
  dauerhaft `503`.
- **`busy`** für die Datenbank: `check_health()` (`app/repository.py`) nimmt den
  geteilten Lock nur mit einer kurzen Frist (0,2 s); wird er nicht erhalten, gilt die
  Datenbank als **benutzt**, nicht als kaputt. Würde das als krank gelten, meldete sich
  ein Container unter Last selbst als ungesund — genau in dem Moment, in dem man den
  Zustand liest.

Die Enum-Werte selbst (`running`, `stopped`, `not_started`, `usable`, `busy`, `unusable`)
sind **englisch**, weil sie unverändert in der JSON-Antwort landen, die auch
Überwachungswerkzeuge lesen.

### Was der Endpunkt bewusst nicht tut

Er beobachtet, ohne einzugreifen: keine Selbstheilung, keine eigene Buchführung mit
Zeitstempeln, keine Erreichbarkeitsprüfung fremder Dienste (Texterkennung, Paperless,
SevDesk). Begründung gegen Selbstheilung: Jede Worker-Schleife fängt ihre Fehler bereits
pro Durchlauf ab — eine wirklich beendete Task ist deshalb ein struktureller Fehler, der
auffallen soll, statt weggeräumt zu werden. Begründung gegen Zeitstempel: `task.done()`
ist eine Tatsache, ein überschrittener Zeitstempel wäre eine Vermutung und könnte auch
eine gesunde, lange OCR-Verarbeitung bedeuten.

## Zustandstest des Containers (`HEALTHCHECK`)

`Dockerfile` und `docker-compose.example.yml` (Block am `lector`-Service) tragen denselben
Zustandstest: `--interval=30s --timeout=5s --start-period=120s --retries=3`, ausgeführt
über `python -c` mit `urllib.request` statt über `curl`:

```
CMD ["python", "-c", "import urllib.request; assert urllib.request.urlopen('http://127.0.0.1:8001/healthz', timeout=5).status == 200"]
```

**Warum über den Python-Interpreter statt über `curl`:** Das Basis-Abbild
(`python:3.12-slim`) enthält **weder `curl` noch `wget`**; ein Apt-Paket allein für den
Zustandstest aufzunehmen würde das Abbild für etwas vergrößern, das der ohnehin
vorhandene Interpreter erledigt. Ohne `uv run`, weil die Standardbibliothek keine
Projektumgebung braucht und ein Zustandstest nicht nebenbei das Auflösen von
Abhängigkeiten prüfen soll.

**Die Zeitwerte sind Abwägungen:** Die Anlaufzeit (`--start-period=120s`) ist großzügig,
weil der Start Migrationen und die Auflösung hängengebliebener Vorgänge
(`resolve_stale_processing`) umfasst, die beliebig viele Vorgänge betreffen kann. Die
Zeitgrenze (`--timeout=5s`) liegt **über** der 0,2-Sekunden-Frist der Datenbankprüfung —
darunter schlüge der Test bei jeder gleichzeitigen Datenbanknutzung fälschlich fehl, also
genau unter Last. Intervall und Versuche bleiben knapp, damit ein echter Ausfall zeitnah
sichtbar wird.

### Ein Detail, das die naheliegende Lesart widerlegt

Die Verifikation am Container hat gezeigt: Der Container erreicht `healthy` **nach rund 20
Sekunden**, nicht erst nach Ablauf der Anlaufzeit von 120 Sekunden. Das ist korrektes
Docker-Verhalten und kein Fehler: `--start-period` verzögert nicht den ersten erfolgreichen
Check, sondern schont nur die Zählung der Fehlversuche — innerhalb der Anlaufzeit führt ein
fehlgeschlagener Test noch nicht zu `unhealthy`. Die naheliegende Lesart von „Anlaufzeit
120 s" ist „der Container gilt zwei Minuten lang nicht als gesund" — das ist falsch, und
wer beim Rollout darauf wartet, hält einen funktionierenden Dienst für kaputt.

Belegte Zustandsfolge eines Containers, dessen Hintergrundarbeit mitten im Betrieb stirbt
(Verifikation vom 2026-09-21): `starting` → `healthy` (nach ~20 s) → `unhealthy` (rund 3,5
Minuten später, nach Intervall mal Versuche).

### Was der Zustandstest nicht bewirkt

`depends_on` bleibt unverändert, kein `condition: service_healthy` — andere Services auf
den neuen Zustand zu verdrahten wäre eine eigene Änderung am Zusammenspiel des Stacks.
Und: Dockers `HEALTHCHECK` **markiert nur** — er startet nichts neu (das täte nur Swarm
oder ein Zusatzdienst). `unhealthy` wird in `docker ps`/`docker compose ps` sichtbar; mehr
ist ohne neue Abhängigkeit nicht zu haben.

## Vor einem Rollback

Folgenlos: keine neue Spalte, kein neuer Zustandswert, keine Datenmigration. Das alte
Abbild startet wieder wie zuvor — inklusive der wiederhergestellten Lücken (Konfiguration
kann nicht scheitern, `/healthz` meldet unbedingt `ok`).
