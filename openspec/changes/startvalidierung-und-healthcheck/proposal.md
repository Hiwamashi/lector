# Proposal

## Why

Zwei der offenen Lücken aus `baseline-specs-kernpipeline` haben dieselbe Ursache: **Der
Dienst behauptet Betriebsbereitschaft, die er nicht hat.** Eine unvollständige
Konfiguration fällt erst beim ersten Dokument auf, und `/healthz` antwortet `ok`, solange
der Prozess überhaupt antwortet — unabhängig davon, ob noch etwas verarbeitet wird.

Beide Lücken sitzen an derselben Naht, der Startsequenz in `lifespan`
(`app/main.py:160-186`), und sie ergänzen sich: Die Validierung deckt ab, was **vor** dem
Start feststellbar ist, der Health-Endpunkt das, was **danach** zerbrechen kann. Getrennt
umgesetzt müsste die Naht zweimal angefasst werden.

Der Schaden ist heute belegbar und nicht theoretisch. Fehlt `GCP_PROJECT_ID` oder
`DOCAI_PROCESSOR_ID`, kommt der Fehler nicht aus der Konfiguration, sondern als
`InvalidArgument` von Google — beim ersten echten Verarbeitungsversuch. Dieser Fehler
läuft in die reguläre Retry-Logik (`app/pipeline.py:226`), also **drei Versuche à 15
Minuten**, bevor der Vorgang auf `failed` geht und die Ursache in `error_message` lesbar
wird. Eine Fehlkonfiguration, die beim Start in einer Zeile benennbar wäre, kostet so 45
Minuten und opfert das erste Dokument.

## What Changes

**1. Pflichtangaben werden beim Start geprüft, und der Dienst startet ohne sie nicht.**

- Die Prüfung läuft in der Startsequenz, bevor irgendein Seiteneffekt entsteht (vor
  `ensure_dirs()`, der Datenbank, dem Worker).
- Gemeldet werden **alle** Beanstandungen zusammen, nicht die erste. Wer drei Werte
  vergessen hat, soll das in einem Durchgang erfahren und nicht in drei Neustarts.
- Welche Angabe Pflicht ist, hängt von den gewählten Schaltern ab: Die
  Document-AI-Angaben sind Pflicht, weil `OCR_PROVIDER` auf `documentai` steht (der
  Standardwert) — nicht unbedingt. Dasselbe Muster für die Paperless-Schalter.
- **BREAKING (Betrieb, nicht API):** Eine Instanz, die heute mit unvollständiger
  Konfiguration startet und stillsteht, startet nach dieser Change nicht mehr. Das ist die
  Absicht; es kann eine bestehende Installation beim nächsten Neustart anhalten, deren
  Fehlkonfiguration bisher nur niemandem aufgefallen ist.

**2. Fehlkonfigurierte Zusatz-Features bleiben nicht stumm.**

Heute prüft `PaperlessSync.enabled` (`app/paperless_sync.py:114`) die Kombination aus
Feature-Schalter **und** URL **und** Token. Fehlt bei gesetztem `FEATURE_PAPERLESS_SYNC`
das Token, ist die Sync-Schleife lautlos abgeschaltet — kein Fehler, keine Warnung. Ein
gesetzter Feature-Schalter ohne die zugehörigen Angaben gilt künftig als
Konfigurationsfehler und bricht den Start ab. Ein **nicht** gesetzter Schalter bleibt
folgenlos, auch wenn die zugehörigen Angaben fehlen.

**3. `/healthz` prüft, was es behauptet.**

- Datenbank über eine triviale Abfrage erreichbar.
- Alle Worker-Tasks leben. Die Task-Liste liegt bereits vor (`app/worker.py:68`), wird
  heute aber nie befragt.
- Der Watchdog-Observer-Thread lebt.
- Der Endpunkt **meldet**, er heilt nicht. Die Loops fangen bereits jede Ausnahme pro
  Durchlauf ab (`app/worker.py:151,177,188,208,217`); eine wirklich beendete Task ist
  deshalb ein struktureller Fehler und soll auffallen, statt weggeräumt zu werden.
- Antwortform bleibt JSON, wird aber je Prüfung aufgeschlüsselt. Ungesund antwortet mit
  `503`, damit ein Container-Healthcheck ohne Body-Auswertung auskommt.

**4. Dockerfile und Compose-Vorlage erhalten einen `HEALTHCHECK`.**

Das Base-Image `python:3.12-slim` enthält **weder `curl` noch `wget`** (verifiziert). Der
Healthcheck läuft deshalb über den ohnehin vorhandenen Python-Interpreter, statt ein
Apt-Paket allein für diesen Zweck aufzunehmen.

### Ausdrücklich nicht in dieser Change

- **Kein Wartezustand für Fehlkonfiguration.** Abgewogen und verworfen: Der Dienst würde
  laufen, ohne zu arbeiten — genau das Muster, das diese Lücke beseitigen soll. Entschieden
  zugunsten des harten Abbruchs.
