# Umsetzungs- und Review-Protokoll

Begleitdokument zu diesem archivierten Change. Es hält fest, was bei der Umsetzung
entschieden wurde und warum, welche Fehler die Reviews gefunden haben, und was bewusst
offengeblieben ist. Der Code und die Commit-Historie zeigen das Ergebnis; dieses Dokument
zeigt die Wege, die verworfen wurden — und die sind aus dem Ergebnis nicht mehr ablesbar.

**Umsetzung:** 2026-09-27, Branch `feat/datei-upload-web-ui`, nach `main` gemergt als `9d158de`.
**Umfang:** 18 Aufgaben in 5 gebündelten Durchgängen, 5 Task-Reviews, 4 Fix-Runden, eine
Schlussreview über den gesamten Branch, eine Fix-Welle. 393 → 421 Tests.

---

## Die tragende Entscheidung

Der Upload endet an der Ablage in `WATCH_DIR`. Ab dort läuft der bestehende Watch-Folder-Weg
unverändert: kein upload-spezifischer Code, kein neuer Zustand, kein neues Feld im Datenmodell.
Die Schlussreview hat das gegengeprüft — `store_upload` wird ausschließlich aus `app/main.py`
gerufen, ohne Berührung mit Worker, Pipeline, Repository oder Models.

Die Alternative wäre gewesen, dass der Endpunkt die Datei selbst zur Aufnahme anmeldet. Das
hätte den Vorgang sofort sichtbar gemacht statt nach den rund acht Sekunden, die
`POLL_INTERVAL_SECONDS` plus `STABILITY_WINDOW_SECONDS` ergeben. Verworfen, weil der
Prüfsummen-Abgleich in `_intake_file` nur gegen **aktive** Vorgänge prüft: Bei schnell
abgeschlossener Verarbeitung hätte der nachfolgende Scan-Lauf einen zweiten Vorgang für
dieselbe Datei angelegt.

---

## Vor der Umsetzung: zwei Mängel im Plan

Ein Durchgang durch die Aufgabenliste vor dem ersten Dispatch fand zwei Stellen, die so nicht
umsetzbar waren:

