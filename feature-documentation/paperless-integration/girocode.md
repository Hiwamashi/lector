# GiroCode (EPC069-12)

**Modul:** `app/girocode.py` — engine-unabhängig und ohne Netzwerk/IO, daher voll unit-testbar
(`tests/test_girocode.py`).

## Zweck

Aus einer Rechnung die SEPA-Zahldaten gewinnen und als **GiroCode** (EPC-QR-Code) rendern, den
man mit der Banking-App scannt, um eine Überweisung vorauszufüllen.

## Datenmodell

`PaymentData(creditor_name, iban, bic, amount, currency, purpose)`.
`is_payable` ist `True`, sobald Empfängername **und** eine per Mod-97 gültige IBAN vorliegen.

## Extraktion

1. **E-Rechnung (deterministisch)** — `extract_from_einvoice_xml(data: bytes)`:
   - Unterstützt **UBL** (`Invoice`, XRechnung) und **UN/CEFACT CII**
     (`CrossIndustryInvoice`, ZUGFeRD/Factur-X).
   - Sucht namespace-agnostisch über lokale Element-Namen
     (`IBANID`/`PayeeFinancialAccount`, `BICID`, `DuePayableAmount`/`PayableAmount`,
     `SellerTradeParty`/`AccountingSupplierParty`, `PaymentReference`/Rechnungs-ID).
   - ⚠️ ET-Elemente ohne Kinder sind „falsy" — daher kein `or`-Chaining auf Elementen,
     sondern explizite `is None`-Prüfungen.
2. **OCR-Text (heuristisch)** — `extract_from_ocr_text(text, fallback_creditor=…)`:
   - IBAN per Regex + Mod-97-Validierung (`valid_iban`).
   - Betrag bevorzugt in der Nähe von Schlüsselwörtern („Zahlbetrag", „Gesamtbetrag" …),
     deutsches Zahlenformat (`1.234,56`).
   - Gläubigername als Fallback aus dem Paperless-**Korrespondenten**.

## QR-Erzeugung

- `epc_payload(data)` baut den EPC069-12-Payload (Version `002`, UTF-8, `SCT`). Pflicht:
  Name + gültige IBAN; sonst `ValueError`. Betrag wird als `EUR123.45` formatiert; leere
  Endfelder werden weggelassen.
- `qr_svg(data)` rendert über `segno` ein eigenständiges **SVG** (Inline-Einbettung im HTML).
  Wichtig: `segno` schreibt SVG als Bytes → über `io.BytesIO` rendern und dekodieren.
