# Paperless-Integration: GiroCode, SevDesk-Export & Export-Übersicht

Ein **entkoppeltes Zusatz-Feature**, das unabhängig vom OCR-Veredelungspfad
(`scan-in → consume`) läuft. Während der Kern Lector **vor** Paperless sitzt, dreht dieses
Feature die Richtung um: Lector liest Rechnungen **aus** Paperless, erzeugt GiroCodes für die
Überweisung, stuft jede Rechnung nach dem Geschäftskontext **IT-Consulting** ein, gleicht sie mit
den Belegen in SevDesk ab und exportiert ausgewählte Rechnungen nach SevDesk — und schreibt Status
zurück ans Paperless-Dokument.

```
Paperless (Dokumententyp = "Rechnung")
   │  [PaperlessSync._sync_invoices]  (periodisch im Worker)
   ▼
GiroCode-Zahldaten  ──► E-Rechnung (XRechnung/ZUGFeRD): deterministisch aus XML
   │                └─► sonst: Heuristik aus OCR-Text + Korrespondent
   │
   ├─► Empfänger-Feld und „SevDesk-Beleg“ gespiegelt (recipient_label, paperless_voucher_ref)
   ▼
Lector-UI: /invoices  (Export-Übersicht)  ── Filter, Mehrfachauswahl, QR, Zahldaten
   │
   ├─► Kontext-Einstufung   (kontext-einstufung.md)
   │      Quellen: Empfänger → Korrespondenten-Historie → KI-Wahrscheinlichkeit
   │
   ├─► SevDesk-Abgleich     (sevdesk-abgleich.md)
   │      Belegabzug (GET /Voucher, periodisch) → sicherer Treffer (Beleg-ID)
   │                                             │ ähnlicher Treffer (Betrag, Datum, Lieferant)
   ▼
Export (sevdesk-export.md) ── Prüfungen & Sperren (sync-und-aktionen.md)
   │  harte Sperre → nicht exportierbar
   │  Rückfrage    → nur nach Bestätigung
   ▼
SevDesk-Beleg (Entwurf)  ──► Rückschrieb: Beleg-ID, Datum, Empfänger, Tag, Notiz

Paperless-Tag (SEVDESK_TAG)
   │  [PaperlessSync._sync_sevdesk_tag]  — dieselben Prüfungen wie die Übersicht
   ▼
queued (vorgemerkt) | review („zu prüfen“, mit Grund) | nicht vorgemerkt (harte Sperre)
```

Der Tag-Weg exportiert erst nach mindestens einem erfolgreichen Belegabruf. Bis dahin bleiben
Rechnungen `queued`. Die Prüfungen laufen in beiden Wegen gleich (siehe
[sync-und-aktionen.md](sync-und-aktionen.md)).

## Module ↔ Funktion

| Datei | Funktion |
|---|---|
| [girocode.md](girocode.md) | `app/girocode.py` — Zahldaten-Extraktion + EPC069-12-QR |
| [paperless-client.md](paperless-client.md) | `app/paperless.py` — REST-Client (lesen/zurückschreiben) |
| [sevdesk-export.md](sevdesk-export.md) | `app/sevdesk.py` — Beleg-Upload nach SevDesk, Belegposition, Abruf der Belege (`list_vouchers`) |
| [sevdesk-abgleich.md](sevdesk-abgleich.md) | `app/sevdesk_matching.py` — Belegabzug, sichere und ähnliche Treffer, Entscheidungen, Anzeigezustand |
| [kontext-einstufung.md](kontext-einstufung.md) | `app/context_classification.py`, `app/invoice_overview.py` — Einstufung „IT-Consulting“, Filter-Bereiche, Übersichtszeilen |
| [sync-und-aktionen.md](sync-und-aktionen.md) | `app/paperless_sync.py`, `app/sevdesk_export_checks.py`, Worker-Loop, UI-Routen |
| [rechnungs-ui.md](rechnungs-ui.md) | Rechnungs-UI: Export-Übersicht, Dokumentdatum, Spalten-Sortierung, Dokumentvorschau |
| [empfaenger-zuordnung.md](empfaenger-zuordnung.md) | Empfänger pro Dokument (select-Feld) + KI-Vorschlag inkl. IT-Wahrscheinlichkeit (`app/recipient_llm.py`) |
| [dokumentansicht.md](dokumentansicht.md) | `app/main.py` (Routen `/paperless/{id}`, Vorschau-Proxy, Seitenleiste), `app/paperless_sync.py` (`load_document_view`, Namens-Cache), `app/static/app.js` (Seitenleiste) | Dokumentansicht eines Paperless-Dokuments als Seite und Seitenleiste, lesend bis auf Lector-Angaben |
| [scan-verknuepfung.md](scan-verknuepfung.md) | `app/paperless_link.py` (Job), `app/paperless.py` (`find_documents`), `app/pipeline.py` (`mark_consumed`), `app/main.py` (`/documents/{id}/original`, `_document_context`), `app/worker.py` (Task `paperless-link`) | Verknüpfung Lector-Vorgang ↔ Paperless-Dokument über die SHA-256-Prüfsumme, Altbestand über Dateinamen, Original-Vorschau, Vorgangsleiste, Filter „Nicht in Paperless“ |

