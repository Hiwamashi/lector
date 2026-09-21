# Tasks

## 1. Seitenzahl ohne Rasterung

- [x] 1.1 Zählfunktion in `app/pages.py` ergänzen, die zu Pfad und Dokumenttyp nur die
      Seitenzahl liefert (PDF über `pypdfium2`, TIFF über die Frame-Zahl, Einzelbild 1) —
      verifiziert durch Tests in `tests/test_pages.py` (neu, falls nicht vorhanden) je
      Dokumenttyp, die die zurückgegebene Zahl gegen ein erzeugtes Dokument bekannter
      Seitenzahl prüfen
- [x] 1.2 Übereinstimmung mit der Extraktion belegen — verifiziert durch einen Test, der für
      ein mehrseitiges PDF **und** ein mehrseitiges TIFF zeigt, dass die Zählfunktion
      dieselbe Zahl liefert wie `len(extract_pages(...))` (D1: eine Abweichung würde nach
      einer Zahl blockieren, die später nicht bestätigt wird)
- [x] 1.3 Belegen, dass die Zählung nicht rastert — verifiziert durch einen Test, der das
      Rendern überwacht (z. B. Monkeypatch auf die Rasterfunktion) und zeigt, dass die
      Zählung eines mehrseitigen PDFs es nicht auslöst

## 2. Zustand, Verlaufsarten und Konfiguration

- [x] 2.1 `MAX_PAGES_PER_DOCUMENT` (Standard 100) in `app/config.py` ergänzen — verifiziert
      durch einen Test, der den Standardwert ohne gesetzte Variable und die Übernahme eines
      gesetzten Wertes prüft
- [x] 2.2 Zustand `blocked` in `DocStatus` (`app/models.py`) ergänzen und sicherstellen, dass
      `set_status` ihn **nicht** als Endzustand behandelt (kein `finished_at`) — verifiziert
      durch einen Test in `tests/test_repository.py`, der den Übergang setzt und belegt, dass
      `finished_at` leer bleibt
- [x] 2.3 Verlaufsarten `blocked`, `released` und `discarded` in `EventType`
      (`app/models.py`) ergänzen — verifiziert durch einen Test, der je Art einen Eintrag
      schreibt und ihn im Verlauf des Vorgangs wiederfindet
- [x] 2.4 Spalte für die erteilte Freigabe an `documents` über `_MIGRATIONS`
      (`app/db.py:111-113`) ergänzen, mit Vorgabewert „nicht freigegeben" — verifiziert durch
      einen Test, der eine Datenbank **ohne** diese Spalte anlegt, das Repository darauf
      öffnet und belegt, dass die Spalte danach existiert und bestehende Zeilen den
      Vorgabewert tragen
- [x] 2.5 Label „Angehalten" in `STATUS_LABELS` (`app/main.py:40-46`), Eintrag in
      `tile_order` (`app/templates/dashboard.html:4`) sowie die Regeln `.tile--blocked` und
      `.badge--blocked` in `app/static/app.css` ergänzen — verifiziert durch Aufgabe 2.6
- [x] 2.6 Vollständigkeitstest über die vier Zustandslisten (D7): iteriert über `DocStatus`
      und belegt je Wert einen Eintrag in `STATUS_LABELS`, einen in `tile_order` sowie je
      eine Regel `.tile--<wert>` und `.badge--<wert>` in `app.css` — verifiziert durch
      Gegenprobe: der Test muss rot werden, wenn einer der vier Einträge für `blocked`
      entfernt wird

## 3. Prüfung in der Pipeline

- [x] 3.1 Prüfung am Anfang von `_handle_ocr` (`app/pipeline.py:39`) einsetzen, **vor**
      `extract_pages`: Seitenzahl zählen, an den Vorgang schreiben, und bei Überschreitung
      nach `blocked` wechseln statt zu verarbeiten — verifiziert durch einen Test in
      `tests/test_pipeline.py` mit einem Dokument über der Grenze, der belegt, dass der
      `FakeAdapter` **nicht** aufgerufen wurde und der Vorgang auf `blocked` steht
- [x] 3.2 Grenzfälle der Prüfung — verifiziert durch je einen Test: genau auf der Grenze wird
      verarbeitet (eingeschlossen), Grenze 0 schaltet die Prüfung ab, eine E-Rechnung über
      der Grenze läuft unverändert durch den Bypass
- [x] 3.3 Blockade erzeugt weder Wiederholversuch noch erhöhten Versuchszähler und setzt
      keinen Abschlusszeitpunkt — verifiziert durch einen Test, der nach der Blockade
      `attempt_count`, `next_retry_at` und `finished_at` prüft
- [x] 3.4 Verlaufseintrag `blocked` mit Seitenzahl und geltender Grenze in der Meldung —
      verifiziert durch einen Test, der beide Zahlen im Text des Eintrags findet
- [x] 3.5 Freigegebener Vorgang übergeht die Prüfung — verifiziert durch einen Test, der
      einen freigegebenen Vorgang über der Grenze durch die Pipeline schickt und belegt, dass
      er vollständig verarbeitet wird
- [x] 3.6 Eine nicht zählbare Datei läuft in den bestehenden Fehlerpfad (D1) — verifiziert
      durch einen Test mit einer beschädigten Datei, der belegt, dass ein Wiederholversuch
      eingeplant wird statt einer Blockade

## 4. Entscheidung: freigeben und verwerfen

