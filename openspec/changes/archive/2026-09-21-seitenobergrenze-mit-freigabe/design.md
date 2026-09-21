# Design

## Context

Siehe `proposal.md` — Why. Verhaltensbindend sind die drei Delta-Specs unter `specs/`.

Vier Eigenschaften des Bestands bestimmen den Lösungsraum:

1. **Die Seitenzahl ist heute erst nach der Rasterung bekannt.** `extract_pages`
   (`app/pages.py:21-32`) rendert mit `pypdfium2` jede Seite bei 200 DPI zu einem PIL-Bild;
   `total = len(images)` in `app/pipeline.py:42` ist die erste Stelle, an der die Zahl
   feststeht. Eine Prüfung an dieser Stelle käme zu spät: Der Arbeitsspeicher ist dann bereits
   verbraucht. Es gibt im Projekt bisher keinen Zählpfad ohne Rasterung.
2. **Der Zustand ist freier Text.** `documents.status` ist `TEXT NOT NULL` ohne
   CHECK-Constraint (`app/db.py:14`); geprüft wird erst beim Zurücklesen über
   `DocStatus(row["status"])`. Ein neuer Zustandswert braucht also keinen Schema-Eingriff.
   Für neue **Spalten** gibt es einen schlanken Migrationspfad: das Tupel `_MIGRATIONS`
   (`app/db.py:111-113`), das per `PRAGMA table_info` prüft und bei Bedarf
   `ALTER TABLE ... ADD COLUMN` ausführt.
3. **Die Zustandsmenge ist an vier Stellen redundant gepflegt** — `DocStatus`,
   `STATUS_LABELS` (`app/main.py:40-46`), `tile_order` (`app/templates/dashboard.html:4`)
   und die CSS-Klassen `.tile--*` / `.badge--*`
   (`app/static/app.css:118-122,190-194`). Kein Test hält sie heute zusammen.
4. **Für UI-Aktionen existiert ein durchgängiges Vorbild.** Die Rechnungsseite nutzt
   POST-Formular → synchroner Aufruf → `303`-Redirect auf die Detailseite; die Anzeige zieht
   danach über SSE nach, ausgelöst durch die Repository-Benachrichtigung (`app/main.py:418-444`,
   `app/templates/partials/invoice_detail_body.html:24-56`). Kein JavaScript je Aktion.

## Goals / Non-Goals

**Goals:**

- Die Entscheidung „verarbeiten oder nicht" fällt, **bevor** nennenswerte Ressourcen —
  Geld wie Arbeitsspeicher — verbraucht sind.
- Der neue Zustand fügt sich in die vorhandene Zustandsmaschine ein, ohne Sonderwege im
  Worker oder in der Recovery.
- Die redundante Pflege der Zustandsmenge wird abgesichert, statt um eine fünfte Stelle
  erweitert zu werden.

**Non-Goals (Design-Ebene, zusätzlich zum Proposal):**

- Kein direkter Zugriff der HTTP-Schicht auf die Worker-Queue. Die Wiederaufnahme läuft über
  denselben Zustandsübergang wie ein Wiederholversuch (siehe D4).
- Keine Verallgemeinerung von `blocked` zu einem Freigabe-Rahmenwerk für künftige
  Blockadegründe. Der Zustand ist so benannt, dass er das später trüge; gebaut wird er für
  genau diesen einen Grund.
- Keine Änderung an der Recovery unterbrochener Verarbeitung. Sie holt ausschließlich
  `processing` (`app/recovery.py`, `app/repository.py:301-313`) — siehe D6.

## Decisions

### D1 — Ein eigener Zählpfad ohne Rasterung, getrennt von `extract_pages`

Neu in `app/pages.py`: eine Funktion, die zu Pfad und Dokumenttyp **nur die Seitenzahl**
liefert.

| Typ | Weg | Kosten |
|---|---|---|
| PDF | `pypdfium2.PdfDocument(path)` öffnen, Seitenzahl abfragen, schließen | Parsen des Seitenbaums, keine Rasterung |
| TIFF | Pillow öffnen, `n_frames` lesen | Header/IFD-Kette, keine Dekodierung der Bilddaten |
| Einzelbild | konstant 1 | — |