Die Scan-Verknüpfung gehört nicht zum entkoppelten Rechnungsfeature. Ihr Ablageteil hängt an der
Pipeline, und der Job läuft schon bei `PAPERLESS_URL` und `PAPERLESS_TOKEN`, auch ohne
`FEATURE_PAPERLESS_SYNC` (siehe [scan-verknuepfung.md](scan-verknuepfung.md)).

Konfiguration aller Variablen: [../konfiguration.md](../konfiguration.md).

## Aktivierung (ENV)

Standardmäßig **deaktiviert**. Siehe `.env.example` für alle Variablen. Minimal:

```
FEATURE_PAPERLESS_SYNC=true
PAPERLESS_URL=http://webserver:8000
PAPERLESS_TOKEN=...
PAPERLESS_INVOICE_DOCTYPE=Rechnung

FEATURE_SEVDESK_EXPORT=true
SEVDESK_API_TOKEN=...
SEVDESK_TAG=sevdesk
```

Fehlende Custom Fields/Tags legt Lector bei `PAPERLESS_AUTO_CREATE_FIELDS=true` selbst an. Die
Kontext-Option **„IT-Consulting“** im Feld „Empfänger“ legt Lector **nicht** an. Sie muss in
Paperless vorhanden sein, sonst sind Rechnungen „nicht einstufbar“ (siehe
[kontext-einstufung.md](kontext-einstufung.md)).

## Datenhaltung

Tabellen in `app/db.py`:

- `paperless_invoices` — eine Zeile je Paperless-Rechnung, inkl. Zahldaten, Export- und
  Bezahlt-Status. Spalten für den Change `sevdesk-export-uebersicht`: `recipient_label` (gespiegelter
  Empfänger), `paperless_voucher_ref` (gespiegeltes Feld „SevDesk-Beleg“), `review_reason`
  (Grund des Status `review`) und `written_back_at` (Rückschrieb nach Paperless erledigt; leer = offen).
- `invoice_events` — Verlaufs-Log je Rechnung.
- `document_recipients` — Cache des KI-Vorschlags je Paperless-Dokument. Neu: `it_probability`.
- `sevdesk_vouchers` — lokaler Abzug der SevDesk-Belege (wird bei jedem Abruf als Ganzes ersetzt).
- `invoice_voucher_matches` — Zuordnung Rechnung ↔ Beleg mit Art (`id`, `similar`, `confirmed`,
  `rejected`) und Score.
- `sevdesk_sync_state` — Stand des letzten Belegabrufs (genau eine Zeile).
- Spalten an `documents` — Verknüpfung mit dem Paperless-Dokument (`paperless_id`, `paperless_link`,
  `output_hash`, `original_path`, `consumed_at`, `paperless_checked_at`). Siehe
  [scan-verknuepfung.md](scan-verknuepfung.md#datenmodell).

Neue Spalten und Tabellen kommen über `_migrate()` bzw. `CREATE TABLE IF NOT EXISTS` in
bestehende Datenbanken. Die Rollback-Anweisung vor einem Image-Rollback steht in
`prd/PROGRESS.md`.

Repository-Methoden in `app/repository.py` (u. a. `upsert_invoice`, `upsert_invoices` (gesammelt, ein Commit),
`set_giro_data`,
`set_sevdesk_status`, `set_paid`, `add_invoice_event`, `replace_vouchers`, `list_matches`,
`decide_match`, `correspondent_context_history`, `set_review`, `dismiss`, …). SSE-Tokens tragen das
Präfix `inv:` (Dokumente: `doc:`); der Belegabruf meldet `vouchers:sync`.