- [x] 4.1 Bedingten Zustandsübergang im Repository ergänzen, der nur greift, wenn der Vorgang
      auf `blocked` steht, und zurückgibt, ob eine Zeile betroffen war (D5) — verifiziert
      durch je einen Test für den Treffer und für einen Vorgang in einem anderen Zustand
      (keine Änderung, Rückgabe „nicht betroffen")
- [x] 4.2 Freigabe umsetzen: Freigabe-Spalte setzen, Vorgang auf `pending` ohne
      Wiederholzeitpunkt zurücksetzen, Versuchszähler **nicht** erhöhen, Verlaufseintrag
      `released` schreiben — verifiziert durch einen Test, der alle vier Punkte nach der
      Freigabe prüft
- [x] 4.3 Freigabe ohne vorhandenes Original führt zu `failed` mit erklärender Meldung, statt
      den Vorgang einzureihen — verifiziert durch einen Test, der die Datei vor der Freigabe
      aus dem Eingangsordner entfernt
- [x] 4.4 Verwerfen umsetzen: Original in den Fehlerordner verschieben, Vorgang auf `failed`
      mit Meldung, die das Verwerfen benennt, Verlaufseintrag `discarded` — verifiziert durch
      einen Test, der Dateiort, Zustand, Meldung und Verlauf prüft
- [x] 4.5 Konkurrierende Entscheidungen bleiben folgenlos — verifiziert durch einen Test, der
      denselben Vorgang zweimal freigibt bzw. erst freigibt und dann verwirft, und belegt,
      dass die zweite Entscheidung nichts ändert und das Original nicht bewegt wurde

## 5. Weboberfläche

- [x] 5.1 Zwei POST-Endpunkte in `app/main.py` nach dem Vorbild der Rechnungsaktionen
      (`app/main.py:418-444`): Formular-POST, synchroner Aufruf, `303`-Redirect auf die
      Detailansicht; bei einem Vorgang, der nicht auf `blocked` steht, ein Konfliktstatus
      statt einer stillen Weiterleitung — verifiziert durch Tests in `tests/test_web.py` für
      beide Endpunkte, je im Erfolgs- und im Konfliktfall
- [x] 5.2 Beide Schaltflächen in der Detailansicht (`app/templates/partials/detail_body.html`)
      ergänzen, ausschließlich bei `status == "blocked"` — verifiziert durch je einen Test,
      der die Schaltflächen bei einem blockierten Vorgang findet und bei einem `pending`- und
      einem `done`-Vorgang nicht
- [x] 5.3 Seitenzahl und geltende Grenze in der Detailansicht eines blockierten Vorgangs
      anzeigen — verifiziert durch einen Test, der beide Zahlen im gelieferten HTML findet
- [x] 5.4 Kachel und Filter für den neuen Zustand belegen — verifiziert durch einen Test, der
      einen blockierten Vorgang anlegt und prüft, dass die Kachel ihn zählt und der Filter
      `?status=blocked` genau ihn liefert
- [x] 5.5 Live-Aktualisierung nach einer Entscheidung — verifiziert durch einen Test, der
      belegt, dass die Entscheidung eine Benachrichtigung für diesen Vorgang auslöst (wie
      jede andere Zustandsänderung)

## 6. Zusammenspiel und Regressionen

- [x] 6.1 Ein blockierter Vorgang verhindert die erneute Aufnahme seines im Eingangsordner
      liegenden Originals (D6) — verifiziert durch einen Test, der den Eingang ein zweites
      Mal prüfen lässt und belegt, dass kein zweiter Vorgang entsteht
- [x] 6.2 Ein blockierter Vorgang übersteht einen Neustart unverändert und wird dabei weder
      aufgelöst noch erneut aufgenommen — verifiziert durch einen Test, der die Anwendung mit
      einem blockierten Vorgang und dessen Datei im Eingangsordner startet
- [x] 6.3 Ein freigegebener Vorgang wird ohne weiteres Zutun aufgenommen und verarbeitet —
      verifiziert durch einen Test, der nach der Freigabe die Wiederaufnahme über
      `claim_due_retries` belegt
- [x] 6.4 Der Aufbewahrungsjob lässt den Eingangsordner unangetastet — verifiziert durch
      einen Test mit einem blockierten Original im Eingangsordner, das nach einem Durchlauf
      noch dort liegt

## 7. Dokumentation und Abschluss

- [x] 7.1 `MAX_PAGES_PER_DOCUMENT` in `.env.example` und
      `feature-documentation/konfiguration.md` aufnehmen, mit Standardwert und der Bedeutung
      von 0 — verifiziert durch Sichtprüfung beider Dateien
- [x] 7.2 Feature-Doku für die Seitenobergrenze samt Entscheidungsweg unter
      `feature-documentation/` anlegen (Doku-Richtlinie: eine Datei je Funktion) —
      verifiziert durch die vorhandene Datei mit Beschreibung von Blockade, Freigabe und
      Verwerfen
- [x] 7.3 Den Rollback-Hinweis aus `design.md` (offene blockierte Vorgänge vor einem Rollback
      entscheiden) in der Feature-Doku festhalten — verifiziert durch den vorhandenen
      Abschnitt
- [x] 7.4 `prd/PROGRESS.md` nachziehen: zweite Lücke aus `baseline-specs-kernpipeline`
      geschlossen, mit Begründung der getroffenen Entscheidungen — verifiziert durch den
      neuen Abschnitt
- [x] 7.5 `ruff` und die vollständige Testsuite laufen lassen — verifiziert durch beide
      Läufe ohne Befund
