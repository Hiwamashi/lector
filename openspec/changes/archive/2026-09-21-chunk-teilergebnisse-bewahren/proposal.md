# Proposal

## Why

`DocumentAiAdapter.process` (`app/ocr/documentai.py:115-130`) sammelt die Blockergebnisse in
einer lokalen Variable. Wirft `_process_chunk` — Netzwerkabbruch, Quota-Antwort, eine Seite,
die die Engine zurückweist —, läuft die Ausnahme bis `run_pipeline` durch und nimmt jedes
bereits bezahlte Blockergebnis mit. Der Wiederholversuch beginnt bei Seite eins und kauft
dieselben Seiten ein zweites Mal.

Bei einem 60-seitigen Dokument, das im letzten Block scheitert, sind das drei vergeblich
bezahlte Blöcke pro Anlauf — bei `RETRY_MAX=3` bis zu neun. Der Fehler, der das auslöst, ist
ausgerechnet der wahrscheinlichste: ein Aussetzer der Gegenstelle mitten in einem langen
Dokument.

Das ist die dritte der acht in `baseline-specs-kernpipeline` benannten Lücken. Sie ist
bereits einmal aktenkundig geworden: Ruling R14 der Recovery-Change nennt die „erneut
bezahlte Texterkennung" ausdrücklich als in Kauf genommenes Problem.

## What Changes

- Jeder erfolgreich verarbeitete Block wird **sofort** festgehalten, bevor der nächste
  beginnt. Fällt der Lauf danach aus, überlebt das Ergebnis.
- Vor jedem Block sieht der Dienst nach, ob für genau diesen Block bereits ein Ergebnis
  vorliegt. Wenn ja, wird es verwendet, statt die Engine zu fragen.
- Ein wiederverwendeter Block löst **keine** Wartezeit des Seiten-Rate-Limits aus. Das Limit
  schützt die Quota der Engine; ohne Anfrage gibt es nichts zu drosseln. Andernfalls wäre ein
  Wiederholversuch, der ausschließlich aus dem Zwischenspeicher liest, genauso langsam wie
  der ursprüngliche Lauf.
- Der Verlauf macht sichtbar, welche Blöcke wiederverwendet wurden — sonst sähe ein Lauf, der
  60 Seiten in zwei Sekunden „erkennt", nach einem Fehler aus.
- Die Zwischenergebnisse werden freigegeben, sobald der Vorgang einen Endzustand erreicht.
  Verwaiste Einträge verfallen zusätzlich nach einer Frist.

**Speicherort:** eine SQLite-Tabelle, ein Datensatz je Block, nach dem Vorbild von
`document_recipients`. Ein Cache im Arbeitsspeicher scheidet aus: Der Wiederholversuch läuft
frühestens 15 Minuten später und nachweislich **nicht** zwingend im selben Prozess — die
Retry-Schleife holt fällige Vorgänge auch nach einem Neustart (`app/worker.py:76-78`), und
die Startauflösung reiht unterbrochene Vorgänge über denselben Weg wieder ein.

**Gültigkeit:** Der Schlüssel besteht aus der Prüfsumme des Originals, den Blockgrenzen und
einem Fingerabdruck der Einstellungen, die das Ergebnis beeinflussen (Vorverarbeitung,
Blockgröße, Engine und Prozessor). Damit hängt die Wiederverwendung **nicht** davon ab, ob
Rasterung und Schieflagenkorrektur bitgenau reproduzierbar sind — das ist im Projekt nirgends
belegt, und ein Schlüssel über die erzeugten Bilder würde bei einem einzigen abweichenden
Pixel dauerhaft ins Leere greifen: Die Funktion liefe mit, ohne je zu wirken.

**Annahme zur Verfallsfrist:** 7 Tage. Lang genug für jede Retry-Kette (dreimal 15 Minuten),
kurz genug, dass Reste eines abgestürzten Laufs nicht dauerhaft liegen bleiben.

## Capabilities

### New Capabilities

Keine. Die Änderung berührt zwei bestehende Capabilities.

### Modified Capabilities

- `ocr-veredelung`: Zwei Requirements ändern sich. „Der Fortschritt wird während der
  Verarbeitung gemeldet" — ein wiederverwendeter Block ist im Verlauf als solcher erkennbar.
  „Die Engine ist austauschbar" — der Zwischenspeicher ist wie Bildaufbereitung und
  PDF-Bau engine-**unabhängig**; die Blockhoheit bleibt bei der Engine. Dazu neue
  Requirements für Festhalten, Wiederverwenden und die Ausnahme vom Rate-Limit.
- `verarbeitungs-lebenszyklus`: Neues Requirement — Zwischenergebnisse werden freigegeben,
  sobald der Vorgang einen Endzustand erreicht, und verfallen andernfalls nach einer Frist.

## Impact

**Code:** `app/ocr/base.py` (Zwischenspeicher-Schnittstelle im Adapter-Vertrag),
`app/ocr/documentai.py` (nachsehen, ablegen, Rate-Limit überspringen), `app/models.py`
(Serialisierung der Ergebnisstruktur), `app/db.py` (neue Tabelle), `app/repository.py`
(Ablegen, Lesen, Freigeben), `app/pipeline.py` (Schlüssel bilden, Zwischenspeicher
durchreichen, bei Abschluss freigeben), `app/retention.py` (Verfall), `app/config.py`
(Frist).

**Datenbank:** eine neue Tabelle. Sie kommt über `CREATE TABLE IF NOT EXISTS` und braucht
keinen Migrationseintrag — `_MIGRATIONS` ist nur für neue **Spalten** bestehender Tabellen
nötig. Bestehende Vorgänge sind nicht betroffen; ohne Zwischenergebnisse verhält sich der
Dienst wie bisher.

**Betriebsgrößen:** Die Datenbank wächst vorübergehend um die Ergebnisse hängender
Dokumente — grob geschätzt wenige MB je Dokument, freigegeben beim Abschluss.

**Nicht betroffen:** E-Rechnungs-Bypass, Paperless-Integration, Weboberfläche außer dem
Verlaufstext, Deployment, Abhängigkeiten.

**Abgrenzung:** Diese Change ändert **nichts** daran, wann ein Wiederholversuch stattfindet
oder wie oft. Die Unterscheidung transienter von permanenten Fehlern bleibt eine eigene,
weiterhin offene Lücke. Und sie setzt die Verarbeitung nicht mitten in einem Block fort: Die
kleinste wiederverwendbare Einheit ist der Block, nicht die Seite.
