# Tasks

Reihenfolge der ersten drei Gruppen ist bewusst so gewählt: Die Prüffunktion entsteht
zuerst ungenutzt, dann werden die Test-Fixtures auf eine vollständige Konfiguration
gehoben, **erst danach** wird die Prüfung in den Start eingehängt. Andersherum wäre die
Suite zwischen zwei Aufgaben flächendeckend rot, und man könnte nicht mehr unterscheiden,
ob ein Fehlschlag von der Änderung oder von einem Fixture-Mangel kommt.

## 1. Prüffunktion für die Konfiguration

- [x] 1.1 In `app/config.py` eine Prüffunktion anlegen, die ein `Settings`-Objekt entgegennimmt und eine Liste von Beanstandungen zurückgibt (leere Liste = gültig); verifiziert durch einen Test, der für eine vollständige Konfiguration eine leere Liste erhält
- [x] 1.2 Jede Beanstandung trägt den ENV-Namen, unter dem die Angabe gesetzt wird, nicht den Feldnamen der Klasse; verifiziert durch einen Test, der `GCP_PROJECT_ID` in der Meldung erwartet und `gcp_project_id` ausschließt
- [x] 1.3 Prüfung von `OCR_PROVIDER` auf einen bekannten Wert, Meldung nennt die zulässigen Werte; verifiziert durch einen Test mit einem erfundenen Provider-Namen
- [x] 1.4 Prüfung der Engine-Pflichtangaben (`GCP_PROJECT_ID`, `DOCAI_PROCESSOR_ID`, `DOCAI_LOCATION`) nur für die gewählte Engine; verifiziert durch zwei Tests — leere Angaben bei gewählter Document-AI-Engine werden beanstandet, bei einer Engine ohne diesen Bedarf nicht
- [x] 1.5 Prüfung von `GOOGLE_APPLICATION_CREDENTIALS` auf gesetzt **und** lesbare Datei; verifiziert durch drei Tests (leer, Pfad ins Leere, vorhandene Datei), Meldung unterscheidet die beiden Fehlerfälle
- [x] 1.6 Prüfung von `RETRY_DELAY_MINUTES` auf mindestens 1 (einziger Zähler aus D2, bei dem ein Tippfehler Geld kostet — Begründung und die entfallenen Prüfungen siehe D2); verifiziert durch drei Tests (0, negativ, gültig) **und** je einen Test, der belegt, dass `CHUNK_SIZE_PAGES=0`, `CHUNK_SIZE_PAGES=99` und eine negative Aufbewahrungsfrist den Start **nicht** verhindern
- [x] 1.7 Prüfung der Feature-Schalter: gesetzter Schalter ohne zugehörige Angaben wird beanstandet, nicht gesetzter Schalter bleibt folgenlos; verifiziert durch je einen Testpaar für Paperless-Sync, SevDesk-Export und Empfänger-KI
- [x] 1.8 Alle Beanstandungen werden gesammelt statt beim ersten abzubrechen; verifiziert durch einen Test mit drei gleichzeitigen Mängeln, der alle drei in der Liste erwartet
- [x] 1.9 Gegenprobe: die Prüffunktion vorübergehend so verändern, dass sie nach der ersten Beanstandung zurückkehrt, und belegen, dass Test 1.8 rot wird

## 2. Test-Fixtures auf eine vollständige Konfiguration heben

- [x] 2.1 Die ENV-Vorbereitung in `tests/test_web.py` auf **eine** gemeinsame Hilfsfunktion zusammenführen, die von der Fixture `client` (Zeilen 11-25) und vom zweiten Aufbau ab Zeile 672 genutzt wird; verifiziert dadurch, dass die Suite unverändert grün bleibt
- [x] 2.2 Diese Hilfsfunktion setzt zusätzlich `GCP_PROJECT_ID`, `DOCAI_PROCESSOR_ID` und `GOOGLE_APPLICATION_CREDENTIALS` auf eine leere Datei in `tmp_path`; verifiziert durch einen grünen Lauf der gesamten Suite, noch bevor die Prüfung eingehängt ist

## 3. Einbindung in die Startsequenz

