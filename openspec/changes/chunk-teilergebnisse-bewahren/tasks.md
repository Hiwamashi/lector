# Tasks

## 1. Ergebnisse serialisierbar machen

- [x] 1.1 Umwandlung der Ergebnisstruktur (`OcrPage`, `OcrToken`) nach JSON-tauglichen
      Daten und zurück ergänzen, mit explizitem Rückbau statt generischer Deserialisierung
      (D3) — verifiziert durch einen Rundlauf-Test in `tests/test_ocr.py`, der eine Seite
      mit mehreren Token hin- und zurückwandelt und Gleichheit aller Felder prüft
      (einschließlich `confidence` und der vier Koordinaten)
- [x] 1.2 Unvollständige oder fremdartige Daten beim Rückbau abweisen, statt halbe Objekte
      zu bauen — verifiziert durch Tests mit fehlendem Feld, falschem Typ und leerem Text

## 2. Tabelle und Repository

- [x] 2.1 Tabelle für bewahrte Blockergebnisse in `app/db.py` als
      `CREATE TABLE IF NOT EXISTS` ergänzen: Primärschlüssel `(document_id, chunk_index)`,
      dazu Fingerabdruck, Seitenzahl des Blocks, die Nutzdaten und ein Anlagezeitpunkt
      (D2) — verifiziert durch einen Test, der eine frische Datenbank öffnet und die Tabelle
      samt Primärschlüssel vorfindet
- [x] 2.2 Ablegen per Upsert im Repository — verifiziert durch einen Test, der denselben
      Block zweimal mit unterschiedlichem Inhalt ablegt und belegt, dass genau eine Zeile
      mit dem zweiten Inhalt existiert
- [x] 2.3 Lesen mit Fingerabdruck-Abgleich: Bei abweichendem Fingerabdruck wird nichts
      geliefert — verifiziert durch je einen Test für Treffer und Nichttreffer
- [x] 2.4 Freigeben aller Einträge eines Vorgangs — verifiziert durch einen Test, der zwei
      Vorgänge bestückt, einen freigibt und belegt, dass der andere unberührt bleibt
- [x] 2.5 Aufräumabfrage für den Aufbewahrungsjob: Einträge älter als eine Frist **und**
      Einträge zu Vorgängen in einem Endzustand (D6) — verifiziert durch einen Test mit vier
      Vorgängen (alt/neu × Endzustand/laufend), der genau die richtigen zwei entfernt

## 3. Zwischenspeicher im Adapter-Vertrag

- [x] 3.1 Schmale Ablageort-Schnittstelle in `app/ocr/base.py` definieren — zu einem
      Blockindex ein bewahrtes Ergebnis liefern bzw. eines ablegen (D1) — verifiziert durch
      eine Testimplementierung im Speicher, die in den folgenden Aufgaben verwendet wird
- [x] 3.2 `OcrAdapter.process` um den optionalen Ablageort erweitern, mit Vorgabewert.
      **Korrektur der ursprünglichen Annahme:** `process` ist eine abstrakte Methode — ein
      Testdouble muss dem erweiterten Vertrag folgen, der `FakeAdapter` in
      `tests/test_pipeline.py` braucht den Parameter also doch (eine Zeile). Rückwärts
      kompatibel bleibt dagegen der Fortschritts-Callback: Er ist als Protokoll mit
      Vorgabewert definiert, sodass ein Aufruf mit nur der Seitenzahl weiterhin trägt —
      verifiziert dadurch, dass der `FakeAdapter` `progress(i + 1)` unverändert aufruft und
      die bestehenden Pipeline-Tests grün bleiben
- [x] 3.3 Implementierung, die den Ablageort an einen Vorgang und einen Fingerabdruck
      bindet und die Repository-Methoden aus Gruppe 2 nutzt — verifiziert durch einen Test,
      der über sie ablegt und liest
- [x] 3.4 Lese- und Schreibfehler des Ablageorts abfangen, protokollieren und weiterlaufen
      (D4) — verifiziert durch je einen Test mit einem Ablageort, der beim Lesen bzw. beim
      Schreiben wirft, und dem Nachweis, dass die Verarbeitung dennoch vollständig
      durchläuft

## 4. Wiederverwendung im Document-AI-Adapter

- [x] 4.1 In der Blockschleife (`app/ocr/documentai.py:115-130`) vor jedem Block nachsehen
      und bei einem Treffer die Engine überspringen — verifiziert durch einen Test mit
      einem vorbestückten Ablageort, der belegt, dass `_process_chunk` für diesen Block
      nicht aufgerufen wurde und das Ergebnis dennoch vollständig ist
- [x] 4.2 Nach jedem erfolgreich von der Engine verarbeiteten Block dessen Ergebnis ablegen,
      **bevor** der nächste beginnt — verifiziert durch einen Test, dessen Adapter beim
      zweiten Block wirft und der danach das Ergebnis des ersten Blocks im Ablageort
      vorfindet