**Warum dieselbe Bibliothek wie beim Rendern (`pypdfium2`), nicht `pikepdf`?** Weil die
gezählte Zahl mit der später tatsächlich extrahierten übereinstimmen muss. `pikepdf` ist im
Projekt zwar vorhanden (`app/detection.py:15`), zählt aber auf einem anderen Parser — bei
einem beschädigten oder ungewöhnlich strukturierten PDF können die Zahlen auseinanderlaufen,
und dann blockierte der Dienst nach einer Zahl, die er anschließend nicht bestätigt.

**Verworfene Alternative:** `extract_pages` einen Parameter „nur zählen" mitgeben. Das
vermischt zwei Aufgaben in einer Funktion, deren Rückgabetyp dann von einem Schalter abhängt.

**Fehlerfall:** Lässt sich die Seitenzahl nicht ermitteln (beschädigte Datei), wird die
Ausnahme nicht abgefangen. Sie läuft in den bestehenden Fehlerpfad
(`_handle_failure`, `app/pipeline.py:71-90`) und damit in den regulären Wiederholversuch —
dasselbe, was heute geschähe, nur früher. Eine Datei, die sich nicht zählen lässt, ließe sich
ohnehin nicht extrahieren.

### D2 — Die Prüfung sitzt am Anfang des OCR-Weges, nicht in `run_pipeline`

Der Platz ist der Beginn von `_handle_ocr` (`app/pipeline.py:39`), vor `extract_pages`.

*Warum nicht früher, etwa bei der Aufnahme im Watcher?* Weil dort der Dokumenttyp noch nicht
feststeht und E-Rechnungen ausgenommen sind (siehe Spec `ocr-veredelung`). Die Erkennung
läuft in `run_pipeline` (`app/pipeline.py:103`); erst danach ist bekannt, ob überhaupt eine
Texterkennung ansteht.

*Warum nicht in `run_pipeline` nach der Erkennung?* Dort müsste die Fallunterscheidung
E-Rechnung/OCR ein zweites Mal aufgemacht werden. Am Anfang von `_handle_ocr` ist sie bereits
getroffen.

Die festgestellte Seitenzahl wird in beiden Ausgängen an den Vorgang geschrieben
(`total_pages`) — auch im Blockadefall, weil die Oberfläche sie anzeigen muss.

### D3 — Die Freigabe ist eine Spalte am Vorgang, nicht ein Rückschluss aus dem Verlauf

Neue Spalte in `documents`, eingeführt über `_MIGRATIONS`. Sie hält fest, dass für diesen
Vorgang die Grenze nicht mehr gilt.

