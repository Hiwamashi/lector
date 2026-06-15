# Paperless-Integration: GiroCode & SevDesk-Export

Ein **entkoppeltes Zusatz-Feature**, das unabhängig vom OCR-Veredelungspfad
(`scan-in → consume`) läuft. Während der Kern Lector **vor** Paperless sitzt, dreht dieses
Feature die Richtung um: Lector liest Rechnungen **aus** Paperless, erzeugt GiroCodes für die
Überweisung und exportiert getaggte Dokumente nach SevDesk — und schreibt Status zurück ans
Paperless-Dokument.

```
Paperless (Dokumententyp = "Rechnung")
   │  [PaperlessSync._sync_invoices]  (periodisch im Worker)
   ▼
GiroCode-Zahldaten  ──► E-Rechnung (XRechnung/ZUGFeRD): deterministisch aus XML
   │                └─► sonst: Heuristik aus OCR-Text + Korrespondent
   ▼
Lector-UI: /invoices  ── QR anzeigen, Zahldaten editieren ──► Rückschrieb (Custom Fields)

Paperless-Tag (SEVDESK_TAG)
   │  [PaperlessSync._sync_sevdesk_tag]
   ▼
vorgemerkt (queued) ── manuell/auto ──► SevDesk-Beleg-Upload ──► Rückschrieb
                                          (Custom Field, Tag, Notiz)
```

## Module ↔ Funktion

| Datei | Funktion |
|---|---|
| [girocode.md](girocode.md) | `app/girocode.py` — Zahldaten-Extraktion + EPC069-12-QR |
| [paperless-client.md](paperless-client.md) | `app/paperless.py` — REST-Client (lesen/zurückschreiben) |
| [sevdesk-export.md](sevdesk-export.md) | `app/sevdesk.py` — Beleg-Upload nach SevDesk |
| [sync-und-aktionen.md](sync-und-aktionen.md) | `app/paperless_sync.py`, Worker-Loop, UI-Routen |
| [rechnungs-ui.md](rechnungs-ui.md) | Rechnungs-UI: Dokumentdatum, Spalten-Sortierung, Dokumentvorschau |
| [empfaenger-zuordnung.md](empfaenger-zuordnung.md) | Empfänger pro Dokument (select-Feld) + KI-Vorschlag (`app/recipient_llm.py`) |

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

Fehlende Custom Fields/Tags legt Lector bei `PAPERLESS_AUTO_CREATE_FIELDS=true` selbst an.

## Datenhaltung

Neue Tabellen in `app/db.py`: `paperless_invoices` (eine Zeile je Paperless-Rechnung,
inkl. Zahldaten + Export-/Bezahlt-Status) und `invoice_events` (Verlaufs-Log). Repository-
Methoden in `app/repository.py` (`upsert_invoice`, `set_giro_data`, `set_sevdesk_status`,
`set_paid`, `add_invoice_event`, …). SSE-Tokens tragen das Präfix `inv:` (Dokumente: `doc:`).
