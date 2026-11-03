# Proposal

## Why

Die Dokumente-Liste zeigt, was Lector mit einem Scan gemacht hat, aber nicht, was daraus in
Paperless geworden ist. Wer nach dem Scannen kontrollieren will, ob ein Dokument angekommen ist
und wie es aussieht, muss in Paperless suchen. Bei Fehlern ist das Original nur auf dem NAS
einsehbar. Mit der Paperless-Dokumentansicht gibt es jetzt den Baustein, um beides in Lector zu
zeigen; es fehlt die Verbindung vom Lector-Vorgang zum Paperless-Dokument.

## What Changes

- **Neu: Verknüpfung Vorgang → Paperless-Dokument.** Paperless speichert als Prüfsumme die
  SHA-256 der eingelieferten Datei. Lector hält beim Ablegen in `consume` die SHA-256 der
  abgelegten Datei fest (bei E-Rechnungen ist das die vorhandene Prüfsumme des Originals, beim
  OCR-Weg die des Sandwich-PDFs) und sucht das Dokument in Paperless regelmäßig über diese
  Prüfsumme. Lehnt Paperless eine Dublette ab, findet die Suche das vorhandene Dokument.
- **Neu: Zustände der Verknüpfung** — wartet, verknüpft, verknüpft über Dateinamen, nicht
  gefunden (nach 24 Stunden), in Paperless nicht mehr vorhanden.
- **Neu: Nachholen für den Altbestand.** E-Rechnungen über die vorhandene Prüfsumme;
  OCR-Dokumente ohne gespeicherte Ausgabe-Prüfsumme über den Dateinamen in Paperless und ein
  enges Zeitfenster, nur bei genau einem Treffer.
- **Neu: Vorschau des lokalen Originals** aus `processed` (solange die Aufbewahrung läuft) und
  `error`, mit denselben Schutzmaßnahmen wie die Paperless-Vorschau; XML-E-Rechnungen als
  Download.
- **Geändert: Seitenleiste und Detailansicht der Dokumente-Liste** zeigen kombiniert den
  Lector-Vorgang (Status, Verlauf eingeklappt) und darunter die Paperless-Dokumentansicht; ohne
  Verknüpfung das lokale Original.
- **Geändert: Dokumente-Liste** bekommt eine Spalte „Paperless“ und einen Schnellfilter „Nicht
  in Paperless“.

Nicht Teil dieses Changes: manuelles Zuordnen nicht gefundener Dokumente, Abfrage über die
Paperless-Tasks-API, Änderungen am Verarbeitungsablauf selbst.

## Capabilities

### New Capabilities

- `scan-paperless-verknuepfung`: Ermitteln und Fortschreiben der Verknüpfung eines
  Lector-Vorgangs mit seinem Paperless-Dokument (neu und Altbestand), ihre Zustände, die Anzeige
  in Dokumente-Liste und Seitenleiste sowie die Vorschau des lokalen Originals.

### Modified Capabilities

_keine_ — Verarbeitungsablauf und Historie ändern ihr bisheriges Verhalten nicht; die
Erweiterungen der Dokumente-Ansicht stehen in der neuen Capability.

## Impact

- **Datenbank:** neue Spalten an `documents` (Prüfsumme der abgelegten Datei, Paperless-ID,
  Verknüpfungszustand, Zeitpunkte), Migration ohne Datenverlust.
- **Code:** `app/pipeline.py` (Prüfsumme beim Ablegen), `app/paperless.py` (Suche nach Prüfsumme
  und Dateiname), `app/paperless_sync.py` oder eigenes Modul (Verknüpfungsjob, Nachholen),
  `app/worker.py` (periodischer Job, Health), `app/main.py` (Vorschau des Originals,
  kombinierte Leiste, Filter), Templates der Dokumente-Liste und der Detailansicht.
- **Paperless-Last:** eine Suchanfrage je offenem Vorgang alle 5 Minuten bis zur Verknüpfung;
  einmaliges Nachholen beim Start.
- **Freischaltung:** wie die Dokumentansicht nur mit Paperless-Adresse und Token; ohne beides
  zeigt die Dokumente-Liste das lokale Original.
- **Doku:** `feature-documentation/` (neue Datei), `prd/PROGRESS.md`, `DESIGN.md` falls neue
  Bausteine.
