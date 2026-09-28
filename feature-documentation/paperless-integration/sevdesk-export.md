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
2. `save_voucher_from_temp(temp_filename, …)` → `POST /Voucher/Factory/saveVoucher`.
   Legt den Beleg an und referenziert die Temp-Datei. Liefert `VoucherResult(voucher_id, link)`.

`export_document(...)` fasst beide Schritte zusammen.

## Pflichtfelder des Belegs

Auch ein **Entwurf** muss für SevDesk buchhalterisch vollständig sein. Fehlt eines dieser
Felder, antwortet `saveVoucher` mit **HTTP 422 Unprocessable Entity**:

| Feld | Wert in Lector | Herkunft |
|---|---|---|
| `voucherType` | `"VOU"` | fest |
| `status` | `50` (Entwurf) | fest |
| `creditDebit` | `"C"` | fest (Eingangsbeleg) |
| `taxRule` | `{"id": "10", "objectName": "TaxRule"}` | Konstante `TAX_RULE_ID` |
| `voucherDate` | `YYYY-MM-DD` | `PaperlessInvoice.document_date`, sonst Exporttag |
| `deliveryDate` | = `voucherDate` | abgeleitet |
| `currency` | z. B. `"EUR"` | `PaperlessInvoice.currency` |
| `supplierName` | Name des Zahlungsempfängers | `creditor_name`, sonst `correspondent` |
| `description` | Rechnungstitel | `PaperlessInvoice.title`, sonst Dateiname |

`taxRule` **10** ist „Nicht vorsteuerabziehbare Aufwendungen" — die Regel, mit der die
bestehenden Belege des Mandanten geführt werden. Sie ist bewusst nur eine Vorbelegung am
Entwurf; die endgültige steuerliche Zuordnung erfolgt in SevDesk. Die Liste aller Regeln
liefert `GET /TaxRule`.

Ein Feld `type` gibt es im Voucher-Modell **nicht** — es wurde früher mitgesendet und von
der API nie akzeptiert.

## Fehlerbehandlung

`raise_for_status()` von httpx nennt nur Status und URL („Client error '422 Unprocessable
Entity' for url …") — der eigentliche Grund steht ausschließlich im Antwortkörper, den
SevDesk als `{"error": {"message": …, "exceptionUUID": …}}` liefert.

`_raise_for_status()` ersetzt deshalb `raise_for_status()` und hängt diese Meldung an den
Fehlertext an. Der Ausnahmetyp bleibt bewusst `httpx.HTTPStatusError`, weil
`PaperlessSync.export_invoice` daran retrybare Ablehnungen (4xx) von mehrdeutigen
Serverfehlern (5xx) unterscheidet. Die angereicherte Meldung landet über
`_mark_export_failed` in `error_message` und damit in der Rechnungs-UI.

## Hinweise

- Der E-Rechnungs-Upload als Beleg setzt SevDesk-**Systemversion 2.0** voraus (API-Feature
  seit 2024-11).
- Fehler werden als `SevdeskError` bzw. `httpx.HTTPStatusError` geworfen;
  `PaperlessSync.export_invoice` fängt sie ab und setzt den Rechnungsstatus auf `failed`
  (retrybar) oder `uncertain` (kein Auto-Retry).
- Tests: `tests/test_sevdesk.py` hält Pflichtfelder und Fehlerweitergabe über
  `httpx.MockTransport` fest.