*Warum keine Ableitung aus dem Verlauf* (etwa „es existiert ein `released`-Eintrag")? Der
Verlauf ist ein Protokoll, kein Zustandsträger. Eine Auswertung über Ereignisse würde die
Verarbeitungsentscheidung von der Vollständigkeit des Protokolls abhängig machen und wäre bei
jedem Wiederholversuch erneut zu treffen.

*Warum kein Zurücksetzen der Freigabe nach erfolgreicher Verarbeitung?* Weil der Vorgang
danach in einem Endzustand steht und die Spalte nur noch dokumentiert, dass eine Entscheidung
getroffen wurde. Ein späterer, inhaltsgleicher Doppeleingang erzeugt einen **neuen** Vorgang
(Spec `dokumenteneingang`) — und der ist nicht freigegeben. Genau so soll es sein.

### D4 — Die Freigabe setzt den Vorgang auf `pending` zurück, statt ihn direkt einzureihen

Die Route ändert nur den Zustand. Die Wiederaufnahme besorgt `claim_due_retries`
(`app/repository.py:289-299`), das `pending` mit fälligem oder leerem Wiederholzeitpunkt holt
und im Takt von `_RETRY_POLL_SECONDS` (30 s, `app/worker.py:182-189`) eingereiht wird.

*Warum nicht direkt `worker._enqueue(doc.id)` aus der Route?* Das wäre der erste Pfad, der
die HTTP-Schicht an die Queue-Instanz koppelt; heute tut das keine Route. Die Wiederaufnahme
ist damit auch nach einem Neustart zwischen Freigabe und Verarbeitung robust — der Vorgang
steht dann schlicht auf `pending` und wird beim Start ohnehin geholt.

*Preis:* bis zu 30 Sekunden zwischen Klick und Verarbeitungsbeginn. Bei einem Dokument, das
die Grenze überschreitet und entsprechend lange läuft, fällt das nicht ins Gewicht. Die
Oberfläche zeigt den Vorgang in dieser Zeit als `pending` — nicht als „passiert nichts".

*Wichtig:* Der Versuchszähler wird bei der Freigabe **nicht** erhöht. Die Blockade war kein
Fehlversuch. Ein freigegebenes Dokument hat weiterhin seine vollen `RETRY_MAX` Versuche.

### D5 — Beide Entscheidungen laufen als bedingter Zustandsübergang

Freigeben und Verwerfen werden als `UPDATE ... WHERE id = ? AND status = 'blocked'`
ausgeführt und liefern zurück, ob eine Zeile betroffen war. Nur bei einer betroffenen Zeile
folgen Verlaufseintrag und Dateibewegung.

*Warum nicht erst lesen, dann schreiben?* Ein Doppelklick auf „Freigeben", oder Freigeben in
einer Ansicht und Verwerfen in einer zweiten, würde sonst beide Zweige ausführen — im
schlimmsten Fall wandert das Original in den Fehlerordner, während der Vorgang schon in der
Verarbeitungsreihe steht. Der bedingte Übergang macht die zweite Entscheidung wirkungslos,
und die Route antwortet mit einem Konfliktstatus statt mit einer stillen Weiterleitung.

**Verwerfen** verschiebt danach das Original in den Fehlerordner und setzt `failed` mit einer
Meldung, die das Verwerfen benennt. *Warum `failed` und nicht ein eigener Endzustand
„verworfen"?* Weil `failed` genau die gewünschte Semantik bereits trägt — Original bleibt im
Fehlerordner erhalten, wird nicht automatisch gelöscht, Vorgang ist abgeschlossen. Ein
sechster Zustand brächte eine weitere Kachel, eine weitere Farbe und eine weitere
Fallunterscheidung, ohne mehr auszusagen als der Verlaufseintrag `discarded` es tut.

### D6 — Kein Eingriff in Recovery, Dublettenschutz und Aufbewahrung

Drei Stellen, an denen ein neuer Zustand hätte stören können, tragen ihn ohne Änderung:

- **Recovery:** `resolve_stale_processing` holt ausschließlich `processing`. Der Übergang
  nach `blocked` geschieht synchron innerhalb der Pipeline; ein Vorgang bleibt dabei nicht
  auf `processing` stehen.
- **Dublettenschutz:** `find_by_hash_active` (`app/repository.py:175-183`) schließt nur
  `failed` aus — `blocked` gilt damit automatisch als aktiv, und die im Eingangsordner
  liegengebliebene Datei erzeugt keinen zweiten Vorgang. Das ist geschenkt, aber nicht
  abgesichert: Die Bedingung ist als Ausschlussliste formuliert, ein späterer Umbau zu einer
  Einschlussliste würde es lautlos brechen. Darum ein Regressionstest.
- **Aufbewahrung:** Der Retention-Job räumt nur `PROCESSED_DIR`. Blockierte Originale liegen
  in `WATCH_DIR` und werden nicht angetastet.

### D7 — Ein Test hält die vier Zustandslisten zusammen

Ein Test iteriert über `DocStatus` und belegt für jeden Wert: ein Eintrag in
`STATUS_LABELS`, ein Eintrag in `tile_order`, eine Regel `.tile--<wert>` und eine Regel
`.badge--<wert>` in `app.css`.

*Warum überhaupt?* Weil diese Change die vierfache Redundanz zum ersten Mal wirklich
belastet, und weil ein vergessener Eintrag nicht knallt, sondern still danebengeht: eine
Kachel ohne Farbe, ein Filter ohne Eintrag, ein Zustand, den man in der Oberfläche nicht
findet. Die Spec `verarbeitungs-historie` verlangt ausdrücklich, dass kein Zustand nur in der
Datenbank existiert — dieser Test ist ihre Prüfung.

*Verworfene Alternative:* die vier Listen zu einer zusammenziehen (etwa Label und
CSS-Klasse als Metadaten am Enum). Das wäre die sauberere Struktur, ist aber ein Umbau an
Stellen, die diese Change sonst nicht anfasst — Templates und CSS eingeschlossen. Der Test
schützt dasselbe zu einem Bruchteil des Eingriffs.

## Risks / Trade-offs

**Der Standardwert 100 hält nach dem Update ein Dokument an, das vorher durchgelaufen wäre.**
→ Der Vorgang ist nicht verloren: Er steht sichtbar in der Übersicht und ist mit einem Klick
freigegeben. Der Wert steht in `.env.example` und in der Feature-Doku, und der
Verlaufseintrag nennt Seitenzahl und Grenze. Wer die Prüfung nicht will, setzt 0.

**Die Zählung ohne Rasterung könnte von der späteren Extraktion abweichen.** → Durch dieselbe
Bibliothek minimiert (D1). Bleibt eine Restabweichung, ist sie harmlos: Die Grenze entscheidet
nur über Ja/Nein, nicht über die Verarbeitung selbst. Ein Test belegt die Übereinstimmung für
mehrseitige PDF und TIFF.

**Ein blockierter Vorgang hält sein Original im Eingangsordner fest.** → Beabsichtigt, aber
mit zwei Folgen: Der Ordner bleibt nicht leer, und ein Anwender, der die Datei dort von Hand
entfernt, lässt einen Vorgang zurück, dessen Freigabe ins Leere liefe. Die Spec deckt diesen
Fall ab (Freigabe ohne Original → `failed` mit erklärender Meldung).

**Bis zu 30 Sekunden zwischen Freigabe und Verarbeitungsbeginn** (D4). → Bewusst in Kauf
genommen; die Oberfläche zeigt währenddessen `pending`, nicht Stillstand.

**Ein Dokument über der Grenze wird bei jedem Wiederholversuch erneut gezählt.** → Die
Zählung ist billig (kein Rendern), und der Fall tritt nur bei einem Fehlschlag **nach** der
Freigabe ein — dort wird die Prüfung ohnehin übersprungen.

## Migration Plan

1. Spalte für die Freigabe über `_MIGRATIONS` ergänzen. Sie wird auf bestehenden Datenbanken
   beim nächsten Start angelegt; vorhandene Zeilen erhalten den Vorgabewert „nicht
   freigegeben". Kein Datenumzug, keine Ausfallzeit.
2. Neuer Zustandswert: kein Schema-Eingriff (D-Context 2). Bestehende Vorgänge behalten ihren
   Zustand; `blocked` kann nur durch eine neue Verarbeitung entstehen.
3. `MAX_PAGES_PER_DOCUMENT` in `.env.example` und `feature-documentation/konfiguration.md`
   aufnehmen. Ohne gesetzte Variable gilt der Standard 100.

**Rollback:** Die Vorgängerversion des Images einspielen. Die zusätzliche Spalte stört sie
nicht (sie liest sie nicht). Ein zum Zeitpunkt des Rollbacks auf `blocked` stehender Vorgang
wäre für die alte Fassung allerdings ein unbekannter Zustandswert — `DocStatus(row["status"])`
wirft dort beim Zurücklesen. Vor einem Rollback deshalb offene blockierte Vorgänge
entscheiden (freigeben oder verwerfen); sind keine offen, ist der Rollback folgenlos.

## Open Questions

Keine. Der Name des neuen Zustands (`blocked`), sein deutsches Label („Angehalten") und der
Standardwert der Grenze (100) sind im Proposal bzw. hier festgelegt und in den Tasks
umgesetzt; sie sind vor der Umsetzung leicht zu ändern, blockieren sie aber nicht.
