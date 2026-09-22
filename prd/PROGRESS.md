# Entwicklungsfortschritt — Lector

> Fortlaufend gepflegter Stand der MVP-Umsetzung (siehe `PRD_Lector.md`).
> Legende: ✅ umgesetzt · 🚧 in Arbeit · ⬜ offen

**Stand:** 2026-09-18

## Getroffene Entscheidungen (vormals offene Fragen)

1. **Watch-Folder-Vollständigkeit:** kombiniert — Rename aus `.tmp`/`.part`/`.crdownload` bevorzugt, Größenstabilität über N Sekunden als Fallback.
2. **Bereits durchsuchbare PDFs:** Es laufen **immer** alle PDFs durch Document AI (einheitliches Ergebnis).
3. **Document-AI-Throttling:** seitenbasiertes Rate-Limit im Worker (`DOCAI_MAX_PAGES_PER_MINUTE`).

## MVP-Features

| Feature | Status |
|---|---|
| Projektgerüst, ENV-Config | ✅ |
| SQLite-Historie (`documents`, `document_events`) | ✅ |
| Watch-Folder + Vollständigkeitsprüfung | ✅ |
| Serielle Verarbeitungs-Queue / Worker | ✅ |
| Format-Erkennung & Routing | ✅ |
| E-Rechnungs-Bypass (deterministisch) | ✅ |
| Bildvorverarbeitung (Deskew/Kontrast; Orientierung via Document AI) | ✅ |
| OCR-Adapter-Interface | ✅ |
| Document-AI-Adapter (Region eu) | ✅ |
| Chunking ≤15 Seiten | ✅ |
| Sandwich-PDF (Bild + Textlayer) | ✅ |
| Ablage nach consume (UID/GID 1000) | ✅ |
| Datei-Lifecycle (processed/error) | ✅ |
| Auto-Retry (15 min, max 3) | ✅ |
| Retention-Job (30 Tage) | ✅ |
| Web-UI Dashboard + Historie + Detail | ✅ |
| Live-Updates via SSE | ✅ |
| Docker / Compose-Integration | ✅ |

**MVP vollständig umgesetzt.** `ruff` sauber, Docker-Image baut und startet.
Feature-Doku unter `feature-documentation/`.

## Zusatz-Feature: Paperless-Integration (GiroCode & SevDesk) — entkoppelt

Unabhängig vom OCR-Veredelungspfad. Lector liest Rechnungen über den Paperless-Dokumententyp,
erzeugt GiroCodes und exportiert getaggte Belege nach SevDesk; Status wird ans Paperless-
Dokument zurückgeschrieben. Standardmäßig deaktiviert (`FEATURE_PAPERLESS_SYNC=false`).

| Feature | Status |
|---|---|
| Paperless-REST-Client (lesen/zurückschreiben, `app/paperless.py`) | ✅ |
| GiroCode-Extraktion E-Rechnung (UBL/CII) + OCR-Heuristik (`app/girocode.py`) | ✅ |
| EPC069-12-QR-Erzeugung (segno, SVG) | ✅ |
| SevDesk-Beleg-Upload (`app/sevdesk.py`) | ✅ |
| Periodischer Sync + UI-Aktionen (`app/paperless_sync.py`, Worker-Loop) | ✅ |
| Neue Tabellen `paperless_invoices` / `invoice_events` | ✅ |
| Rückschrieb: Custom Fields + Tags + Notiz (Auto-Anlage) | ✅ |
| Web-UI „Rechnungen" + GiroCode-Anzeige + Aktionen + SSE | ✅ |
| Rechnungs-UI: Dokumentdatum, sortierbare Spalten, Dokumentvorschau/-Sprung | ✅ |
| Empfänger-Zuordnung pro Dokument (Paperless select-Feld, `/empfaenger`) | ✅ |
| KI-Empfänger-Vorschlag (Anthropic, `app/recipient_llm.py`) — einzeln + Batch, Auto-Apply | ✅ |
| Tabelle `document_recipients` (KI-Vorschlag-Cache) | ✅ |
| Batch-Lauf: Menge wählbar, Retry mit Backoff, Fortschritt + Abbruch | ✅ |

146 Tests grün. `ruff` sauber.