- [x] 3.1 Eigene Ausnahmeklasse für einen abgelehnten Start in `app/config.py`; verifiziert durch einen Test, der sie gezielt abfängt
- [x] 3.2 Aufruf der Prüfung in `lifespan` (`app/main.py:161`) unmittelbar nach `get_settings()` und **vor** `ensure_dirs()`; bei Beanstandungen alle Zeilen als Block über `log.error` ausgeben, dann die Ausnahme werfen; verifiziert durch einen Test, der den `TestClient` mit unvollständiger ENV betritt und die Ausnahme erwartet
- [x] 3.3 Test, dass ein abgelehnter Start keine Wirkung hinterlässt: keine Datenbankdatei am Ort von `DB_PATH`, kein Vorgang, keine bewegte Datei
- [x] 3.4 Schreibprobe für die vier Arbeitsordner und den Ort der Datenbank, eingefügt **zwischen** `ensure_dirs()` (`app/main.py:162`) und dem Bau des `Repository` (Zeile 164) — nicht danach, sonst existiert die Datenbankdatei bereits, wenn die Probe scheitert; als tatsächlicher Schreib- und Löschvorgang statt `os.access`; verifiziert durch einen Test gegen einen schreibgeschützten Ordner (Test überspringen, wenn er als root läuft und der Schutz nicht greift — Grund im Skip-Text nennen)
- [x] 3.5 Test, dass ein noch nicht vorhandener Arbeitsordner angelegt wird und der Start weiterläuft
- [x] 3.6 Gegenprobe: die Prüfung hinter `ensure_dirs()` und die Datenbank-Erzeugung verschieben und belegen, dass Test 3.3 rot wird

## 4. Zustandsauskunft der Laufzeitbestandteile

- [x] 4.1 `Worker` erhält eine Methode, die je Hintergrundarbeit meldet, ob sie läuft, beendet ist oder wegen eines abgeschalteten Features nicht gestartet wurde; verifiziert durch einen Test an einem Worker mit fünf laufenden Tasks
- [x] 4.2 Diese Methode fängt `CancelledError` beim Abfragen der Ausnahme einer beendeten Task ab; verifiziert durch einen Test, der eine Task abbricht und erwartet, dass die Auskunft antwortet statt zu werfen
- [x] 4.3 Test, dass die nicht gestartete Paperless-Schleife bei abgeschaltetem Feature **nicht** als beendet gilt
- [x] 4.4 Test, dass eine Task, die mit einer Ausnahme endete, als beendet gemeldet wird und die Ursache in der Auskunft erscheint
- [x] 4.5 `Worker`-Instanz in `app.state` ablegen (`app/main.py:174-177`); verifiziert durch einen Test, der sie über den `TestClient` erreicht
- [x] 4.6 `Repository` erhält eine Methode, die eine triviale Abfrage versucht und den Lock nur mit kurzer Frist nimmt; Rückgabe unterscheidet benutzbar, beschäftigt und nicht benutzbar; verifiziert durch drei Tests (regulär, Lock von einem anderen Thread gehalten, geschlossene Verbindung)
- [x] 4.7 Gegenprobe: die Frist beim Lock entfernen und belegen, dass der Test aus 4.6 für den beschäftigten Fall blockiert statt zu antworten

## 5. Health-Endpunkt

- [x] 5.1 `/healthz` (`app/main.py:237`) auf die drei Prüfungen umstellen, Antwort je Prüfung aufgeschlüsselt, `200` bei Erfolg und `503` sonst
- [x] 5.2 Den bestehenden Test `tests/test_web.py:28-30` zu dem Test am gesunden Dienst umbauen, der Statuscode **und** jede einzelne Prüfung belegt — das ist der Nachweis für 5.1, kein zweiter Test daneben (die alte Zusicherung `{"status": "ok"}` ist genau die, die diese Change ablöst)
- [x] 5.3 Test, dass eine beendete Hintergrundarbeit zu `503` führt und die Antwort die betroffene Arbeit benennt
- [x] 5.4 Test, dass eine nicht benutzbare Datenbank zu `503` führt und die Antwort die Datenbank benennt
- [x] 5.5 Test, dass ein beendeter Beobachter-Thread des Eingangsordners zu `503` führt
- [x] 5.6 Test, dass eine **beschäftigte** Datenbank weiterhin `200` ergibt und als beschäftigt ausgewiesen wird
- [x] 5.7 Test, dass der Endpunkt nichts verändert: mehrfache Abfrage bei beendeter Arbeit lässt diese beendet, es entsteht kein Vorgang und kein Verlaufseintrag
- [x] 5.8 Test, dass ein nicht erreichbares Paperless den Health-Endpunkt nicht auf `503` bringt
- [x] 5.9 Gegenprobe: den Endpunkt vorübergehend fest auf `200` setzen und belegen, dass 5.3 bis 5.5 rot werden

## 6. Container und Compose-Vorlage