- [x] 4.3 Drosselung hinter das Nachsehen verlegen, sodass sie nur für tatsächlich
      abgesetzte Anfragen greift (D5) — verifiziert durch einen Test, der einen vollständig
      vorbestückten Ablageort verwendet und belegt, dass keine Wartezeit entsteht, sowie
      durch einen zweiten mit gemischtem Lauf, in dem nur die tatsächlich gesendeten Seiten
      zählen
- [x] 4.4 Fortschrittsmeldung auch für wiederverwendete Blöcke, mit Kennzeichnung der
      Wiederverwendung — verifiziert durch einen Test, der die Meldungen eines gemischten
      Laufs einsammelt und beide Arten unterscheidet
- [x] 4.5 Seitenreihenfolge und Seitenindizes bleiben über gemischte Läufe hinweg korrekt —
      verifiziert durch einen Test, der ein Dokument über drei Blöcke mit vorbestücktem
      mittlerem Block verarbeitet und die Indizes aller Seiten lückenlos und aufsteigend
      vorfindet

## 5. Einbindung in die Pipeline

- [x] 5.1 Fingerabdruck in `app/pipeline.py` bilden aus Prüfsumme des Originals,
      Blockgröße, Schaltern der Bildaufbereitung, Renderauflösung, Engine-Name und
      Prozessorkennung (D2) — verifiziert durch Tests, die je eine Größe ändern und belegen,
      dass sich der Fingerabdruck ändert, sowie durch einen Test, dass er bei unveränderten
      Bedingungen gleich bleibt
- [x] 5.2 Ohne Prüfsumme am Vorgang keinen Ablageort verwenden (D2) — verifiziert durch
      einen Test mit einem Vorgang ohne `file_hash`, der normal verarbeitet wird und nichts
      ablegt
- [x] 5.3 Ablageort binden und an `adapter.process` reichen — verifiziert durch einen
      Pipeline-Test über zwei Läufe: Der erste scheitert nach dem ersten Block, der zweite
      fragt die Engine nur noch für die restlichen Blöcke und erzeugt dasselbe Ergebnis-PDF
      wie ein ungestörter Lauf
- [x] 5.4 Verlaufseintrag eines wiederverwendeten Blocks weist die Wiederverwendung aus —
      verifiziert durch einen Test, der den Verlauf nach dem zweiten Lauf ausliest

## 6. Freigeben und Verfallen

- [x] 6.1 `CHUNK_CACHE_RETENTION_DAYS` (Standard 7) in `app/config.py` ergänzen —
      verifiziert durch einen Test für Standardwert und gesetzten Wert
- [x] 6.2 Freigabe beim Übergang in einen Endzustand in `set_status` (`done`,
      `skipped_erechnung`, `failed`) — verifiziert durch je einen Test pro Endzustand, der
      belegt, dass die Einträge weg sind und Vorgang samt Verlauf erhalten bleiben
- [x] 6.3 Dieselbe Freigabe auf dem Weg über `transition_from_blocked`, der `set_status`
      umgeht (D6) — verifiziert durch einen Test, der einen angehaltenen Vorgang mit
      bestückten Einträgen verwirft
- [x] 6.4 Einträge bleiben erhalten, wenn ein Wiederholversuch eingeplant wurde —
      verifiziert durch einen Test, der nach `schedule_retry` prüft, dass sie noch da sind
- [x] 6.5 Aufräumen im Aufbewahrungsjob (`app/retention.py`) über die Abfrage aus 2.5,
      inklusive Abschaltung bei einem Wert kleiner oder gleich 0 — verifiziert durch je
      einen Test für das Entfernen alter Einträge und für die abgeschaltete Frist

## 7. Dokumentation und Abschluss

- [x] 7.1 `CHUNK_CACHE_RETENTION_DAYS` in `.env.example` und
      `feature-documentation/konfiguration.md` aufnehmen — verifiziert durch Sichtprüfung
      beider Dateien
- [x] 7.2 Feature-Doku unter `feature-documentation/` anlegen: was bewahrt wird, woran ein
      Ergebnis als gültig erkannt wird, wann es freigegeben wird, und warum die Drosselung
      hinter dem Nachsehen sitzt — verifiziert durch die vorhandene Datei
- [x] 7.3 `feature-documentation/ocr-adapter.md` um den erweiterten Adapter-Vertrag
      ergänzen, damit eine künftige Engine weiß, was sie erbt — verifiziert durch den
      ergänzten Abschnitt
- [x] 7.4 `prd/PROGRESS.md` nachziehen: dritte Lücke geschlossen, mit den getroffenen
      Entscheidungen — verifiziert durch den neuen Abschnitt
- [x] 7.5 `ruff` und die vollständige Testsuite laufen lassen — verifiziert durch beide
      Läufe ohne Befund