**Fix-Runde Fortschrittsanzeige (2026-09-18):** Der Zähler stand still und der
Fortschrittsbalken fehlte. Ursache war **nicht** die Live-Logik, sondern das Ausliefern der
statischen Dateien: `/static/app.css` und `/static/app.js` gingen ohne `Cache-Control` und
ohne Versionsangabe raus, Browser cachten heuristisch und revalidierten nicht — frisches
HTML traf auf altes CSS/JS, und mehrere vorangegangene Fixes an `app.js` sind nie im Browser
angekommen. `base.html` bindet die Dateien jetzt über `static_url()` mit Inhalts-Fingerabdruck
ein. Ergänzend hängt der Fortschritt nicht mehr allein an SSE: solange ein Lauf läuft
(`data-batch-running`), fragt `app.js` alle 2 s von sich aus nach — gepufferte
`text/event-stream`-Verbindungen hinter einem Reverse Proxy wirken sonst gesund, während
nichts mehr ankommt. Die Pause liegt dabei **zwischen** den Zyklen: Ein festes
`setInterval` ließe bei Antwortzeiten oberhalb der Pause jeden Zyklus vom nächsten
überholen, der Veralterungsschutz verwürfe dann jede Antwort — die Anzeige stünde dauerhaft
still. Und jeder Fragment-Request hat eine Frist von 15 s: `fetch` bricht von sich aus nie
ab, ein hängender Request hielte den Takt sonst für immer an. Beides im Review gefunden,
beides mit Regressionstest belegt (Gegenprobe gegen die jeweils fehlerhafte Fassung
durchgeführt).
Der Balken zeigt jetzt die drei Ausgänge (verarbeitet / übersprungen / fehlgeschlagen) als
farbige Segmente mit Legende und einem Puls an der Füllkante als Lebenszeichen.