- [x] 6.1 `HEALTHCHECK` im `Dockerfile` über `python` und `urllib.request` gegen `127.0.0.1:8001/healthz`, ohne `uv run` und ohne neues Apt-Paket; verifiziert durch einen Bau des Abbilds und `docker inspect`, das den Test ausweist
- [x] 6.2 Intervall, Zeitgrenze, Anlaufzeit und Anzahl der Versuche festlegen — Anlaufzeit großzügig (die Auflösung hängengebliebener Vorgänge kann dauern), Intervall und Versuche knapp; die gewählten Werte im Dockerfile kommentiert begründen
- [x] 6.3 `healthcheck`-Block am `lector`-Service in `docker-compose.example.yml` (Zeilen 81-172); verifiziert durch `docker compose config`, das ihn aufgelöst ausgibt
- [x] 6.4 Den Kommentar bei `depends_on` (`docker-compose.example.yml:94`) berichtigen: Es gibt nun einen Health-Check, er wird für `depends_on` bewusst nicht herangezogen
- [x] 6.5 `tests/test_compose_files.py` um eine Prüfung erweitern, dass der `lector`-Service einen `healthcheck` deklariert; verifiziert durch Gegenprobe mit entferntem Block

## 7. Verifikation am echten Container

- [x] 7.1 **Annahme aus D3 prüfen:** Abbild mit unvollständiger ENV starten und belegen, dass der Prozess wirklich **endet** (Exit-Code ungleich 0) und nicht lauschend hängen bleibt; das Ergebnis in `design.md` als verifiziert oder widerlegt festhalten
- [x] 7.2 Fällt 7.1 negativ aus: Abbruch anders erzwingen (Signal an den eigenen Prozess nach dem Protokolleintrag) und 7.1 wiederholen — vor Abschluss der Change entscheiden, nicht danach
- [x] 7.3 Belegen, dass die Begründung in `docker logs` als zusammenhängender Block erscheint und jede beanstandete Angabe nennt
- [x] 7.4 Belegen, dass der Container mit vollständiger ENV den Zustand `healthy` erreicht (`docker compose ps`), nicht nur `running`
- [x] 7.5 Belegen, dass der Container nach dem Abbruch einer Hintergrundarbeit im laufenden Betrieb auf `unhealthy` wechselt

## 8. Dokumentation und Abschluss

- [x] 8.1 `feature-documentation/konfiguration.md` um die Tabelle aus D2 ergänzen: welche Angabe unter welcher Bedingung Pflicht ist, und was bewusst nicht geprüft wird — ausdrücklich festhalten, dass `CHUNK_SIZE_PAGES` auf das Engine-Limit geklemmt wird (≤ 0 und Werte über dem Limit ergeben beide das Limit) und dass ≤ 0 bei den vier Zählern „abgeschaltet" bedeutet
- [x] 8.2 Neue Feature-Datei `feature-documentation/startvalidierung-und-healthcheck.md`: Startverhalten, Prüfumfang, Antwortform des Health-Endpunkts, Zustandstest des Containers, und die Begründung für den harten Abbruch gegenüber einem Wartezustand
- [x] 8.2a Die neue Datei in die Index-Tabelle „Module ↔ Feature" in `feature-documentation/README.md` aufnehmen (Zeile pro Datei, Spalten Datei/Modul/Feature) — ohne diesen Eintrag ist die Doku für einen Agenten, der über den Index navigiert, nicht auffindbar
- [x] 8.2b `feature-documentation/docker-deployment.md` um den `HEALTHCHECK` ergänzen: dass es einen gibt, warum er über den Python-Interpreter statt über `curl` läuft, und dass er nichts neu startet
- [x] 8.3 `.env.example` an den Pflichtstatus anpassen — die Pflichtangaben als solche kennzeichnen, samt Bedingung
- [x] 8.4 Lückentabelle in `openspec/changes/baseline-specs-kernpipeline/proposal.md` nachziehen: zwei Einträge geschlossen, neuer Eintrag für `LOG_LEVEL` über ENV (heute fest auf `INFO`, `app/main.py:34`)
- [x] 8.5 `prd/PROGRESS.md` um den Abschnitt zu dieser Change ergänzen, mit dem Befund aus 7.1 und dem Hinweis auf den Abgleich der `.env` vor dem Rollout
- [x] 8.6 Vollständigen Testlauf und `ruff` sauber belegen; Anzahl der Tests vorher/nachher nennen
- [x] 8.7 `graphify update .` laufen lassen, damit der Graph die neuen Symbole kennt
