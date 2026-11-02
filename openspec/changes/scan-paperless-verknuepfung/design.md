# Design

## Context

Motivation siehe `proposal.md`, Verhalten siehe `specs/scan-paperless-verknuepfung/spec.md`.
Ausgangslage im Code:

- **Prüfsummen:** `file_hash` ist die SHA-256 des Eingangsoriginals, berechnet in
  `Worker._intake_file`. Paperless speichert als `checksum` die SHA-256 der eingelieferten
  Datei (an einem echten Dokument geprüft: `original_checksum` mit 64 Hex-Zeichen).
- **Ablage:** E-Rechnungen gehen per `copy_into` byte-identisch nach `consume`
  (`pipeline.py:30-36`). Das Sandwich-PDF entsteht in einem `TemporaryDirectory` und geht per
  `move_into` nach `consume` (`pipeline.py:145-158`). `output_path` speichert den
  `consume`-Pfad, inklusive eines `_n`-Suffixes bei Namenskollision. Den Zeitpunkt der Ablage
  gibt es nur als Event `moved_to_consume`.
- **Originale:** Nach Erfolg bzw. endgültigem Fehler wird das Original nach `processed` bzw.
  `error` verschoben. Der neue Pfad wird **nicht** gespeichert, `source_path` bleibt der
  Eingangspfad. `recovery._find_in_processed` findet ein Original über das Namensmuster
  `stem(_n)?.ext` und die Prüfsumme. Die Aufbewahrung löscht Dateien, aber keine DB-Einträge.
- **Paperless-Client:** `search_documents` kennt nur Volltext, Sortierung und Custom-Field-Query.
  `get_document` wirft bei 404; `PaperlessSync` hat dafür bereits Muster (`load_document_view`
  gibt bei 403/404 `None`).
- **Hintergrundjobs:** Der Worker hat vier immer laufende Tasks und den optionalen
  `paperless-sync`, der nur mit `FEATURE_PAPERLESS_SYNC` startet und dessen Zustand in
  `/healthz` erscheint.
- **Leiste:** `detail_body.html` und `paperless_doc_body.html` binden beide `panel_bar.html` ein
  und tragen beide `h1#panel-title`; `app.js` verlässt sich auf genau ein `#panel-title`.

## Goals / Non-Goals

**Goals:**

- Verknüpfung deterministisch über die Prüfsumme, Dateiname nur als gekennzeichnete Ausnahme
  für den Altbestand.
- Keine Änderung am Ablauf und an den Zuständen der Verarbeitung.
- Ein Leistenbaustein für alle Zustände eines Vorgangs.

**Non-Goals:**

- Kein Abgleich in Gegenrichtung (Paperless-Dokumente ohne Lector-Vorgang).
- Keine manuelle Zuordnung, keine Tasks-API.
- Kein Nachholen der Ausgabe-Prüfsumme alter OCR-Vorgänge über die Datei in `consume`: Die ist
  nach der Aufnahme durch Paperless weg.

## Decisions

### D1: Neue Spalten an `documents`

`output_hash` (SHA-256 der abgelegten Datei), `original_path` (aktueller Pfad des Originals in
`processed` oder `error`), `consumed_at` (Zeitpunkt der Ablage), `paperless_id`,
`paperless_link` (`pending | linked | linked_by_name | not_found | missing`),
`paperless_checked_at`. Nachgezogen über `_MIGRATIONS`, Index auf `paperless_link` über
`_POST_MIGRATION_INDEXES`. `paperless_link` ist `NULL` für Vorgänge ohne Ergebnis (laufend,
fehlgeschlagen, verworfen), damit Liste und Filter sie als „—“ behandeln.

*Alternative:* eigene Tabelle `document_links`. Verworfen, weil die Beziehung 1:1 ist und die
Liste die Werte in jeder Zeile braucht.

### D2: Prüfsumme und Pfade beim Ablegen schreiben

- E-Rechnung: `output_hash = file_hash` (Bytes identisch), kein zweites Lesen.
- OCR: Hash des fertigen PDFs im Temp-Ordner vor `move_into` (die Bytes ändern sich durch Move
  und `chown` nicht).
- Beide: `consumed_at` = Zeitpunkt der Ablage, `paperless_link = 'pending'` nur bei
  konfigurierter Anbindung, sonst `NULL`.
