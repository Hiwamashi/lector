# Tasks

Testbefehle: `uv run pytest`, `uv run ruff check .`. Nach Codeänderungen `graphify update .`.
Aufgaben mit **(manuell)** führt der Anwender aus bzw. sie laufen gegen die echte Instanz; der
Agent bereitet sie vor und hakt erst nach Rückmeldung ab. Befunde aus echten Daten werden im
öffentlichen Repository nur anonymisiert festgehalten.

## 1. Paperless-Filter klären

- [x] 1.1 **(manuell, mit Agent)** Gegen die echte Paperless-Instanz mit Lectors Token prüfen: `checksum__iexact` mit der Prüfsumme eines bekannten Dokuments liefert genau dieses; `original_filename__iexact` und `added__gte/added__lte` werden angenommen; die in `consume` abgelegte Datei eines frischen Scans hat dieselbe SHA-256 wie `original_checksum` in Paperless. Prüfen: Ergebnis (ohne Dokumentdaten) in `design.md` D5 vermerkt, Abweichungen als Änderung des Designs.

## 2. Datenmodell

- [x] 2.1 `app/db.py`: Spalten `output_hash`, `original_path`, `consumed_at`, `paperless_id`, `paperless_link`, `paperless_checked_at` an `documents` über `_MIGRATIONS`, Index auf `paperless_link`; `app/models.py`: Felder am `Document`, Enum `PaperlessLink`, Event `paperless_linked`; `app/repository.py`: `_DOC_COLUMNS`, Lesen/Schreiben, Abfragen „offen“, „nachzuholen“ und Filter `paperless=missing`. Prüfen: Migrationstest mit Alt-Schema (Muster `tests/test_repository.py:126`) und Repository-Tests für die Abfragen.

## 3. Ablage und Originalpfade

- [x] 3.1 `app/pipeline.py`: `output_hash` (E-Rechnung = `file_hash`, OCR = Hash des fertigen PDFs vor dem Move), `consumed_at`, `paperless_link='pending'` nur bei Anbindung; `original_path` aus dem Rückgabewert von `move_into` nach `processed` bzw. `error`. Prüfen: `tests/test_pipeline.py` prüft für beide Wege, dass `output_hash` der SHA-256 der Datei in `consume` entspricht und `original_path` existiert.
- [x] 3.2 `original_path` auch in `app/recovery.py` und `app/decisions.py` setzen, wo Originale verschoben werden. Prüfen: bestehende Tests in `tests/test_recovery.py` grün, neue Assertions auf `original_path`.

## 4. Verknüpfungsjob

- [x] 4.1 `app/paperless.py`: `find_documents(**filters)` mit `fields`-Parameter. Prüfen: Test mit `httpx.MockTransport` prüft Query-Parameter und Rückgabe.
- [x] 4.2 Neues Modul `app/paperless_link.py`: Lauf über offene Vorgänge (Prüfsumme, 24-h-Frist, Stapel 50), Nachholen (E-Rechnung über `file_hash`, OCR über Dateiname und Zeitfenster, nur eindeutige Treffer), Fehler brechen ohne Zustandsänderung ab, Event `paperless_linked`. Prüfen: Tests mit Fake-Client für Treffer, Dublette (vorhandenes Dokument), kein Treffer vor und nach 24 h, Netzfehler, eindeutiger und mehrdeutiger Name, fehlgeschlagene Vorgänge werden übersprungen.
- [x] 4.3 `app/worker.py`: Task `paperless-link` bei `view_enabled`, Takt `PAPERLESS_LINK_INTERVAL_SECONDS` (Standard 300) in `app/config.py` mit Validierung und `.env.example`; Zustand in `/healthz`. Prüfen: Worker-Tests für Start mit und ohne Anbindung; Health-Tests grün und um den neuen Task ergänzt.

## 5. Ansicht

- [x] 5.1 Route `GET /documents/{id:int}/original` (D7): Pfad aus DB bzw. lazy ermittelt und gespeichert, Ordnerprüfung per `resolve()`, PDF/Bild über `_preview_response`, sonst Download mit `attachment` und `nosniff`; 404 wenn nicht vorhanden. Prüfen: Tests für PDF, Bild, XML-Download, gelöschte Datei, Pfad außerhalb der Ordner, Schutz-Header.
- [x] 5.2 `partials/document_panel.html` (D6) mit eingeklapptem bzw. offenem Verlauf, Paperless-Teil über `paperless_doc_body.html` mit `embedded`-Schalter, sonst Original-Vorschau bzw. Hinweise; `missing` beim Laden setzen (D4); Rückweg `back=doc:<id>` für Aktionen; Seite und Fragment nutzen den Baustein. Prüfen: Tests für verknüpft, nicht verknüpft mit Original, Original gelöscht, fehlgeschlagen (Verlauf offen), gelöscht in Paperless; genau ein `#panel-title` und eine `.panel-bar`.
- [x] 5.3 Dokumente-Liste: Spalte „Paperless“ (`col-secondary`), Verknüpfungszustand in `data-rev`, Chip „Nicht in Paperless“, ohne Anbindung keine Spalte und kein Chip. Prüfen: Tests in `tests/test_web.py` für Spalte, Filter und Fall ohne Anbindung; `tests/test_status_consistency.py` grün.
- [x] 5.4 CSS und `DESIGN.md` für Badges der Verknüpfung und den eingebetteten Teil, falls neue Bausteine nötig. Prüfen: **(manuell, mit Agent)** Leiste bei 1800 und 390 px im Browser, Impeccable-Detector ohne neue Befunde. (Browser-Prüfung am 2026-11-03 auf dem NAS: hell und dunkel, ohne horizontalen Überlauf; Detector ohne neue Befunde.)

## 6. Abschluss

- [x] 6.1 Doku: neue `feature-documentation/paperless-integration/scan-verknuepfung.md`, Ergänzungen in `dokumentansicht.md`, `web-ui-sse.md`, `konfiguration.md`, `prd/PROGRESS.md`. Prüfen: Dateien vorhanden und verlinkt.
- [x] 6.2 Gesamtprüfung: `uv run pytest`, `uv run ruff check .`, `graphify update .`, `openspec validate scan-paperless-verknuepfung`, Token-Log-Zeile. Prüfen: Ausgaben ohne Fehler.
- [x] 6.3 **(manuell)** Abnahme auf dem NAS nach Rollout: frischer Scan wird über die Prüfsumme verknüpft (belegt die Prüfsummengleichheit aus 1.1), Altbestand nachgeholt (Zahlen je Zustand, anonymisiert in `PROGRESS.md`), Leiste für verknüpft, fehlgeschlagen und nicht gefunden, Filter. Danach `/opsx:archive`.
