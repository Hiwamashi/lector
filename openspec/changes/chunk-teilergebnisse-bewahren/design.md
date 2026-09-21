# Design

## Context

Siehe `proposal.md` — Why. Verhaltensbindend sind die zwei Delta-Specs unter `specs/`.

Vier Eigenschaften des Bestands bestimmen den Lösungsraum:

1. **Die Blockhoheit liegt bei der Engine.** `process(pages, progress)` nimmt *alle* Seiten
   und chunkt intern (`app/ocr/documentai.py:115-130`); das Seitenlimit ist eine Eigenschaft
   des Adapters (`page_limit`, Zeile 86-92). Die Spec `ocr-veredelung` schreibt das
   ausdrücklich fest. Der Aufrufer sieht die Blöcke nie.
2. **Der Wiederholversuch ist nicht prozessgebunden.** `claim_due_retries` holt fällige
   Vorgänge aus der Datenbank — beim Start des Workers (`app/worker.py:76-78`) genauso wie
   im laufenden Betrieb. Alles, was nur im Arbeitsspeicher liegt, ist beim nächsten Versuch
   möglicherweise weg.
3. **Die Ergebnisstruktur ist frei von Fremdobjekten.** `OcrResult`/`OcrPage`/`OcrToken`
   (`app/models.py:174-197`) sind reine Dataclasses; die Übersetzung aus der Google-Antwort
   geschieht bereits in `document_to_pages` (`app/ocr/documentai.py:45-75`). Sie lassen sich
   also ohne Umweg serialisieren.
4. **Für eine Schlüssel-Upsert-Tabelle gibt es ein Vorbild.** `document_recipients`
   (`app/db.py:88-95`, `app/repository.py:608-682`) ist genau das: Primärschlüssel,
   `ON CONFLICT ... DO UPDATE`, angelegt über `CREATE TABLE IF NOT EXISTS` ohne
   Migrationseintrag.

## Goals / Non-Goals

**Goals:**

- Kein Block wird zweimal bezahlt, solange sich am Dokument und an den Bedingungen nichts
  geändert hat.
- Die Blockhoheit bleibt bei der Engine; der Zwischenspeicher ist engine-unabhängig.
- Der Zwischenspeicher kann nie ein falsches Ergebnis einspielen — im Zweifel wird neu
  erkannt.

**Non-Goals (Design-Ebene, zusätzlich zum Proposal):**

- Keine Fortsetzung *innerhalb* eines Blocks. Die kleinste Einheit ist der Block.
- Kein Teilen des Zwischenspeichers zwischen verschiedenen Vorgängen, auch nicht bei
  inhaltsgleichen Dokumenten (siehe D2).
- Keine Komprimierung der abgelegten Ergebnisse (siehe D3).

## Decisions

### D1 — Der Zwischenspeicher wird dem Adapter gereicht, statt das Chunking hochzuziehen

`process` bekommt einen dritten, optionalen Parameter: einen Ablageort mit zwei Aufgaben —
zu einem Blockindex ein bewahrtes Ergebnis liefern, und eines dazu ablegen. Der Adapter
fragt vor jedem Block nach und legt nach jedem erfolgreichen Block ab.

*Warum nicht das Chunking in die Pipeline ziehen?* Dann wäre der Zwischenspeicher trivial,
aber die Spec „Jede Engine kennt ihr eigenes Seitenlimit und blockt selbst" wäre gebrochen
und jede künftige Engine müsste ihre Blockgröße nach außen tragen. Der Preis wäre ein
Umbau am Adapter-Vertrag, der weit über diese Change hinausreicht.

*Warum kennt der Adapter nur den Blockindex, nicht den Schlüssel?* Weil er von Prüfsummen und
Einstellungen nichts wissen muss. Der Ablageort wird von der Pipeline fertig bestückt
übergeben — mit Vorgang und Fingerabdruck bereits gebunden. Ein künftiger Adapter erbt die
Funktion damit, ohne etwas dafür zu tun.

*Verworfene Alternative:* zwei lose Callbacks statt eines Objekts. Sie müssten paarweise
konsistent übergeben werden, und die Signatur von `process` würde mit jeder weiteren
Zuständigkeit wachsen.

### D2 — Der Schlüssel ist (Vorgang, Blockindex); der Fingerabdruck steht daneben