- **Aufgabe 4.2 war ein Duplikat.** Der geforderte Test („eine Datei mit Teil-Suffix wird nie
  aufgenommen") existierte bereits als `tests/test_watcher.py::test_partial_suffix_never_ready`.
  Die Aufgabe wurde auf die an dieser Stelle tatsächlich unabgedeckte Gefahr umgewidmet: dass
  der Endpunkt sein Teil-Suffix aus `PARTIAL_SUFFIXES` bezieht statt es hart zu verdrahten.
- **Lücke zwischen Aufgabe 2.2 und 3.3.** 2.2 erzeugt die Query-Parameter der Rückmeldung, 3.3
  zeigt sie an — aber keine Aufgabe änderte die Route `GET /`, die sie entgegennehmen muss. Das
  Template kann sie nicht selbst lesen. Zugeordnet zu 3.3.

---

## Die substanziellen Funde der Reviews

### Der Wettlauf hatte zwei Hälften

**Erste Hälfte** (Task-Review Gruppe 1): `store_upload` bestimmte den Zielnamen einmal zu Beginn
und rief am Ende bedingungslos `os.replace`. Zwei gleichzeitige Uploads desselben Namens
überschrieben einander lautlos — ein Verstoß gegen die Anforderung „Eine Übergabe überschreibt
keine vorhandene Datei".

Die naheliegende Lösung, den Zielnamen vorab mit `O_CREAT|O_EXCL` zu reservieren, **bricht eine
zweite Anforderung**: Sie legt eine leere Datei unter dem endgültigen Namen an, und genau das
verbietet „erst nach vollständiger Übertragung sichtbar" — der Watch-Folder würde die leere
Hülle sehen. Auch `os.link` + `unlink` wurde verworfen: atomar selbst gegen fremde Schreiber,
aber Hardlinks können auf einem SMB-/NFS-gebundenen `scan-in` scheitern und würden Uploads dort
vollständig unmöglich machen. Ein seltenes Überschreiben ist der kleinere Schaden als ein
generell kaputter Upload.

Gewählt: ein modulweiter Lock, der **nur** den Schlussschritt umschließt — Zielnamen neu
bestimmen, dann umbenennen. Das Schreiben bleibt außerhalb und damit parallel. Der Restwettlauf
gegen einen externen Schreiber bleibt bestehen, steckt aber unverändert schon in
`unique_target` und betrifft den gesamten Code, nicht nur den Upload.

**Zweite Hälfte** (erst von der Schlussreview gefunden): Zwischen `while partial.exists()` und
`partial.open("wb")` lag keinerlei Absicherung. Zwei gleichnamige Uploads konnten dieselbe
Zwischendatei öffnen und mit unabhängigen Schreibpositionen ineinander schreiben — das
vermischte Ergebnis wurde dann als vollständige Datei veröffentlicht und ging in die Pipeline.
Ein Upload verloren, einer korrumpiert, die Korruption von außen nicht erkennbar. Behoben über
exklusives Anlegen mit `open("xb")`.

Lehre: Der Branch hatte für die eine Hälfte des Problems eigens einen deterministischen
Nebenläufigkeitstest gebaut — und die andere Hälfte trotzdem übersehen, weil jede Task-Review
nur ihren eigenen Ausschnitt sah.

### Das leere Formular meldete einen Fehler

Klickt man „Hochladen" ohne Dateiauswahl, senden Browser laut HTML-Spezifikation trotzdem einen
Part mit `filename=""` und leerem Body. Starlette erzeugt daraus eine `UploadFile` — es prüft
nur, *ob* `filename` vorkommt, nicht ob der Wert nicht-leer ist. Der Endpunkt machte daraus
„Nicht übernommen: (ohne Namen) — nicht unterstütztes Format".

Verschärfend: Der Test, der genau diesen Fall zu prüfen behauptete, sendete `files=[]` — einen
Request ganz ohne `files`-Part, den kein Browser erzeugt. Grün, und die Anforderung trotzdem
verfehlt. Behoben, indem Parts ohne Namen **und** ohne Inhalt übersprungen werden; ein Part
ohne Namen **mit** Inhalt bleibt eine Formatablehnung.

### Der Integrationstest teilte Zustand mit den Hintergrundschleifen

Der Test griff auf den `StabilityTracker` des laufenden Workers zu, dessen `_scan_loop` denselben
Tracker mit echter Monotonic-Zeit beschreibt. Trug die Hintergrundschleife den Pfad zuerst ein,
lieferte der manuelle Poll nichts mehr. Dazu kam ein zweiter Wettlauf derselben Bauart:
`_intake_file` reiht den Vorgang in die Queue, aus der `_process_loop` ihn weiterbewegt — die
Assertion auf `pending` prüfte gegen einen Zustand, den eine Schleife parallel verlassen durfte.
Behoben, indem beide Schleifen vor dem manuellen Durchspielen stillgelegt werden.

### Die Bestätigungsmeldung war unsichtbar

`.notice` besitzt ohne Modifikator weder Hintergrund noch Rahmen; Farbe kommt erst aus
`.notice--blocked`. Die Upload-Bestätigung war der erste „nackte" `.notice` der Codebase und
stand als unausgezeichneter Absatz in einer Seite voller Kacheln und Tabellen. Das verfehlt die
Anforderung „Die Oberfläche MUSS erkennbar machen, dass die Übergabe erfolgt ist" — behoben
über einen eigenen Modifikator `.notice--success`.

---

## Was die Reviews geprüft und für gut befunden haben

Diese Punkte wurden ausdrücklich gegengeprüft; wer sie später anfasst, sollte wissen, dass sie
einmal bewusst so entschieden wurden:

- **Das abweichende Namensschema des Zwischenpfads** (`name_n.part` statt `stem_n.suffix`) sieht
  nach Duplikation von `unique_target` aus, **muss** aber so sein: Das Teil-Suffix muss am Ende
  stehen, sonst greift `StabilityTracker._is_partial` nicht. Ein „Aufräumen" würde den Schutz
  zerstören.
- **`move_into`/`copy_into` nutzen den Lock nicht** — das ist folgenlos. Über alle Aufrufstellen
  geprüft: Ziel ist ausnahmslos `consume_dir`, `processed_dir` oder `error_dir`, während
  `store_upload` nur nach `watch_dir` schreibt. Es gibt keinen gemeinsamen Zielordner.
- **Die Executor-Trennung.** Das Schreiben läuft über den Standard-Executor, nicht über den
  seriellen Pool des Workers — sonst würde ein Upload die Verarbeitungs-Queue blockieren.
  Anmerkung: Der Standard-Executor wird auch vom Scan-Lauf mitbenutzt; entkoppelt ist der
  Verarbeitungs-Pool, nicht die Aufnahme.
- **Client-gelieferte Dateinamen** laufen überall über Jinjas Autoescaping, nirgends über
  `|safe`. Der `Location`-Header wird über `urlencode` prozentkodiert, `\r\n` im Dateinamen kann
  also keine Header-Injektion auslösen.

---

## Offene Punkte

Bewusst nicht in diesem Change behoben:

1. **`app/watcher.py`, `_emitted`** — eine Datei kann dauerhaft im Eingangsordner liegen bleiben,
   wenn sie einen gerade freigewordenen Namen wiederbelegt, bevor ein Poll die Abwesenheit
   registriert. `self._emitted &= present` entfernt einen Pfad nur, wenn ein Poll ihn abwesend
   sieht; danach überspringt `poll` jeden Pfad in `_emitted`. Der Defekt steckt im unveränderten
   Code und besteht unabhängig vom Upload — der Upload macht die Wiederbelegung desselben Namens
   nur wahrscheinlicher. **Verdient einen eigenen Change.**
2. **Der Nebenläufigkeitstest zum Zwischenpfad** ist an das Implementierungsdetail `mode == "xb"`
   gekoppelt. Empirisch gemessen (30 Läufe gegen eine nachgebaute alte Implementierung): Bei
   einer Rückdrehung auf prüfen-und-öffnen greift der Barrier-Mechanismus nie, der Test fällt
   dann nur timingbedingt in rund 90 % der Läufe durch.
3. **Sehr lange Dateinamen.** Der Zwischenpfad ist um die Länge des Teil-Suffix länger als der
   Zielname. Ab etwa 126 Zeichen mit Umlauten scheitert der Upload mit `ENAMETOOLONG`, während
   dieselbe Datei per SMB-Kopie anstandslos durchläuft.
4. **Unbegrenzt wachsende Rückmeldung.** Bei sehr vielen abgewiesenen Dateien wandern alle Namen
   in den `Location`-Header; jenseits der 16-KiB-Grenze sieht der Nutzer statt der Fehlerliste
   eine abgewiesene Anfrage und erfährt gar nichts. Ein Deckel („die ersten 20 plus N weitere")
   würde genügen.
5. **Keine vorgezogene Dublettenprüfung.** Ein inhaltsgleicher Doppel-Upload wird erst bei der
   Aufnahme verworfen, also nach der Rückmeldung — der Nutzer sieht „übernommen" für eine Datei,
   die still verschwindet. Nachrüstbar, ohne die getroffenen Entscheidungen zu berühren.

---

## Commit-Landkarte

| Commit | Inhalt |
|---|---|
| `17ce338` | Planungsartefakte |
| `3dc3a65` | Namensabsicherung und Ablage mit Teil-Suffix |
| `f865998` | TOCTOU zwischen Zielnamen-Ermittlung und Rename |
| `da04b97` | Endpunkt `POST /upload` |
| `8bc64a5` | Signatur ohne B008-Suppression |
| `62b7e82` | Formular und Rückmeldung im Dashboard |
| `5acda29` | Nachweis des gemeinsamen Wegs |
| `3a5e3cc` | Wettlauf mit den Hintergrundschleifen im Test |
| `683732a` | Dokumentation, überholte Ausschlüsse ersetzt |
| `980380e` | Fix-Welle der Schlussreview |
| `7a01b54` | Aufgabenliste abgehakt |

Das PRD und die `CLAUDE.md` schlossen einen manuellen Upload bis zu diesem Change ausdrücklich
aus; beide Stellen wurden durch den eingegrenzten Stand ersetzt. Authentifizierung bleibt
ausgeschlossen, der Betrieb bleibt auf das LAN beschränkt.