- `move_into` liefert den Zielpfad im `processed`- bzw. `error`-Ordner; er wird als
  `original_path` gespeichert, an allen Stellen, die Originale verschieben (Pipeline,
  `recovery.py`, `decisions.py`).

Für den Altbestand wird `consumed_at` aus dem Event `moved_to_consume` bzw. `finished_at`
abgeleitet und `original_path` beim Öffnen der Ansicht lazy über `_find_in_processed` bzw. ein
gleiches Suchmuster im Fehlerordner ermittelt und dann gespeichert.

### D3: Eigener Hintergrundjob `paperless-link`

Ein eigener Task nach dem Muster von `paperless-sync`, aber gestartet bei `view_enabled`
(Adresse und Token), unabhängig vom Rechnungs-Feature. Er erscheint in `/healthz`; ohne
Anbindung gilt `NOT_STARTED` als gesund. Takt: `PAPERLESS_LINK_INTERVAL_SECONDS`, Standard 300.
Je Lauf:

1. Offene Vorgänge (`pending`) in Stapeln von bis zu 50: je ein
   `GET /api/documents/?checksum__iexact=<hash>&fields=id`. Treffer → `linked`. Kein Treffer und
   `consumed_at` älter als 24 Stunden → `not_found`.
2. Nachholen (einmal nach Start, dann im selben Lauf für noch nicht geprüfte Vorgänge):
   E-Rechnungen mit `file_hash` wie oben; OCR-Vorgänge ohne `output_hash` über
   `original_filename__iexact=<Name aus output_path>` plus `added__gte/added__lte` im Fenster
   `consumed_at` bis `consumed_at + 24 h`. Genau ein Treffer → `linked_by_name`, sonst
   `not_found`.
3. Fehler (Netz, 5xx) brechen den Lauf ab, ohne Zustände zu ändern. Mehr als 5 Treffer bei
   der Prüfsumme gelten als nicht unterstützter Filter und brechen ebenfalls ab; beim
   Dateinamen gelten sie als mehrdeutig (`not_found`), damit ein häufiger Scan-Name das
   Nachholen nicht blockiert. Ein Namenstreffer, dessen Paperless-ID schon ein anderer Vorgang
   trägt, wird verworfen, bevor gezählt wird; bleibt genau ein Treffer, wird verknüpft. Bei 2 bis 5
   Prüfsummentreffern bleibt der Vorgang mit Warnung `pending` (Betriebsfehler, nicht Normalfall).
4. `not_found`-Vorgänge mit Prüfsumme werden einmal täglich erneut gesucht, solange die Ablage
   weniger als 14 Tage zurückliegt (etwa nach einem längeren Paperless-Ausfall);
   Einmal nach jedem Start werden alle `not_found`-Vorgänge erneut gesucht, unabhängig vom Alter.

Ein Event `paperless_linked` im Verlauf hält Verknüpfung und Herkunft fest.

*Alternative:* Anbau an `paperless-sync`. Verworfen, weil der nur mit
`FEATURE_PAPERLESS_SYNC` läuft und die Verknüpfung auch ohne Rechnungsfeature gebraucht wird.

### D4: `missing` beim Öffnen, nicht im Job

Ob ein verknüpftes Dokument gelöscht wurde, erkennt die Ansicht beim Laden
(`load_document_view` → `None`) und setzt `missing`. Der Job prüft verknüpfte Vorgänge nicht
erneut, um Paperless nicht mit Bestandsabfragen zu belasten.

### D5: Paperless-Client

Neue Methode `find_documents(**filters) -> list[int]` auf `/api/documents/` mit
`fields=id,original_file_name,added` und kleiner Seitengröße. Ob Paperless die Filter
`checksum__iexact`, `original_filename__iexact` und `added__gte/lte` annimmt, wird zu Beginn
gegen die echte Instanz geprüft (Aufgabe 1.1); im Quellcode von Paperless-ngx sind `checksum`
und `original_filename` als Filterfelder deklariert.

