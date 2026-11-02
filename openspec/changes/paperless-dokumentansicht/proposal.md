# Proposal

## Why

Für den Alltag muss man heute ständig zwischen Lector und Paperless wechseln: Die
Rechnungsliste zeigt kein PDF, die Empfänger-Zuordnung zeigt nur Titel ohne Dokument, und
wer prüfen will, was eine Zeile eigentlich ist, öffnet Paperless in einem neuen Tab. Lector
soll die UI für den Alltag werden und Paperless das Backend für Details. Dafür braucht
Lector eine eigene, lesende Sicht auf Paperless-Dokumente, die aus jeder Liste ohne
Seitenwechsel erreichbar ist.

## What Changes

- **Neu: Dokumentansicht für Paperless-Dokumente.** Eine Seite `/paperless/{id}` zeigt
  PDF-Vorschau und die Paperless-Metadaten des Dokuments (Titel, Korrespondent,
  Dokumenttyp, Datum, Tags, Custom Fields, Notizen, ASN), dazu einen Absprung „In Paperless
  öffnen ↗“. Alles ist lesend; bearbeitbar sind nur die Angaben, die Lector heute schon
  bearbeitet (Empfänger, Rechnungsdaten, „überwiesen“, SevDesk-Export), und zwar mit den
  bestehenden Aktionen.
- **Neu: Seitenleiste in allen Listen.** Rechnungen, Empfänger und Dokumente öffnen die
  Ansicht als Seitenleiste neben der Liste. Auf breiten Bildschirmen wird die Liste schmaler
  und blendet weniger wichtige Spalten aus; auf schmalen Bildschirmen liegt die Leiste über
  der Liste, auf dem Handy im Vollbild. Der Zustand steht in der URL (`?doc=…`), Tastatur:
  ↑/↓ bzw. j/k wechseln das Dokument, Esc schließt, Enter öffnet die volle Seite.
- **Neu: allgemeiner Vorschau-Proxy.** Die PDF-Vorschau läuft für jedes Paperless-Dokument
  über Lector (bisher nur für bekannte Rechnungen), mit denselben Sicherheits-Headern wie
  heute.
- **Geändert: Rechnungsdetail.** Die bisherige Rechnungsdetailseite wird zur
  Dokumentansicht mit Rechnungsbereich; ihre Aktionen bleiben erhalten, alte Links leiten
  weiter.
- **Geändert: Dokumente-Liste (OCR-Weg).** Die Seitenleiste zeigt dort zunächst Status und
  Verlauf des Lector-Dokuments wie die heutige Detailansicht. Die Verknüpfung mit dem
  Paperless-Dokument und die Vorschau des lokalen Originals folgen im Change
  `scan-paperless-verknuepfung`.
- **Geändert: Produktpositionierung.** `PRODUCT.md` beschreibt Lector künftig als
  Alltags-UI vor dem Paperless-Backend statt als reinen Vorschritt.

Nicht Teil dieses Changes: Bearbeiten von Paperless-Metadaten (Titel, Korrespondent, Tags,
Dokumenttyp, sonstige Custom Fields), Verknüpfung von Scans mit Paperless-Dokumenten über
die Prüfsumme, lokale Vorschau von Originalen, Volltextsuche über Paperless.

## Capabilities

### New Capabilities

- `paperless-dokumentansicht`: Lesende Ansicht eines Paperless-Dokuments in Lector (Seite
  und Seitenleiste), Vorschau-Proxy, Absprung nach Paperless, eingebettete Lector-Aktionen
  je Kontext und das Seitenleisten-Verhalten in den Listen.

### Modified Capabilities

- `verarbeitungs-historie`: Die Detailansicht eines Lector-Dokuments öffnet sich aus der
  Dokumente-Liste zusätzlich als Seitenleiste.

## Impact

- **Code:** `app/paperless.py` (Dokument, Notizen, Namen für Korrespondenten, Tags,
  Dokumenttypen und Felder lesen), `app/paperless_sync.py` (Vorschau für beliebige IDs,
  Namens-Caches), `app/main.py` (Routen `/paperless/{id}`, Fragment, Vorschau; Weiterleitung
  der Rechnungsdetailseite), neue Partials unter `app/templates/partials/`,
  `invoices.html`, `recipients.html`, `index.html` bzw. Dokumente-Liste,
  `app/static/app.js` (Seitenleiste, Tastatur, URL-Zustand), `app/static/app.css`.
- **Sicherheit:** Der Proxy liefert mit Lectors Paperless-Token jedes Dokument aus. Bei
  `AUTH_MODE=paperless` sieht damit jeder angemeldete Nutzer alle Dokumente, die Lectors
  Token sehen darf. Das ist bewusst so entschieden und wird dokumentiert.
- **Last:** Pro geöffnetem Dokument ein Metadatenabruf und ein Vorschauabruf bei Paperless;
  Namenslisten werden zwischengespeichert.
- **Doku:** `PRODUCT.md`, `DESIGN.md`, `feature-documentation/` (neue Datei zur
  Dokumentansicht), `prd/PROGRESS.md`.
