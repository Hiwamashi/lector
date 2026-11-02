# Proposal

## Why

Alle 5 Minuten reagiert Lector rund 40 Sekunden lang nicht: Seitenaufrufe und `/healthz` hängen,
und der Verknüpfungsjob der Scan-Verknüpfung läuft in eine Zeitüberschreitung. Ursache ist der
Rechnungs-Sync: Er schreibt bei jedem Lauf jede der rund 800 Rechnungen mit eigenem Commit neu
– auch ohne Änderung, weil „zuletzt synchronisiert“ jedes Mal einen neuen Wert bekommt – und
das synchron im einzigen Prozess. Aufgefallen ist es bei der Abnahme der Scan-Verknüpfung; der
Fehler besteht seit Einführung des Syncs.

## What Changes

- **Geändert: Rechnungs-Sync schreibt nur Änderungen.** Eine Rechnung wird nur geschrieben, wenn
  sich ihre gespiegelten Angaben (Titel, Korrespondent, Datum, Empfänger, Beleg-Vermerk)
  geändert haben oder sie neu ist. Unveränderte Rechnungen erzeugen weder einen Schreibzugriff
  noch ein Live-Signal an offene Browser.
- **Geändert: Schreiben gesammelt.** Die Änderungen eines Laufs gehen gesammelt in die Datenbank
  statt mit einem Commit je Rechnung.
- **Geändert: „Zuletzt synchronisiert“ wird „Zuletzt geändert“.** Die Rechnungsdetails zeigen,
  wann der Sync die Angaben der Rechnung zuletzt geändert hat, nicht mehr den letzten Lauf.
- **Neu: Laufzeit im Log.** Der Sync protokolliert je Lauf die Dauer seiner Schritte und die Zahl
  geänderter Rechnungen; damit ist der Fix im Betrieb nachweisbar.
- **Geändert: Fehlertyp im Log der Verknüpfung.** Bricht ein Lauf der Scan-Verknüpfung ab, nennt
  das Log den Fehlertyp (bisher leer bei Zeitüberschreitungen).

Nicht Teil dieses Changes: Auslagern des Syncs in einen eigenen Thread, Änderungen am
SevDesk-Belegabruf oder am Belegabgleich.

## Capabilities

### New Capabilities

- `rechnungs-sync`: Abgleich der Rechnungen aus Paperless in Lectors Datenbank – was als Änderung
  gilt, dass unveränderte Rechnungen nicht geschrieben werden, die Anzeige „Zuletzt geändert“
  und dass Lector während eines Laufs bedienbar bleibt.

### Modified Capabilities

_keine_ — die Scan-Verknüpfung ist noch nicht archiviert; der Fehlertyp im Log ist kein
spezifiziertes Verhalten.

## Impact

- **Code:** `app/repository.py` (`upsert_invoice` vergleicht vor dem Schreiben, gesammeltes
  Schreiben), `app/paperless_sync.py` (`_sync_invoices`, `_sync_sevdesk_tag`, Zeitmessung),
  `app/paperless_link.py` (Log), `app/templates/partials/invoice_sections.html` (Beschriftung).
- **Datenbank:** keine Schemaänderung; die Spalte `last_synced_at` bekommt die Bedeutung
  „zuletzt geändert“.
- **Betrieb:** deutlich weniger Schreibzugriffe auf dem NAS; keine 800 Live-Signale je Lauf mehr.
- **Doku:** `feature-documentation/paperless-integration/` (Sync), `prd/PROGRESS.md`.
