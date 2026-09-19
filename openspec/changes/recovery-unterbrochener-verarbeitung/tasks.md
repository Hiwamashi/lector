# Tasks

## 1. Vorgänge in Bearbeitung auffindbar machen

- [ ] 1.1 Abfrage in `app/repository.py` ergänzen, die alle Vorgänge im Zustand `processing`
      nach `id` geordnet liefert — verifiziert durch einen Test in `tests/test_repository.py`,
      der drei Vorgänge in `pending`, `processing` und `done` anlegt und belegt, dass
      ausschließlich der mittlere zurückkommt
- [ ] 1.2 Hilfsfunktion ergänzen, die zu einem Vorgang bestimmt, wo sein Original liegt
      (Eingang, verarbeitet, oder nirgends) — verifiziert durch einen Test, der die Datei
      jeweils an den passenden Ort legt bzw. entfernt und alle drei Rückgaben abdeckt

## 2. Auflösungslogik

- [ ] 2.1 Auflösung nach der Entscheidungstabelle aus `design.md` (D1) implementieren, ohne
      sie an die Startsequenz zu binden — verifiziert durch Tests je Tabellenzeile, die einen
      Vorgang samt Dateizustand herstellen und den resultierenden Zustand prüfen
- [ ] 2.2 Grenzfall aus D2 ergänzen: Original im Eingang, kein Ablageort vermerkt, aber eine
      Datei mit erwartetem Namen im Ausgabeordner, die nach `started_at` verändert wurde →
      `failed` mit Meldung, die zur Prüfung in Paperless auffordert — verifiziert durch zwei
      Tests, die sich nur im Änderungszeitpunkt der Datei unterscheiden und zu `failed` bzw.
      zu erneuter Einreihung führen
- [ ] 2.3 Abschluss über denselben Weg wie im Normalfall (D4): Original nachziehen, wenn es
      noch im Eingang liegt, und den zum Dokumenttyp passenden Endzustand setzen —
      verifiziert durch je einen Test für den OCR-Weg (`done`) und den E-Rechnungs-Weg
      (`skipped_erechnung`)
- [ ] 2.4 Verlaufseintrag je aufgelöstem Vorgang schreiben, der die Unterbrechung und die
      getroffene Auflösung benennt — verifiziert durch einen Test, der den Verlauf nach der
      Auflösung ausliest
- [ ] 2.5 Fehler je Vorgang einzeln abfangen und protokollieren, ohne die Auflösung der
      übrigen abzubrechen — verifiziert durch einen Test mit drei Vorgängen, bei dem der
      mittlere eine Ausnahme auslöst und die beiden anderen dennoch aufgelöst werden

## 3. Einbindung in den Start

- [ ] 3.1 Auflösung in `lifespan` (`app/main.py`) aufrufen, nach dem Öffnen der Datenbank und
      **vor** `worker.start()`, analog zu `reset_stale_exports` — verifiziert durch einen
      Test, der einen Vorgang auf `processing` vorbereitet, die Anwendung startet und belegt,
      dass er danach nicht mehr in diesem Zustand steht
- [ ] 3.2 Anzahl der aufgelösten Vorgänge je Start protokollieren (nur bei mehr als null) —
      verifiziert durch einen Test, der die Protokollausgabe mit `caplog` prüft
- [ ] 3.3 Reihenfolge absichern: kein neu aufgenommenes Dokument darf vor der Auflösung
      verarbeitet werden — verifiziert durch einen Test, der gleichzeitig einen unterbrochenen
      Vorgang und eine neue Eingangsdatei bereitstellt und die Reihenfolge belegt

## 4. Abschluss

- [ ] 4.1 Regressionsprobe: Die neuen Tests gegen die *unveränderte* Fassung laufen lassen und
      belegen, dass sie dort fehlschlagen — sonst beweisen sie nichts
- [ ] 4.2 `feature-documentation/pipeline-lifecycle-retry.md` um die Auflösung beim Start
      ergänzen, inklusive der Entscheidungstabelle und des Grenzfalls — verifiziert durch
      Sichtprüfung gegen `design.md`
- [ ] 4.3 `prd/PROGRESS.md` um die umgesetzte Lücke ergänzen und den Eintrag in der
      Lücken-Tabelle von `openspec/changes/baseline-specs-kernpipeline/proposal.md` als
      erledigt kennzeichnen
- [ ] 4.4 Vollständiger Lauf: `uv run pytest` grün und `uv run ruff check` sauber
- [ ] 4.5 `openspec sync` für diese Change ausführen, damit das neue Requirement in
      `openspec/specs/verarbeitungs-lebenszyklus/spec.md` steht — verifiziert durch
      `openspec validate --specs`
