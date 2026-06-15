# SevDesk-Beleg-Export

**Modul:** `app/sevdesk.py` — asynchroner `httpx`-Client für die
[SevDesk-API](https://api.sevdesk.de/). Authentifizierung per API-Token im
`Authorization`-Header (ohne Schema-Präfix).

## Umfang (bewusst leichtgewichtig)

Das Dokument (PDF/E-Rechnung) wird als **Beleg (Voucher) im Status „Entwurf" (50)** nach
SevDesk übertragen. Die eigentliche Verbuchung (Kategorie, Kontakt, Betrag) erfolgt
anschließend in SevDesk — Lector bucht **nicht** vor.

## Ablauf (zwei Schritte laut API)

1. `upload_temp_file(content, filename, mime)` → `POST /Voucher/Factory/uploadTempFile`
   (multipart). Liefert den temporären Dateinamen aus `objects.filename`.
2. `save_voucher_from_temp(temp_filename, description=…)` → `POST /Voucher/Factory/saveVoucher`.
   Legt den Beleg an und referenziert die Temp-Datei. Liefert `VoucherResult(voucher_id, link)`.

`export_document(...)` fasst beide Schritte zusammen.

## Hinweise

- Der E-Rechnungs-Upload als Beleg setzt SevDesk-**Systemversion 2.0** voraus (API-Feature
  seit 2024-11).
- Fehler werden als `SevdeskError` geworfen; `PaperlessSync.export_invoice` fängt sie ab und
  setzt den Rechnungsstatus auf `failed` inkl. Fehlermeldung.
