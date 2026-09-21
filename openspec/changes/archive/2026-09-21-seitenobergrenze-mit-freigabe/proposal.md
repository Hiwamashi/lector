# Proposal

## Why

Die Seitenzahl eines eingehenden Dokuments wird heute nirgends gegen eine Grenze geprüft.
`_handle_ocr` (`app/pipeline.py:42`) extrahiert die Seiten und gibt sie ungeprüft an die
Engine — jede Seite kostet bei Document AI Geld. Ein versehentlich als ein Dokument
eingescannter Stapel oder eine irrtümlich in `scan-in` kopierte Datei erzeugt die Kosten
lautlos und vollständig, bevor irgendjemand davon erfährt. Es gibt keinen Halt und keine
Rückfrage.

Das ist die zweite der acht in `baseline-specs-kernpipeline` benannten Lücken.

## What Changes

- Vor dem ersten Aufruf der Engine wird die Seitenzahl gegen eine neue Obergrenze
  `MAX_PAGES_PER_DOCUMENT` geprüft. Ein Wert kleiner oder gleich 0 schaltet die Prüfung ab.
- **BREAKING (Betriebsverhalten):** Ein Dokument über der Grenze wird nicht mehr verarbeitet,
  sondern in einen **neuen Zustand** überführt, in dem es auf eine ausdrückliche Entscheidung
  wartet. Es entstehen keine OCR-Kosten, und es wird kein Wiederholversuch eingeplant —
  wiederholen würde nichts ändern.
- Die Weboberfläche zeigt diesen Zustand als eigene Statuskachel, führt die betroffenen
  Vorgänge in der Liste und bietet je Vorgang zwei Entscheidungen an: **freigeben** — das
  Dokument läuft trotz Überschreitung, und erst diese Entscheidung erzeugt die Kosten — oder
  **verwerfen**: Das Original wandert in den Fehlerordner, der Vorgang endet auf `failed`.
- Die Oberfläche nennt dabei Seitenzahl und geltende Grenze, damit die Entscheidung nicht
  blind getroffen wird.
- Die Seitenzahl wird **ohne** Rasterung der Seiten ermittelt. Heute rastert
  `extract_pages` (`app/pages.py:21-32`) jede Seite bei 200 DPI, bevor die Zahl überhaupt
  bekannt ist — ein 800-Seiten-Scan würde also erst vollständig in den Speicher gerendert und
  dann angehalten. Das verschöbe den Schaden von Geld auf Arbeitsspeicher, statt ihn
  abzuwenden.
- Der Verlauf hält Blockade und Entscheidung fest.

**Warum auch verwerfen, wo nur die Freigabe gefordert war:** Ohne zweiten Ausgang ist
`blocked` eine Sackgasse. Das Original bleibt im Eingangsordner liegen (sonst nähme der
Watcher es erneut auf), der Vorgang bliebe auf Dauer im Wartezustand, und der Anwender
müsste die Datei von Hand aus `scan-in` entfernen — mit einem Vorgang, der für immer
angehalten in der Übersicht steht. Das Verwerfen kostet eine zweite Schaltfläche und nutzt
den vorhandenen Endzustand.

**Bewusst nicht Teil dieser Change:** ein kumulatives Kostenbudget über mehrere Dokumente
(Seitenkontingent pro Tag oder Monat). Es bräuchte einen persistenten Zähler, eine
Zeitfenster-Definition und eine Antwort auf „Kontingent mitten im Monat leer" — und es löst
den realistischen Schadensfall nicht besser als die Grenze pro Dokument, weil der Schaden dort
in **einem** Vorgang entsteht.

**Annahme zum Standardwert:** 100 Seiten. Groß genug, dass gewöhnliche Post, Verträge und
Handbücher unbehelligt durchlaufen; klein genug, dass ein irrtümlicher Massenscan hängen
bleibt. Der Dienst läuft produktiv — ein zu enger Standard würde nach dem Update Dokumente
anhalten, die vorher durchliefen. Wer die Prüfung nicht will, setzt den Wert auf 0.

## Capabilities

### New Capabilities

Keine. Die Änderung berührt drei bestehende Capabilities.

### Modified Capabilities

- `ocr-veredelung`: Neues Requirement — die Seitenzahl wird **vor** dem ersten Engine-Aufruf
  gegen eine Obergrenze geprüft, und die Prüfung geschieht, bevor Kosten entstehen.
- `verarbeitungs-lebenszyklus`: Das Requirement „Ein Vorgang durchläuft definierte Zustände"
  zählt die Zustände abschließend auf und bekommt den neuen Zustand hinzu. Ergänzend: Ein
  angehaltener Vorgang löst **keinen** Wiederholversuch aus (heute ist jeder Fehlschlag
  retry-fähig), sein Original bleibt auffindbar, und die Freigabe führt ihn zurück in die
  reguläre Verarbeitung.
- `verarbeitungs-historie`: Der Zustand ist in Übersicht, Filter und Detailansicht sichtbar;
  die Freigabe ist eine Aktion der Oberfläche; Blockade und Freigabe erscheinen im Verlauf
  (neue Verlaufsarten — die bestehende Aufzählung ist abschließend).

## Impact

**Code:** `app/config.py` (neuer Parameter), `app/models.py` (Zustand, Verlaufsarten),
`app/pages.py` (Seitenzahl ohne Rasterung), `app/pipeline.py` (Prüfung vor der Veredelung),
`app/repository.py` (Zustand persistieren, Freigabe festhalten), `app/main.py`
(zwei Endpunkte für die Entscheidung), `app/templates/` (Kachel, Filter, Schaltflächen) und
`app/static/app.css` (Kachel- und Abzeichenfarbe des neuen Zustands).

**Datenbank:** Der Zustand ist eine freie Textspalte ohne CHECK-Constraint (`app/db.py:14`) —
für ihn ist kein Schema-Eingriff nötig. Für die dauerhaft festgehaltene Freigabe kommt eine
Spalte hinzu, über den vorhandenen Migrationspfad (`_MIGRATIONS`, `app/db.py:111-113`).
Bestehende Vorgänge sind nicht betroffen.

**Stille Mitwisser:** Die Menge der Zustände ist an vier Stellen redundant gepflegt —
`DocStatus`, `STATUS_LABELS` (`app/main.py:40-46`), `tile_order`
(`app/templates/dashboard.html:4`) und die CSS-Klassen `.tile--*` / `.badge--*`
(`app/static/app.css:118-122,190-194`). Kein Test erzwingt heute, dass sie deckungsgleich
sind; ein vergessener Eintrag fiele nicht auf. Diese Change fügt den fehlenden Test hinzu.

**Konfiguration:** ein neuer Wert in `.env.example` und
`feature-documentation/konfiguration.md`.

**Nicht betroffen:** E-Rechnungs-Bypass (dort findet keine Texterkennung statt, die Grenze
greift nicht), Paperless-Integration, Deployment, Abhängigkeiten.

**Abgrenzung zu einer anderen offenen Lücke:** „Fehler werden nicht nach transient/permanent
unterschieden" bleibt offen. Diese Change führt **keine** allgemeine Fehlerklassifikation ein;
sie regelt nur, dass genau dieser eine Fall kein Wiederholversuch ist.