Tabelle mit Primärschlüssel `(document_id, chunk_index)` und einer Spalte für den
Fingerabdruck. Gelesen wird nur, wenn der gespeicherte Fingerabdruck dem aktuellen
entspricht; geschrieben wird per Upsert.

Der Fingerabdruck ist ein Hash über: Prüfsumme des Originals, Blockgröße, die Schalter der
Bildaufbereitung, die Renderauflösung, den Namen der Engine und die Prozessorkennung.

*Warum der Fingerabdruck nicht im Primärschlüssel?* Sonst blieben nach einer geänderten
Einstellung die alten Zeilen als Müll liegen. So überschreibt der neue Lauf sie Block für
Block.

*Warum `document_id` im Schlüssel, obwohl die Prüfsumme den Inhalt schon identifiziert?*
Zwei Gründe. Das Freigeben wird zu einem `DELETE ... WHERE document_id = ?` statt zu einer
Suche über Fingerabdrücke. Und ein inhaltsgleicher Doppeleingang entsteht als **neuer**
Vorgang (Spec `dokumenteneingang`) — dessen Zwischenspeicher wäre ohnehin leer, weil der
erste beim Abschluss geräumt wurde. Der theoretische Gewinn eines geteilten Speichers ist
damit null, die zusätzliche Verschränkung zweier Vorgänge aber real.

*Wenn die Prüfsumme fehlt* (`file_hash` ist `NULL` — möglich bei einem Vorgang, der nicht
über den Watcher entstand), wird **kein** Zwischenspeicher verwendet. Lieber wirkungslos als
auf einem Schlüssel, der nicht trägt.

### D3 — Abgelegt wird JSON, unkomprimiert

Ein Datensatz je Block enthält die Seiten des Blocks als JSON-Text, erzeugt aus den
Dataclasses; beim Lesen werden sie explizit zurückgebaut (keine generische Deserialisierung
in beliebige Typen).

*Warum kein Pickle?* Es würde beliebige Objekte wiederherstellen und wäre an die
Python-Version gebunden — für Daten, die einen Neustart und womöglich ein Image-Update
überdauern sollen, die falsche Wahl.

*Warum keine Komprimierung?* Sie würde grob zwei Drittel sparen, aber die Einträge sind
kurzlebig (Minuten bis Stunden) und der Gewinn liegt im einstelligen MB-Bereich je
hängendem Dokument. Lesbarer Text ist bei einem Zwischenspeicher, den man im Fehlerfall
ansehen will, mehr wert. Falls die Datenbankgröße je auffällt, ist die Umstellung auf ein
komprimiertes Blob eine lokale Änderung an zwei Funktionen.

*Verworfene Alternative:* die Token als Arrays statt als Objekte ablegen (spart die
wiederholten Feldnamen). Dieselbe Abwägung, mit demselben Ergebnis — und ein Positionsformat
verträgt kein neues Feld.

### D4 — Ein Fehlschlag beim Ablegen bricht den Lauf nicht ab

Das Ablegen läuft in einem eigenen Fehlerfang. Schlägt es fehl, wird protokolliert und
weitergearbeitet.

*Warum?* Die Verhältnismäßigkeit ist eindeutig: Ein nicht bewahrter Block kostet einen
erneuten Aufruf. Ein wegen des Zwischenspeichers abgebrochener Lauf kostet alle Blöcke —
der Schutzmechanismus würde teurer als der Schaden, den er abwenden soll.

Für das **Lesen** gilt dasselbe: Eine unlesbare oder nicht deutbare Zeile wird behandelt, als
gäbe es sie nicht.

### D5 — Die Drosselung sitzt hinter dem Nachsehen

Heute steht `self._rate_limiter.acquire(len(chunk))` vor dem Aufruf
(`app/ocr/documentai.py:122-124`). Die Reihenfolge wird umgestellt: erst nachsehen, und nur
wenn tatsächlich gefragt werden muss, drosseln.

*Warum das mehr ist als eine Feinheit:* Bei `DOCAI_MAX_PAGES_PER_MINUTE=120` wartet ein
60-Seiten-Dokument eine halbe Minute. Bliebe die Drosselung vor dem Nachsehen, wäre ein
Wiederholversuch, der jede Seite aus dem Zwischenspeicher bedient, genauso langsam wie der
ursprüngliche Lauf — für Anfragen, die nie stattfinden.

