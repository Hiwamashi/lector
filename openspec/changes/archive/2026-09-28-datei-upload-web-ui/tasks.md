# Tasks

## 1. Ablage im Eingangsordner

- [x] 1.1 In `app/fileops.py` eine Funktion ergänzen, die einen vom Client gelieferten Dateinamen
  auf seinen reinen Namensanteil reduziert und Namen ersetzt, die danach leer sind, nur aus
  Punkten bestehen oder kein verwertbares Suffix tragen. Verifikation: neue Unit-Tests in
  `tests/test_fileops.py` decken `../../data/lector.db`, `a/b/c.pdf`, `..`, `""` und einen
  gewöhnlichen Namen ab und laufen grün.
- [x] 1.2 In `app/fileops.py` eine Funktion ergänzen, die einen Byte-Strom unter einem über
  `unique_target()` bestimmten Zielnamen ablegt: schreiben nach `<zielname><teil-suffix>`, danach
  atomares Umbenennen auf den Zielnamen; bei einem Fehler beim Schreiben wird die Teil-Datei
  entfernt und der Fehler weitergereicht. Das zu verwendende Teil-Suffix wird übergeben, nicht
  fest verdrahtet. Verifikation: Unit-Tests zeigen, dass (a) nach Abschluss nur die Zieldatei
  existiert, (b) während des Schreibens keine Datei unter dem Zielnamen sichtbar ist, (c) bei
  einem ausgelösten Schreibfehler weder Ziel- noch Teil-Datei zurückbleibt.
- [x] 1.3 Verifizieren, dass eine bereits vorhandene gleichnamige Datei im Zielverzeichnis
  unangetastet bleibt und die neue Datei `_1` erhält — Unit-Test über die Funktion aus 1.2 mit
  vorbelegtem Verzeichnis.

## 2. Endpunkt

- [x] 2.1 In `app/main.py` einen `POST /upload`-Endpunkt anlegen, der mehrere `UploadFile`
  entgegennimmt, jede Datei über 1.1 säubert, ihre Endung gegen `detection.is_supported` prüft
  und die unterstützten Dateien über 1.2 in `settings.watch_dir` ablegt. Das Teil-Suffix stammt
  aus `settings.partial_suffix_list` (erster Eintrag, Rückfall auf `.part`, falls die Liste leer
  konfiguriert ist). Das Schreiben läuft im Thread-Pool, nicht im Event-Loop. Verifikation:
  Test in `tests/test_web.py` lädt ein PDF hoch und findet es anschließend in `WATCH_DIR`.
- [x] 2.2 Zurückgewiesene Dateien sammeln und den Endpunkt mit `303` auf `/` umleiten, wobei die
  Namen der zurückgewiesenen Dateien und die Zahl der übernommenen Dateien als Query-Parameter
  mitgegeben werden (es gibt keine Session-Middleware, also keinen Flash-Speicher).
  Verifikation: Test lädt gemischt `.pdf` + `.zip` hoch, erwartet `303`, das PDF in `WATCH_DIR`,
  kein `.zip` dort und den `.zip`-Namen im `Location`-Header.
- [x] 2.3 Fehlschlag beim Schreiben abfangen, protokollieren und als zurückgewiesene Datei
  melden, statt die Anfrage mit `500` abbrechen zu lassen. Verifikation: Test mit
  gemocktem Schreibfehler erwartet `303` und den betroffenen Namen in der Rückmeldung.
- [x] 2.4 Verifizieren, dass ein Upload mit Verzeichnisanteilen im Dateinamen ausschließlich im
  Eingangsordner landet — Test lädt eine Datei namens `../../lector.db.pdf` hoch und prüft, dass
  außerhalb von `WATCH_DIR` nichts entstanden ist.

## 3. Oberfläche

- [x] 3.1 In `app/templates/dashboard.html` über der bestehenden Filterleiste ein Formular mit
  `method="post"`, `enctype="multipart/form-data"`, `action="/upload"` und einem
  `<input type="file" name="files" multiple>` ergänzen. Kein JavaScript. Verifikation: Aufruf von
  `/` enthält das Formular; Test in `tests/test_web.py` prüft auf `enctype` und `multiple`.
- [x] 3.2 Das `accept`-Attribut des Datei-Feldes aus `detection.SUPPORTED_SUFFIXES` ableiten,
  damit der Dateidialog vorfiltert, ohne die serverseitige Prüfung aus 2.1 zu ersetzen.
  Verifikation: Test prüft, dass jede Endung aus `SUPPORTED_SUFFIXES` im gerenderten
  `accept`-Attribut vorkommt.
- [x] 3.3 In `app/templates/dashboard.html` die Rückmeldung aus 2.2 auswerten und anzeigen:
  Zahl der übernommenen Dateien, Namen der zurückgewiesenen Dateien mit Grund, und der Hinweis,
  dass ein übernommener Vorgang erst nach einigen Sekunden in der Übersicht erscheint.
  Verifikation: Test ruft `/` mit den Query-Parametern auf und findet beide Meldungen im HTML.
- [x] 3.4 In `app/static/app.css` die Darstellung von Formular und Meldungsbereich ergänzen,
  passend zum vorhandenen Stil der Filterleiste. Verifikation: `/` im Browser aufrufen und
  prüfen, dass Formular und Meldung nicht aus dem Layout brechen.

## 4. Verhalten im Zusammenspiel

- [x] 4.1 Verifizieren, dass eine hochgeladene Datei denselben Weg nimmt wie eine im
  Eingangsordner abgelegte: Test lädt eine Datei hoch, lässt den Scan-Lauf sie aufnehmen und
  prüft, dass ein Vorgang im Zustand `pending` mit dem erwarteten Dateinamen entsteht — ohne
  upload-spezifisches Feld im Vorgang.
- [x] 4.2 Verifizieren, dass eine Teil-Datei im Eingangsordner nicht aufgenommen wird: Test legt
  eine Datei mit konfiguriertem Teil-Suffix in `WATCH_DIR` und prüft über den bestehenden
  `StabilityTracker`, dass sie nie als fertig gemeldet wird. (Deckt die Anforderung „Übertragung
  bricht ab" ab.)
- [x] 4.3 Gesamtlauf: `uv run pytest` und `uv run ruff check .` laufen ohne Fehler.

## 5. Dokumentation

- [x] 5.1 `feature-documentation/datei-upload.md` anlegen: Zweck, Endpunkt, Ablageweg
  (Teil-Suffix → Rename), Format-Zurückweisung, Namensabsicherung, verzögerte Sichtbarkeit und
  die bewusst ausgelassene vorgezogene Dublettenprüfung. Verifikation: Datei existiert und ist in
  `feature-documentation/README.md` verlinkt.
- [x] 5.2 In `prd/PRD_Lector.md` (Zeile 53) und `CLAUDE.md` (Abschnitt „Wichtige Vorgaben &
  Fallstricke") den Ausschluss „kein manueller Datei-Upload" durch den neuen, eingegrenzten Stand
  ersetzen — mit dem Hinweis, dass der Upload im Eingangsordner endet und Authentifizierung
  weiterhin ausgeschlossen bleibt. Verifikation: beide Stellen nennen den Upload und widersprechen
  sich nicht mehr.
- [x] 5.3 `prd/PROGRESS.md` um das Feature ergänzen. Verifikation: Eintrag vorhanden.
- [x] 5.4 `graphify update .` ausführen, damit der Wissensgraph den neuen Endpunkt kennt.
  Verifikation: Befehl läuft durch und `graphify-out/graph.json` ist aktualisiert.