**Befund 1.1 (2026-11-02):** `checksum__iexact` liefert für die Prüfsumme eines bekannten
Dokuments genau dieses und für eine erfundene keines; `original_filename__iexact` und
`added__gte`/`added__lte` (ISO mit `Z`) grenzen wie erwartet ein; `fields=id,added,original_file_name`
wird beachtet. **Paperless ignoriert unbekannte Filter stillschweigend** und liefert dann den
gesamten Bestand. Daraus folgt eine Schutzregel: Mehr als 5 Treffer gelten als „Filter nicht
unterstützt“ und brechen den Lauf ohne Verknüpfung ab; beim Namens-Fallback wird
`original_file_name` und `added` des Treffers zusätzlich geprüft. Dass die Prüfsumme einer
frisch abgelegten OCR-Datei mit der in Paperless übereinstimmt, zeigt die Abnahme 6.3: Ein
frischer Scan wird nur dann verknüpft, wenn sie übereinstimmt.

### D6: Kombinierte Leiste

`partials/document_panel.html` setzt sich zusammen aus:

1. `panel_bar` (einmal) und Kopf mit `h1#panel-title` = Dateiname, Status-Badge,
   Paperless-Bezug („in Paperless #1234 ↗“ intern auf `/paperless/1234`).
2. Verlauf als `<details>`, offen bei `failed`, `processing`, `pending`, `blocked`.
3. Bei Verknüpfung der Inhalt von `paperless_doc_body.html` **ohne** dessen `panel_bar` und mit
   `h2` statt `h1` (Schalter `embedded=true` im Partial); sonst die Original-Vorschau.

Die volle Seite `/documents/{id}` und das Fragment nutzen denselben Baustein. Aktionen im
eingebetteten Paperless-Teil leiten mit `X-Lector-Panel` wie bisher auf
`/fragment/paperless/{pid}`; für die Dokumente-Liste kommt ein Formularfeld `back=doc:<id>`
hinzu, damit die Antwort wieder die kombinierte Leiste ist.

### D7: Original-Vorschau

Route `GET /documents/{id:int}/original`. Pfad nur aus `original_path` (bzw. lazy ermittelt),
`Path.resolve()` muss unter `processed_dir` oder `error_dir` liegen, sonst 404. Für PDF und
Bilder über `_preview_response` (gleiche Typprüfung und Header); für XML und andere Typen mit
`Content-Disposition: attachment` und `X-Content-Type-Options: nosniff`. Kein Download aus
`consume`.

### D8: Liste und Filter

Spalte „Paperless“ (`col-secondary`) mit Badge je Zustand, `linked_by_name` mit Zusatz „über
Namen“. `data-rev` bekommt den Verknüpfungszustand, damit der Zeilen-Diff Änderungen anzeigt.
Schnellfilter-Chip `paperless=missing` filtert auf `status in (done, skipped_erechnung)` und
`paperless_link in (pending, not_found, missing)`. Das Repository erhält dafür einen Parameter.

## Risks / Trade-offs

- [Paperless verändert die Datei vor dem Hashen] → Laut Metadaten speichert Paperless das
  Original unverändert (`has_archive_version: false` bei `PAPERLESS_OCR_MODE: skip`). Aufgabe
  1.1 prüft es an einem frischen Scan.
- [Dateiname-Fallback verknüpft falsch] → nur eindeutige Treffer im engen Fenster, Zustand
  `linked_by_name` sichtbar.
- [Viele offene Vorgänge beim ersten Nachholen] → Stapel von 50 je Lauf, Abfragen mit
  `fields=id`, Fortschritt über `paperless_checked_at`.
- [Pfad-Einschleusung bei der Original-Auslieferung] → nur DB-Pfade, `resolve()` plus
  Ordnerprüfung, keine Pfadangaben aus der Anfrage.
- [Doppelte IDs in der kombinierten Leiste] → `embedded`-Schalter, Test prüft genau ein
  `#panel-title` und genau eine `.panel-bar`.

## Migration Plan

Spalten werden beim Start nachgezogen. Der erste Lauf des Jobs holt den Altbestand nach. Ein
Rollback auf das vorherige Image ist ohne Eingriff möglich, die zusätzlichen Spalten werden
ignoriert.

## Open Questions

- Ob ein Stapel von 50 je Lauf den Altbestand schnell genug nachholt, zeigt der erste Start;
  der Wert ist eine Konstante und kann ohne Spec-Änderung angepasst werden.