### D6 — Freigegeben wird an der Zustandsänderung, aufgeräumt im Aufbewahrungsjob

Zwei Wege, bewusst beide:

- **Sofort:** beim Übergang in einen Endzustand. Die zentrale Stelle ist `set_status`
  (`app/repository.py:246-261`), die `done`, `skipped_erechnung` und `failed` bereits
  gesondert behandelt. `transition_from_blocked` umgeht sie und braucht denselben Aufruf.
- **Als Netz:** im täglichen Aufbewahrungsjob — Einträge älter als
  `CHUNK_CACHE_RETENTION_DAYS`, und Einträge zu Vorgängen, die inzwischen in einem
  Endzustand stehen.

*Warum beides?* Der sofortige Weg hängt daran, dass jede künftige Endzustandssetzung ihn
mitnimmt — genau die Art Annahme, die still bricht. Der Aufbewahrungsjob prüft stattdessen
die Tatsache selbst und braucht keine Disziplin an der Aufrufstelle.

### D7 — Gebaut wird der Ablageort in der Pipeline, direkt vor dem Aufruf

`_handle_ocr` (`app/pipeline.py:60-98`) hat alles Nötige beisammen: den Vorgang samt
Prüfsumme, die Einstellungen und den Adapter. Dort entsteht der Fingerabdruck, dort wird der
Ablageort gebunden und an `process` gereicht.

Der Fortschrittsbericht bleibt, wo er ist, bekommt aber die Information mit, ob der Block
wiederverwendet wurde — sonst lässt sich der Verlaufseintrag nicht unterscheiden.

## Risks / Trade-offs

**Ein falsch wiederverwendetes Ergebnis erzeugt ein PDF mit fremdem Text.** → Das ist der
einzige Schaden, der schlimmer wäre als das Problem. Abgewehrt über den Fingerabdruck (D2),
der jede ergebnisrelevante Bedingung einschließt, und über den Grundsatz, im Zweifel neu zu
erkennen. Tests decken jede Bedingung einzeln ab.

**Die Datenbank wächst um die Ergebnisse hängender Dokumente.** → Grob geschätzt wenige MB
je Dokument, freigegeben beim Abschluss, zusätzlich verfallend nach sieben Tagen. Die
Schätzung ist unbelegt: Im Projekt gibt es keine Messung realistischer Token-Zahlen je
Seite. Sollte sie danebenliegen, ist Komprimierung die naheliegende Antwort (D3).

**Die Wiederverwendung greift nie, ohne dass es auffällt.** → Etwa wenn der Fingerabdruck aus
einem übersehenen Grund bei jedem Lauf anders ausfällt. Deshalb ist die Wiederverwendung im
Verlauf sichtbar (Spec `ocr-veredelung`) und ein Test belegt den vollständigen Weg über zwei
Läufe hinweg.

**Das Adapter-Interface bekommt einen dritten Parameter.** → Optional, mit Vorgabewert; der
vorhandene Fake-Adapter in den Tests und jede künftige Engine laufen ohne Anpassung weiter.
Eine Engine, die ihn ignoriert, verliert nur die Ersparnis.

## Migration Plan

1. Die neue Tabelle entsteht über `CREATE TABLE IF NOT EXISTS` beim nächsten Start. Kein
   Eintrag in `_MIGRATIONS` — der Pfad ist nur für neue **Spalten** bestehender Tabellen
   nötig. Kein Datenumzug, keine Ausfallzeit.
2. `CHUNK_CACHE_RETENTION_DAYS` in `.env.example` und `feature-documentation/konfiguration.md`
   aufnehmen. Ohne gesetzte Variable gilt der Standard 7.
3. Beim ersten Lauf nach dem Update ist der Zwischenspeicher leer; das Verhalten entspricht
   exakt dem bisherigen. Die Ersparnis setzt ab dem ersten Wiederholversuch ein.

**Rollback:** Die Vorgängerversion kennt die Tabelle nicht und rührt sie nicht an — sie
bleibt als toter Datenbestand liegen und lässt sich später von Hand entfernen. Kein
Zustandswert und kein Schema bestehender Tabellen ändert sich, ein Rollback ist also
folgenlos.

## Open Questions

Keine. Die Verfallsfrist (7 Tage), das Ablageformat und der Umfang des Fingerabdrucks sind
hier festgelegt und in den Tasks umgesetzt.