- **Keine Selbstheilung** gestorbener Tasks (siehe oben).
- **Kein Neustart des Containers durch den Healthcheck.** Dockers `HEALTHCHECK` markiert
  nur, es startet nichts neu (das tut nur Swarm bzw. ein Zusatzdienst). `unhealthy` wird
  in `docker ps` sichtbar; mehr ist ohne neue Abhängigkeit nicht zu haben.
- **Keine Erreichbarkeitsprüfung gegen Google, Paperless oder SevDesk** — weder beim Start
  noch im Healthcheck. Beim Start würde sie Kosten und Laufzeit in die Startsequenz holen
  und den Dienst von der Verfügbarkeit Dritter abhängig machen; im Healthcheck würde ein
  Aussetzer bei Paperless den Container als ungesund markieren, obwohl Lector einwandfrei
  arbeitet. Geprüft wird, dass die Angaben **vorhanden und plausibel** sind, nicht dass sie
  **gültig** sind.
- **`LOG_LEVEL` über ENV** bleibt außen vor (heute fest auf `INFO`,
  `app/main.py:34`) — eine eigenständige Abweichung von der ENV-Vorgabe, die als neuer
  Eintrag in die Lückenliste geht.

## Capabilities

### New Capabilities

Keine. Beide Lücken betreffen bestehende Requirements.

### Modified Capabilities

- `verarbeitungs-lebenszyklus`: Das Requirement „Laufzeitparameter kommen ausschließlich
  aus Umgebungsvariablen" sagt heute nur, **woher** die Parameter kommen, und dass der
  Dienst ohne Konfigurationsdatei mit Standardwerten startet. Es wird um die Zusicherung
  erweitert, dass unvollständige oder unbrauchbare Angaben den Start **verhindern** und
  vollständig benannt werden. Das Szenario „Betrieb ohne Konfigurationsdatei" bleibt gültig
  und wird geschärft: Standardwerte greifen weiterhin, wo es welche gibt — Pflichtangaben
  ohne sinnvollen Standard sind davon ausgenommen.
- `verarbeitungs-historie`: Das Requirement „Der Dienst bietet einen Health-Endpunkt"
  fordert heute, dass der Dienst „mit einem Erfolgsstatus" antwortet — eine Zusicherung,
  die der heutige Code wörtlich erfüllt und die genau deshalb wertlos ist. Es wird zu einer
  Aussage über die Betriebsbereitschaft der Laufzeitbestandteile umformuliert, samt
  Zusicherung, dass die Container-Ebene diesen Endpunkt nutzt.

## Impact

**Code:**

- `app/config.py` — neue Validierung (Pflichtangaben abhängig von den gesetzten Schaltern,
  Lesbarkeit der Credentials-Datei, Beschreibbarkeit der Arbeitsverzeichnisse); die
  `Settings`-Felder selbst bleiben unverändert, weil jedes einen Standardwert trägt und
  pydantic sonst die Fehlermeldung diktieren würde statt dieser Change.
- `app/main.py` — Aufruf der Validierung als erster Schritt in `lifespan`; `/healthz`
  (Zeile 237) wird zur echten Prüfung; die `Worker`-Instanz muss dafür in `app.state`
  abgelegt werden (heute nicht der Fall, `app/main.py:174-177`).
- `app/worker.py` / `app/repository.py` — je eine abfragbare Zustandsaussage
  („leben meine Tasks und der Observer?", „ist die Datenbank benutzbar?"). Kein neues
  Verhalten, nur das Sichtbarmachen vorhandener Tatsachen.

**Betrieb:** `Dockerfile` (neuer `HEALTHCHECK`), `docker-compose.example.yml`
(`healthcheck`-Block am `lector`-Service). Die nicht versionierte NAS-Compose-Datei zieht
der Anwender nach; `depends_on`-Verdrahtung anderer Services auf den neuen Zustand ist
**nicht** Teil dieser Change.

**Tests — hier sitzt das Risiko dieser Change:** Die Fixture `client`
(`tests/test_web.py:11-25`) und der zweite Aufbau ab `tests/test_web.py:672` durchlaufen
den echten `lifespan`, setzen aber **keine** Document-AI-Variablen. Sie funktionieren heute
nur, weil nichts validiert wird. Mit der Validierung brechen sie geschlossen — rund 33
Tests. Die Behebung ist klein (die Fixtures setzen die Werte künftig mit), der Effekt
erwünscht: Die Fixture dokumentiert danach, was ein startfähiger Dienst braucht. Tests
außerhalb `test_web.py` konstruieren `Settings(...)` direkt und sind nicht betroffen.

**Doku:** `feature-documentation/konfiguration.md` (welche Angabe unter welcher Bedingung
Pflicht ist), eine neue Feature-Datei zum Startverhalten und zum Health-Endpunkt,
`.env.example`, `prd/PROGRESS.md` sowie die Lückentabelle in
`openspec/changes/baseline-specs-kernpipeline/proposal.md`.

**Nicht betroffen:** Verarbeitungspipeline, Datenmodell (keine Migration), Weboberfläche
außer dem Health-Endpunkt, Abhängigkeiten (kein neues Paket, kein zusätzliches
Apt-Paket).
