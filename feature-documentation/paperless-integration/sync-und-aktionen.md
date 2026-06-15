# Sync-Loop & UI-Aktionen

**Module:** `app/paperless_sync.py` (Orchestrierung), `app/worker.py` (`_paperless_loop`),
`app/main.py` (Routen), Templates `invoices.html` / `invoice_detail.html` + Partials.

## PaperlessSync

Einziger Ort, der Paperless- und SevDesk-Client zusammenführt. Zentrale `_resolve(client)`
löst (und cached) IDs für Dokumententyp, Tags und Custom Fields auf — legt fehlende bei
`PAPERLESS_AUTO_CREATE_FIELDS=true` an.

### `sync_once()` (periodisch)

Läuft im Worker alle `PAPERLESS_SYNC_INTERVAL_SECONDS`, nur wenn `enabled` (Feature-Flag +
URL + Token). Per `asyncio.Lock` gegen Überlappung gesichert.

1. `_sync_invoices` — Dokumente mit dem Rechnungs-Dokumententyp listen, je Dokument
   `upsert_invoice`. Ein `synced`-Event wird nur bei echter Änderung geschrieben (Neuanlage
   bzw. geänderter Titel/Korrespondent — Vergleich mit `get_invoice_by_paperless` vor dem
   Upsert), damit `invoice_events` bei Idle-Syncs nicht unbegrenzt wächst. Bei
   `giro_status == none`: Zahldaten extrahieren (E-Rechnung aus XML bzw. eingebetteter XML via
   `detection.extract_embedded_invoice_xml`, sonst OCR-Heuristik), speichern und — falls
   `ready` — IBAN/Betrag als Custom Fields zurückschreiben.
2. `_sync_sevdesk_tag` — Dokumente mit `SEVDESK_TAG` listen, als `queued` vormerken. Bei
   `SEVDESK_AUTO_EXPORT=true` direkt exportieren.

### UI-Aktionen

- `save_giro_edits(...)` — manuell korrigierte Zahldaten speichern (`giro_status=edited`),
  optional Rückschrieb.
- `export_invoice(id)` — Original aus Paperless laden → SevDesk-Beleg anlegen → Status
  `exported` + Rückschrieb (Custom Field `SevDesk-Beleg`, Datum, Tag `sevdesk-exportiert`,
  Notiz mit Beleg-Link).
  - **Doppel-Beleg-Schutz (Race):** Vor dem Upload beansprucht `repo.claim_for_export` die
    Rechnung atomar (bedingtes `UPDATE … WHERE sevdesk_status NOT IN
    ('exported','exporting','uncertain')` → setzt den transienten Status `exporting`). Nur ein
    Aufrufer gewinnt; gleichzeitige Aufrufe (UI-Doppelklick, Auto-Export vs. manueller Klick,
    Re-Sync) werden übersprungen. Der UI-Button ist bei `exported`/`uncertain` deaktiviert.
  - **Fehlerklassifizierung:** Der Export ist in Schritte getrennt, um Doppel-Belege bei
    Wiederholung zu vermeiden:
    - Download + `uploadTempFile` legen **keinen** Beleg an → Fehler sind eindeutig
      **retrybar** (`failed`, wieder claim-bar).
    - `saveVoucher` legt den Beleg an. Nur eine **4xx**-Antwort ist eine eindeutige
      Client-Ablehnung (kein Beleg) → `failed` (retrybar). **5xx**-Serverfehler sind
      **mehrdeutig** (der Server kann den Beleg erzeugt haben, bevor die Fehlerantwort kam),
      ebenso Transportfehler/Timeout und eine fehlende Beleg-ID in einer 200-Antwort → Status
      `uncertain`, **nicht** auto-retrybar. Der Nutzer muss in SevDesk prüfen, ob der Beleg
      existiert, bevor erneut exportiert wird.
  - Bei einem harten Absturz **während** des Uploads bleibt der Status auf `exporting`. Beim
    nächsten Start bereinigt `repo.reset_stale_exports()` (Aufruf im Lifespan) solche
    verwaisten Claims auf `uncertain` — nicht auf `failed`, weil unklar ist, ob bereits ein
    Beleg angelegt wurde. So bleibt die Rechnung nicht dauerhaft in `exporting` blockiert,
    wird aber bewusst **nicht** automatisch erneut exportiert (manuelle Prüfung in SevDesk).
- `set_paid(id, paid)` — als überwiesen markieren; Rückschrieb (Custom Field `Überwiesen`,
  Tag `überwiesen`, Notiz).

## Worker-Anbindung

`Worker.__init__` nimmt optional `paperless_sync`. Ist das Feature aktiv, startet `start()`
zusätzlich den Task `_paperless_loop`, der `sync_once()` im Intervall aufruft. Netzwerk-I/O
läuft direkt im asyncio-Loop (kein Thread-Pool nötig, anders als die CPU-lastige OCR-Pipeline).

## Routen (`app/main.py`)

| Route | Zweck |
|---|---|
| `GET /invoices` | Rechnungsliste (+ Filter SevDesk-Status / Suche) |
| `GET /fragment/invoices` | Tabellenkörper (SSE-Refresh) |
| `GET /invoices/{id}` | Detail mit GiroCode-QR + Zahldaten-Formular |
| `GET /fragment/invoices/{id}` | Detail-Body (SSE-Refresh) |
| `POST /invoices/{id}/giro` | Zahldaten speichern |
| `POST /invoices/{id}/export` | Nach SevDesk exportieren |
| `POST /invoices/{id}/paid` | Überwiesen-Status umschalten |

Live-Updates: `EventBus` verteilt Tokens `inv:<id>`; `app/static/app.js` aktualisiert die
passende Liste/Detailansicht.