(Fix-Runde nach Schlussreview: leeres/unlesbares Mengenfeld
fällt auf die Vorbelegung statt auf das Maximum zurück, Start-Button bleibt bei einem
Paperless-Aussetzer nutzbar, SSE-Drossel greift auch über den Einzel-`rec:<id>`-Pfad,
Ausnahmen vor der Dokumentschleife und der leere Empfänger-Feld-Fall setzen `aborted_reason`
statt wortlos zu enden, Anzeige benennt „ohne gesetzten Empfänger" statt eine 1:1-Deckung mit
der Arbeitsmenge zu suggerieren, Batch-Task wird beim Shutdown abgebrochen statt auf der
geschlossenen DB-Verbindung weiterzulaufen, `retry-after` ist auf 60 s gedeckelt, übersprungene
Dokumente zählen sichtbar und der offene Rest berücksichtigt auch abgebrochene Läufe.)
Feature-Doku unter `feature-documentation/paperless-integration/`
(neu: `rechnungs-ui.md`, `empfaenger-zuordnung.md`).
Empfänger-Feature **live gegen die Paperless-Instanz verifiziert**: select-Feld-Auflösung,
`custom_field_query`-Filter „ohne Empfänger" (1504 Dok.), Setzen/Leeren des Feldes (reversibel)
und KI-Vorschlag (korrekte Zuordnung bzw. „unbekannt") end-to-end getestet. Dokumentdatum (`created`) und Vorschau-Endpoint
(`/preview/`, liefert `application/pdf` mit `X-Frame-Options: SAMEORIGIN`) gegen die
Live-Paperless-Instanz verifiziert — daher wird die Vorschau über einen Lector-Proxy
ausgeliefert.

**End-to-End live verifiziert (2026-09-18):** gegen die echte Paperless-Instanz
(Token/URL/Dokumententyp-Name) und gegen ein echtes SevDesk-Konto (API-Token,
Systemversion 2.0 für E-Rechnungs-Belege).

## Zusatz-Feature: Image-Deployment über Scaleway Container Registry

Das Image wird nicht mehr auf dem NAS gebaut, sondern als Multi-Arch-Image
(amd64 + arm64) aus `rg.nl-ams.scw.cloud/krinke-dockersolutions` gezogen. Build
und Push laufen auf dem Entwicklungsrechner, der Rollout aufs NAS bleibt ein
getrennter manueller Schritt.

| Feature | Status |
|---|---|
| Push-Skript Multi-Arch amd64+arm64 als Manifest-Liste (`scripts/push-image.sh`) | ✅ |
| Tags `latest` + `git-<sha>`, Index nach dem Push verifiziert | ✅ |
| Gate: kein Push ohne Registry-Login | ✅ |
| Gate: kein Push aus schmutzigem Worktree (SHA-Tags reproduzierbar) | ✅ |
| Compose auf Registry-Image umgestellt, `build:` deaktiviert + Regressionstest | ✅ |
| arm64-Lauffähigkeit lokal belegt (Container gestartet, HTTP-Antwort) | ✅ |
| Rollout auf dem NAS (`compose pull` + `up -d`) | ✅ vom Anwender durchgeführt (2026-09-18) |

## Im Betrieb verifiziert (2026-09-18)

Alle zuvor offenen Verifikationspunkte sind vom Anwender geschlossen:

- **End-to-End mit echtem Document AI:** Der OCR-Weg läuft mit echten GCP-Credentials
  (`GCP_PROJECT_ID`, `DOCAI_PROCESSOR_ID`, Service-Account-JSON) — nicht mehr nur
  Fake-Adapter und E-Rechnungs-Bypass.
- **Registry-Deployment:** `docker compose pull lector && docker compose up -d lector`
  auf dem NAS (`Teams/Docker/paperless-ngx-stack`) ausgeführt, Dienst auf Port 8001 erreichbar.
- **Paperless & SevDesk:** Sync und Beleg-Upload gegen die produktiven Konten bestätigt.

## Zusatz-Feature: UI-Politur (2026-09-19)

Bewusst kein Redesign: Layout, Navigation, Informationsarchitektur, Routen und der
Akzentfarbton bleiben unveraendert. Ergaenzt wurde, was gefehlt hat.

- **Dunkel-Modus** ueber `@media (prefers-color-scheme: dark)`, ausschliesslich als
  Tokenblock. Kein Umschalter, keine ENV-Variable — die Systemeinstellung entscheidet.
  Zwei neue Token: `--surface-alt` (vorher als `#fafbfc` fest verdrahtet) und
  `--on-accent` (Weiss auf hellem Akzent waere im Dunkeln unlesbar gewesen, 2.4:1).
  Kontraste geprueft, alle ueber WCAG AA.
- **Aufleuchten geaenderter Zeilen:** Jede Listenzeile traegt `data-row-id` und `data-rev`;
  `app.js` vergleicht die Signaturen vor und nach dem Fragment-Tausch und markiert nur
  tatsaechlich geaenderte oder neue Zeilen. Vorher aktualisierte sich die Liste unbemerkt.
- **Fortschrittsbalken in der Listenzeile**, bewusst nur bei `status = processing` —
  dieselbe Ueberlegung wie bei der Batch-Karte: Bewegung soll etwas bedeuten.
- **Aktive Statuskachel** (`aria-current`), **`:focus-visible`** fuer Tastaturbedienung,
  **`:active`**-Rueckmeldung auf Schaltflaechen, **Leerzustaende mit Hinweis** statt
  einer blossen Feststellung.
- **Nebenbei behoben:** Der Zeitstempel im Verlauf der Detailansicht lief als einziger
  ohne `| fmt_dt` und stand roh da.

Tests: 155 gruen. Neu abgedeckt sind das Zeilen-Aufleuchten (vier Faelle im
Node-Harness, u. a. dass eine nur verschobene Zeile NICHT aufleuchtet) sowie
Fortschrittsbalken und Zeilensignatur im Web-Test.

## Zusatz-Feature: Recovery unterbrochener Verarbeitung (2026-09-20)

Die erste der acht benannten Lücken in `baseline-specs-kernpipeline` ist geschlossen:
**Nach einem Prozessabbruch bleibt kein Vorgang dauerhaft in `processing` zurück.**

Der Dienst löst beim Start jeden Vorgang auf, der im Zustand `processing` hängen geblieben ist.
Für die Auflösung werden zwei Tatsachen herangezogen, die bereits in der Datenbank stehen: wo
das Original liegt (Eingang, verarbeitet oder nirgends) und ob ein Ablageort vermerkt ist.
Dies führt zu einer Entscheidungstabelle (D1), die Abschluss, Neuversuch oder endgültiges
Scheitern bestimmt — nicht der Ausgabeordner allein. Ein Grenzfall (D2), in dem nicht
eindeutig bestimmbar ist, ob die Ablage bereits stattfand, hat zwei Ausgänge: Findet die
Stichprobe im Ausgabeordner eine namentlich passende, nach Vorgangsbeginn veränderte Datei,
wird der Vorgang als gescheitert aufgelöst und das Original in den Fehlerordner verschoben
(sonst würde der Watcher es erneut aufnehmen und eine Doppelablage erzeugen); ohne Treffer
wird der Vorgang neu eingereiht. Die Fehlerkosten sind asymmetrisch (sichtbarer Fehler
reversibel, Doppelablage erst in Paperless aufgefallen), darum wird im Treffer-Fall die
sichtbare Variante gewählt.

Der Aufruf erfolgt in der Startsequenz (`lifespan`, `app/main.py:166`), vor dem Start des
Workers und vor der Annahme neuer Arbeit. Alle Artefakte (Code, Tests, Design, Spec) sind
in der Change `recovery-unterbrochener-verarbeitung` enthalten.

181 Tests gruen.

## Zusatz-Feature: Seitenobergrenze mit Freigabe (2026-09-20)

Die zweite der acht benannten Lücken in `baseline-specs-kernpipeline` ist geschlossen:
**Vor dem ersten OCR-Aufruf wird die Seitenzahl gegen `MAX_PAGES_PER_DOCUMENT` geprüft**
(Standard 100, 0 schaltet ab). Darüber wird der Vorgang angehalten statt verarbeitet — es
entstehen keine Kosten.

Zwei Befunde haben das Design gegenüber der ursprünglichen Absicht verschoben:

**Gezählt wird ohne zu rastern.** Die naheliegende Stelle für die Prüfung wäre nach
`extract_pages` gewesen — dort steht die Seitenzahl heute zum ersten Mal fest. Nur rendert
`extract_pages` jede Seite bei 200 DPI, bevor sie feststeht: Ein 800-Seiten-Scan wäre
vollständig in den Arbeitsspeicher gelaufen und dann angehalten worden. Die Grenze hätte
den Schaden von Geld auf Speicher verschoben, statt ihn abzuwenden. Neu ist deshalb
`count_pages` in `app/pages.py` — PDF über dieselbe Bibliothek wie beim Rendern
(`pypdfium2`), damit die gezählte Zahl mit der später extrahierten übereinstimmt; ein Test
belegt die Deckung für PDF und TIFF, ein weiterer, dass beim Zählen nichts gerendert wird.

**Freigabe allein wäre eine Sackgasse gewesen.** Das Original eines angehaltenen Vorgangs
bleibt im Eingangsordner liegen (sonst nähme der Watcher es erneut auf). Ohne zweiten
Ausgang stünde ein Vorgang, den man nicht freigeben will, auf Dauer im Wartezustand.
Ergänzt wurde deshalb **Verwerfen**: Original nach `error`, Vorgang auf `failed`. Kein
sechster Endzustand — `failed` trägt die gewünschte Semantik bereits, der Verlaufseintrag
`discarded` sagt, wie es dazu kam.

Weiteres:

- Neuer Zustand `blocked` als **Wartezustand**: kein `finished_at`, kein Wiederholversuch,
  kein erhöhter Versuchszähler. Die `status`-Spalte ist freier Text ohne CHECK-Constraint,
  ein Schema-Eingriff war dafür nicht nötig; die Freigabe liegt als neue Spalte
  `page_limit_approved` am Vorgang (über den vorhandenen `_MIGRATIONS`-Pfad, mit Test
  gegen eine Bestandsdatenbank ohne die Spalte).
- Beide Entscheidungen laufen als **bedingter** Übergang (`WHERE id = ? AND status =
  'blocked'`). Ohne das hätte ein Doppelklick — oder Freigeben hier und Verwerfen in einer
  zweiten Ansicht — beide Zweige ausgeführt: Das Original wäre in den Fehlerordner
  gewandert, während der Vorgang schon in der Reihe steht. Eine wirkungslose Entscheidung
  antwortet mit `409`, nicht mit einer stillen Weiterleitung.
- Die Wiederaufnahme nach der Freigabe läuft über `claim_due_retries` (bis zu 30 s), nicht
  über einen direkten Zugriff der HTTP-Schicht auf die Worker-Queue. Die Freigabe übersteht
  dadurch einen Neustart zwischen Klick und Verarbeitungsbeginn.
- Die Zustandsmenge war an vier Stellen redundant gepflegt (`DocStatus`, `STATUS_LABELS`,
  `tile_order`, CSS) — ohne Test, der sie zusammenhält. Ein vergessener Eintrag wäre nicht
  aufgefallen, sondern still danebengegangen. Der Test ist jetzt da, gegengeprobt gegen
  alle vier Mutationen. Die Kachelreihe verteilt sich seither über `auto-fit` statt über
  eine fest verdrahtete 5.

**Review-Runde (zwei Reviewer parallel, Kernlogik auf Opus):** Vier Befunde, alle behoben.
Der gewichtigste war ein Wiedergaenger von Ruling R10 aus der Recovery-Change: `discard`
setzte `failed`, **bevor** es die Datei bewegte. Scheitert `move_into` (Rechte auf dem
Fehlerordner, volles Volume), bliebe ein Vorgang auf `failed` zurueck, dessen Original noch
im Eingang liegt — und `find_by_hash_active` schliesst genau `failed` aus, der Watcher legte
die Datei als zweiten Vorgang an. Die Reihenfolge liess sich hier nicht wie in
`_handle_failure` umdrehen (der Anspruch muss gegen eine zeitgleiche Freigabe stehen),
deshalb wird der Uebergang jetzt **zurueckgenommen**. Ausserdem: beide Routen liefen
synchron im Eventloop und haetten beim geraeteuebergreifenden Verschieben eines grossen
Scans den ganzen Dienst angehalten (jetzt `asyncio.to_thread`); eine unbekannte
Dokument-Kennung antwortete mit `409` „nicht mehr angehalten" statt mit `404`; und der
SSE-Fragment-Pfad war nur auf Statuscode geprueft, obwohl ein dort fehlendes `page_limit`
in Jinja still zu einem Leerstring wird. Beim Nachziehen der Tests fielen zwei eigene
Schwaechen auf: eine Tautologie-Assertion (`== 0 or True`) und ein Regex im
Konsistenztest, der ueber einen auskommentierten Selektor hinweg auf die naechste Regel
durchgriff — beide korrigiert und gegengeprobt. Der Test prueft jetzt zusaetzlich, dass
jedes Statusfarb-Token in **beiden** Schema-Bloecken steht.

263 Tests gruen (vorher 181), `ruff` sauber. Alle Artefakte in der Change
`seitenobergrenze-mit-freigabe`; Feature-Doku unter
`feature-documentation/seitenobergrenze.md`.

**Vor einem Rollback** auf eine ältere Fassung: offene angehaltene Vorgänge entscheiden.
Der Zustandswert `blocked` ist dort unbekannt und lässt `DocStatus(...)` beim Zurücklesen
werfen; die zusätzliche Spalte dagegen stört nicht.

## Zusatz-Feature: Bewahrte OCR-Teilergebnisse (2026-09-21)

Die dritte der acht Luecken in `baseline-specs-kernpipeline` ist geschlossen: **Ein
Wiederholversuch bezahlt bereits erkannte Bloecke nicht erneut.**

Bisher sammelte `process()` die Blockergebnisse in einer lokalen Variable; eine Ausnahme im
dritten Block riss die beiden bezahlten mit. Jetzt wird jeder erfolgreiche Block sofort in der
Tabelle `ocr_chunk_cache` abgelegt, und vor jedem Block wird dort nachgesehen. Ruling R14 der
Recovery-Change, das die "erneut bezahlte Texterkennung" als in Kauf genommen benannte, ist
damit erledigt.

**Der Zwischenspeicher wird dem Adapter gereicht, statt das Chunking hochzuziehen.** Die
Blockhoheit liegt laut Spec bei der Engine. Das Chunking in die Pipeline zu ziehen haette den
Zwischenspeicher trivial gemacht, aber dieses Requirement gebrochen und jede kuenftige Engine
gezwungen, ihre Blockgroesse nach aussen zu tragen. Stattdessen nimmt `process()` einen
optionalen Ablageort entgegen, der bereits an Vorgang und Fingerabdruck gebunden ist — der
Adapter kennt nur Blockindizes und erbt die Ersparnis, ohne etwas ueber Pruefsummen zu wissen.

**Gueltig ist ein Block ueber einen Fingerabdruck, nicht ueber die Bilder.** Er hasht
Pruefsumme des Originals, Blockgrenzen, die Schalter der Bildaufbereitung, die
Renderaufloesung sowie Engine, Prozessor und Region. Ein Schluessel ueber die aufbereiteten
Seiten waere exakter, setzte aber bitgenaue Reproduzierbarkeit von Rasterung und Deskew
voraus — im Projekt nirgends belegt. Waere sie auch nur um ein Pixel verletzt, griffe der
Zwischenspeicher nie: Die Funktion liefe mit, ohne je zu wirken. Ohne `file_hash` am Vorgang
wird gar kein Zwischenspeicher verwendet.

Weiteres:

- **Die Drosselung sitzt jetzt hinter dem Nachsehen.** `DOCAI_MAX_PAGES_PER_MINUTE` schuetzt
  die Quota; ohne Anfrage gibt es nichts zu drosseln. Davor stehend waere ein
  Wiederholversuch, der jede Seite aus dem Speicher bedient, genauso langsam wie der
  urspruengliche Lauf — bei 120 Seiten/Minute eine halbe Minute fuer Anfragen, die nie
  stattfinden.
- **Wiederverwendung ist im Verlauf sichtbar.** Sonst saehe ein Lauf, der 60 Seiten in
  Sekunden abschliesst, wie eine Fehlfunktion aus.
- **Freigegeben wird an zwei Stellen, bewusst doppelt:** sofort beim Uebergang in einen
  Endzustand (wobei `transition_from_blocked` `set_status` umgeht und den Aufruf eigens
  braucht) und als Netz im Aufbewahrungsjob, der die Tatsache selbst prueft statt auf
  Disziplin an jeder kuenftigen Aufrufstelle zu bauen. `CHUNK_CACHE_RETENTION_DAYS` (7)
  schaltet bei 0 nur das Verfallen ab, nicht das Raeumen abgeschlossener Vorgaenge.
- **Fehler des Zwischenspeichers brechen nichts ab** (`SafeChunkStore`): Ein nicht bewahrter
  Block kostet einen erneuten Aufruf, ein abgebrochener Lauf kostet alle. Eine unlesbare
  Zeile gilt als nicht vorhanden.
- **Korrektur einer Annahme aus der Planung:** Task 3.2 ging davon aus, der `FakeAdapter` in
  den Tests laufe unveraendert weiter. `process` ist aber eine abstrakte Methode — ein
  Testdouble muss dem erweiterten Vertrag folgen (eine Zeile). Rueckwaerts kompatibel blieb
  dagegen der Fortschritts-Callback, als Protokoll mit Vorgabewert.

**Abschlussreview (Opus, ueber den ganzen Feature-Diff) — vier Important, alle behoben:**

- **Eine leere Engine-Antwort waere dauerhaft festgeschrieben worden.** Ein Document mit
  null Seiten wurde abgelegt; `[]` ist nicht `None` und galt beim naechsten Lauf als
  Treffer — der Retry haette den fehlenden Textlayer nie mehr geheilt. Die Spalte
  `page_count` wurde geschrieben und nie gelesen. Jetzt pruefen zwei Ebenen unabhaengig:
  das Repository verwirft `page_count <= 0`, der Adapter vergleicht gegen die tatsaechliche
  Blocklaenge (faengt auch "zu wenige, aber mehr als null").
- **Die Pruefsumme alterte gegenueber der Datei auf der Platte.** `doc.file_hash` stammte
  aus der Aufnahme, gerendert wurde aus der Datei im Eingangsordner — die waehrend des
  15-Minuten-Retry-Fensters dort liegen bleibt. Wird sie in diesem Fenster durch eine andere
  Datei gleichen Namens ersetzt, waeren bewahrte Bloecke des alten Dokuments ueber die
  Bilder des neuen gelegt worden: ein *falscher* Textlayer, der schwerste denkbare Schaden
  dieser Funktion. Der Hash wird jetzt je Lauf frisch aus der gelesenen Datei gebildet; bei
  Abweichung greifen die alten Eintraege von selbst nicht mehr, und eine Protokollzeile
  nennt es.
- **Der "engine-unabhaengige" Zwischenspeicher hatte einen engine-abhaengigen
  Fingerabdruck** (`docai_*`-Felder fest in `pipeline.py`). Jetzt deklariert jede Engine
  ueber `OcrAdapter.identity`, was sie identifiziert; Document AI baut sie aus Projekt,
  Region und Prozessor — das schliesst zugleich die zuvor fehlende `GCP_PROJECT_ID`.
- **Der Test fuer den gemischten Lauf konnte nicht fehlschlagen.** Er mass die Wanduhr
  gegen 1,5 s; nachgemessen lag die Regression bei 1,004 s und waere gruen geblieben. Er
  belegt jetzt direkt, welche Seiten gedrosselt wurden.

Dazu sieben Minor (u. a. ein tautologischer Test, die Fehlerhuelle eine Ebene zu tief, ein
fehlender Integrationstest ueber die Naht zwischen echtem Adapter und echtem Store). Die
Huelle sitzt jetzt in der Pipeline statt im Adapter — damit gilt die Spec-Garantie "das
Bewahren darf den Lauf nicht zum Scheitern bringen" fuer jede kuenftige Engine automatisch
statt nur durch deren Disziplin.

Geparkt mit Begruendung: Der Adapter-Vertrag schreibt die Laengenpruefung nicht als Pflicht
fest (nur ein Adapter existiert — gehoert in die Change, die eine zweite Engine einfuehrt),
und ein Test-Double huellt seinen Store doppelt (harmlos, die Naht ist anderweitig
abgedeckt).

320 Tests gruen (vorher 263), `ruff` sauber. Feature-Doku unter
`feature-documentation/chunk-teilergebnisse.md`; `ocr-adapter.md` beschreibt den erweiterten
Vertrag fuer kuenftige Engines.

## Zusatz-Feature: Startvalidierung und Health-Check (2026-09-21)

Die vierte und fünfte der acht Lücken in `baseline-specs-kernpipeline` sind geschlossen:
**Eine fehlende oder falsche Pflichtangabe wird beim Start abgewiesen, nicht erst beim
ersten Dokument als Google-API-Fehler sichtbar**, und **`/healthz` meldet die tatsächliche
Betriebsbereitschaft**, nicht mehr unbedingt `ok`. Dazu ein `HEALTHCHECK` in `Dockerfile`
und `docker-compose.example.yml`.

Drei Befunde haben das Design gegenüber der ursprünglichen Absicht verschoben:

**Eine Design-Annahme war sachlich falsch.** Die erste Fassung wollte `CHUNK_SIZE_PAGES`
auf einen Wertebereich prüfen — mit der Begründung, `0` hieße „kein Block wird
verarbeitet" und ein Wert über dem Limit werde von der Engine abgelehnt. Beides widerlegt:
`DocumentAiAdapter.page_limit` klemmt jeden Wert ≤ 0 ohnehin auf das Engine-Limit. Die
Prüfung ist auf `RETRY_DELAY_MINUTES` eingeengt worden, den einzigen Zähler, bei dem ein
Tippfehler Geld kostet — bei ≤ 0 entfällt die Pause zwischen Wiederholversuchen
vollständig, und ein dauerhaft scheiterndes Dokument verbraucht alle Versuche in Sekunden,
jeden mit einem vollen, bezahlten OCR-Aufruf.

**Ein case-sensitiver Vergleich hätte funktionierende Installationen lahmgelegt.**
`get_adapter()` normalisiert `OCR_PROVIDER` seit immer mit `.lower()`, die neue Prüfung
zunächst nicht. Ein Anwender mit `OCR_PROVIDER=DocumentAI` hätte nach dieser Change einen
Dienst gehabt, der nicht mehr startet — dazu hätte der übersprungene Zweig die echten
Lücken verschluckt. Im Review gefunden und behoben.

**Die Gesundheitsbewertung stand nur in Prosa.** Dass eine abgeschaltete
Paperless-Schleife (`not_started`) und eine unter Last kurzzeitig nicht erreichbare
Datenbank (`busy`) als gesund gelten, war Kommentar, nicht Typ. Die naheliegende
Implementierung (`alle == running and db == usable`) hätte jede Standardinstallation
(Standardkonfiguration läuft mit `FEATURE_PAPERLESS_SYNC=false`) dauerhaft mit `503`
antworten lassen — der Fehler wäre erst am NAS aufgefallen. Als `healthy`-Eigenschaft an
`TaskState` bzw. `DatabaseHealthState` ist er jetzt nicht mehr machbar.

**Die offene Design-Annahme wurde am echten Container geprüft:** Ob uvicorn bei einer
Ausnahme in `lifespan` den Prozess wirklich beendet, statt lauschend hängen zu bleiben.
Ein Abbild wurde ohne Restart-Policy mit absichtlich unvollständiger ENV gestartet: Der
Prozess endete tatsächlich, mit Exit-Code `3`, `State.Running=false` — kein lauschendes
Hängenbleiben. Ein härterer Abbruch war damit nicht nötig.

Weiteres:

- Die Ablehnung erscheint zweimal: als zusammenhängender Block über `log.error`, dann als
  Ausnahme — sonst stünde die Begründung nur im Traceback zwischen Starlette- und
  uvicorn-Rahmen.
- Die Schreibprobe der vier Arbeitsordner und des Datenbank-Verzeichnisses schreibt
  tatsächlich (`tempfile.NamedTemporaryFile`), statt `os.access` zu befragen — der Prozess
  läuft als root, und `os.access` antwortet für root fast immer mit „ja", auch auf einem
  schreibgeschützt eingehängten Volume. Sie fängt den in der Praxis relevanten Fall (falsch
  eingehängter Ordner), nicht falsche Berechtigungen als root.
- Der Container erreicht `healthy` bereits nach rund 20 Sekunden, nicht erst nach Ablauf
  der 120-Sekunden-Anlaufzeit — korrektes Docker-Verhalten (`start_period` schont nur die
  Zählung der Fehlversuche, verzögert aber keinen Erfolg), belegt am echten Container.

Für den Rollout festgehalten: **Vor dem `pull` ist die laufende `.env` vollständig gegen
die Tabelle in
[`feature-documentation/konfiguration.md`](../feature-documentation/konfiguration.md#startvalidierung-was-beim-start-pflicht-ist)
abzugleichen** — nicht nur die Feature-Schalter. Ein gesetzter Schalter ohne die
zugehörigen Angaben war bisher lautlos wirkungslos und ist nach dieser Change ein
**Startfehler**, ebenso ein als `:ro` eingehängter Arbeitsordner (bisher folgenlos, weil
nur beim endgültigen Scheitern beschrieben) oder ein zu kurzes `RETRY_DELAY_MINUTES` bei
aktivem Retry.

**Ein Rollback ist folgenlos:** keine neue Spalte, kein neuer Zustandswert, keine
Datenmigration.

373 Tests grün (vorher 320), `ruff` sauber. Feature-Doku unter
`feature-documentation/startvalidierung-und-healthcheck.md`; ergänzt in
`konfiguration.md` (Pflichttabelle) und `docker-deployment.md` (`HEALTHCHECK`).

## Bewusste Abweichungen vom PRD-Tech-Stack

- UI ohne HTMX/Tailwind-Laufzeit: serverseitiges Jinja2 + offline-CSS + Vanilla-JS-SSE
  (LAN-only, keine Cloud-/Node-Abhängigkeit). Funktional identisch (Live-Updates via SSE).
- `pypdfium2` ergänzt für PDF→Bild-Rasterung (keine System-Abhängigkeit).
- **Kein lokales Auto-Rotate** (PRD §3.1 nennt es als Vorverarbeitungsschritt): Die Heuristik
  über die Varianz der Zeilensummen kann 0° nicht von 180° (bzw. 90° nicht von 270°)
  unterscheiden — die Werte sind mathematisch identisch, die Entscheidung fiel nur über den
  Fließkomma-Rundungsfehler und drehte ~22 % korrekt ausgerichteter Seiten zufällig (oft auf
  den Kopf). Schritt entfernt; Orientierung übernimmt Document AI. `PREPROCESS_AUTOROTATE`
  entfällt. Siehe `feature-documentation/bildvorverarbeitung.md`.

## Nice-to-have (später)

- Weitere OCR-Adapter (Cloud Vision, AWS Textract) — Interface vorbereitet.
- Confidence-Score-Auswertung mit Qualitätswarnung im UI.
