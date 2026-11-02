# SevDesk-Beleg-Export

**Modul:** `app/sevdesk.py` — asynchroner `httpx`-Client für die
[SevDesk-API](https://api.sevdesk.de/). Authentifizierung per API-Token im
`Authorization`-Header (ohne Schema-Präfix). Der Client schreibt Belege und liest sie
(`list_vouchers`, für den Abgleich in [sevdesk-abgleich.md](sevdesk-abgleich.md)).

Wann und unter welchen Bedingungen exportiert wird (Übersicht, Tag-Weg, Rückfragen, Sperren),
steht in [sync-und-aktionen.md](sync-und-aktionen.md).

## Umfang (bewusst leichtgewichtig)

Das Dokument (PDF/E-Rechnung) wird als **Beleg (Voucher) im Status „Entwurf" (50)** nach
SevDesk übertragen. Die eigentliche Verbuchung (Kategorie, Kontakt, Betrag) erfolgt
anschließend in SevDesk — Lector bucht **nicht** vor. Eine Ausnahme ist die optionale
Belegposition mit Betrag (siehe unten): Sie setzt nur die Bruttosumme, keine Kategorie.

## Ablauf (zwei Schritte laut API)

1. `upload_temp_file(content, filename, mime)` → `POST /Voucher/Factory/uploadTempFile`
   (multipart). Liefert den temporären Dateinamen aus `objects.filename`.
2. `save_voucher_from_temp(temp_filename, …)` → `POST /Voucher/Factory/saveVoucher`.
   Legt den Beleg an und referenziert die Temp-Datei. Liefert `VoucherResult(voucher_id, link)`.
   Der Link lautet `https://my.sevdesk.de/fi/edit/type/VOU/id/<id>`.

`export_document(...)` fasst beide Schritte zusammen. Der Export in
`PaperlessSync.export_invoice` ruft beide Schritte **einzeln** auf, weil zwischen ihnen die
Fehlerklassifizierung liegt (siehe [sync-und-aktionen.md](sync-und-aktionen.md)).

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
| `currency` | z. B. `"EUR"` | `PaperlessInvoice.currency`, sonst `"EUR"` |
| `supplierName` | Name des Zahlungsempfängers | `creditor_name`, sonst `correspondent` |
| `description` | Rechnungstitel | `PaperlessInvoice.title`, sonst Dateiname |

`taxRule` **10** ist „Nicht vorsteuerabziehbare Aufwendungen" — die Regel, mit der die
bestehenden Belege des Mandanten geführt werden. Sie ist bewusst nur eine Vorbelegung am
Entwurf; die endgültige steuerliche Zuordnung erfolgt in SevDesk. Die Liste aller Regeln
liefert `GET /TaxRule`.

Ein Feld `type` gibt es im Voucher-Modell **nicht** — es wurde früher mitgesendet und von
der API nie akzeptiert.

## Belegposition mit Betrag

Die Summe eines SevDesk-Belegs entsteht aus seinen Positionen. Ohne Position steht der Beleg
auf 0. Lector sendet deshalb eine Position **nur**, wenn beide Bedingungen gelten:

1. `SEVDESK_ACCOUNT_DATEV_ID` ist gesetzt (nicht leer), und
2. der Betrag ist gesichert: `giro_status` ist `ready` oder `edited` und `amount` ist bekannt.

Das prüft `PaperlessSync.export_invoice`. Die Position baut `SevdeskClient.save_voucher_from_temp`:

| Feld der Position | Wert |
|---|---|
| `objectName` | `"VoucherPos"` |
| `mapAll` | `true` |
| `accountDatev` | `{"id": <SEVDESK_ACCOUNT_DATEV_ID>, "objectName": "AccountDatev"}` |
| `taxRate` | `0` |
| `net` | `false` |
| `sumGross` | Betrag der Rechnung |
| `comment` | Rechnungstitel, auf 100 Zeichen gekürzt |

Fehlt eine der Bedingungen, bleibt `voucherPosSave` leer (`None`). Der Beleg wird dann wie
bisher **ohne Summe** angelegt.

- Das Konto ist eine **Vorbelegung**. Die endgültige Kontierung erfolgt in SevDesk.
- Konto-IDs lassen sich über `GET /ReceiptGuidance/forAllAccounts` nachschlagen (Befund aus
  dem Design, siehe unten).
- Der lokale Abzug übernimmt nach dem Export den gesendeten Betrag. Ohne Position bleibt die
  Summe leer, bis der nächste Abruf den Wert aus SevDesk liefert.

Die Startvalidierung verlangt für `SEVDESK_ACCOUNT_DATEV_ID` nur Ziffern (siehe
[konfiguration.md](../konfiguration.md)).

## Befund: SevDesk-Systemversion 2.0 (2026-11-01)

Die folgenden Aussagen stammen aus dem Design-Dokument des OpenSpec-Changes
(`openspec/changes/archive/2026-11-02-sevdesk-export-uebersicht/design.md`, Entscheidung 9, Befund 1.1(b)). Sie
wurden gegen die echte API geprüft. Der Code kann sie nicht selbst belegen.

- Die Belegposition braucht ein **Buchungskonto** (`accountDatev`). Eine Angabe über
  `accountingType` ist in Systemversion 2.0 nicht mehr der Weg. Die erste Fassung des Designs
  nannte noch `accountingType`; sie ist überholt.
- Ein Testentwurf mit `accountDatev` 4279 (das meistgenutzte Konto des Mandanten),
  `taxRate` 0, `net` false, `sumGross` 1,00 und `taxRule` 10 wurde mit **HTTP 201**
  angenommen. Zurückgelesen wurde `sumGross` 1, `sumNet` 1 und `status` 50. Der Testentwurf
  wurde danach gelöscht.
- `GET /ReceiptGuidance/forTaxRule?taxRule=10` antwortet mit **HTTP 422** („TaxRule 10 is not
  supported“). Für die Konto-Suche nutzt Lector den Weg über `GET /ReceiptGuidance/forAllAccounts`.
  Das ist ein Befund aus der Prüfung, im Code wird nur die Konto-ID aus der Konfiguration
  verwendet.

## Abruf der Belege (`list_vouchers`)

`SevdeskClient.list_vouchers(*, page_size=1000)` liest den Belegbestand für den Abgleich.

- Aufruf: `GET /Voucher` mit `limit` (Seitengröße, Standard 1000) und `offset`. Die Schleife
  blättert, bis eine Seite kürzer als `page_size` ist. Lector sendet `countAll` nicht. Das Ende
  erkennt die Schleife allein an der Seitenlänge.
- Antwort: `{"objects": [ … ]}`. Fehlt `objects` oder ist es keine Liste (auf jeder Seite, auch auf
  Folgeseiten, auch bei einem Antwortkörper, der kein Objekt ist), wirft die Methode `SevdeskError`.
  Der Abruf gilt dann als fehlgeschlagen, nicht als „0 Belege“. Der Abzug bleibt unverändert. Eine
  leere Liste (`{"objects": []}`) ist dagegen gültig und bedeutet 0 Belege.
- Objekte ohne `id` werden übersprungen.
- Ein HTTP-Fehler auf einer Seite bricht den gesamten Abruf ab
  (`_raise_for_status`, Schritt `Voucher`). Der Abzug bleibt dann unverändert, siehe
  [sevdesk-abgleich.md](sevdesk-abgleich.md).
- Eine 200-Antwort ohne Objektliste ist ebenfalls ein Abbruch, aber als `SevdeskError` (nicht als
  `httpx.HTTPStatusError`). Auch hier bleibt der Abzug unverändert.

Das Mapping steht an **einer** Stelle, `_voucher_from_api` in `app/sevdesk.py`:

| SevDesk-Feld | Lector-Feld (`SevdeskVoucher`) | Umwandlung |
|---|---|---|
| `id` | `voucher_id` | als Text; leer oder fehlend → Objekt wird verworfen |
| `voucherDate` | `voucher_date` | nur der Datumsteil als `YYYY-MM-DD`; nicht lesbar → `None` |
| `supplierName` | `supplier_name` | Text; leer → Rückfall auf `supplier.name` (eingebetteter Kontakt) |
| `sumGross` | `sum_gross` | Text → Zahl; Komma als Dezimaltrenner wird akzeptiert; nicht lesbar → `None` |
| `currency` | `currency` | Text |
| `description` | `description` | Text |
| `status` | `status` | Text (z. B. `"50"`) |

Befunde aus der Prüfung (Design, Befund 1.1(a), 2026-11-01):

- Die Antwort liefert **alle Zahlen und den Status als Strings** (`sumGross: "0"`,
  `status: "50"`). Das Mapping wandelt sie um.
- Datumsfelder sind ISO-Zeitstempel mit Zeitzone, zum Beispiel `2026-10-03T00:00:00+02:00`.
  Lector übernimmt nur die ersten zehn Zeichen. Das Datum ist also das Datum aus der Antwort,
  ohne Umrechnung in eine andere Zeitzone.
- `limit=1000` lieferte bei der Prüfung den gesamten Bestand (306 Belege) in einem Aufruf.
  `offset` blättert korrekt.
- Ein eingebetteter Kontakt (`supplier`) fehlte bei den Stichproben. Er wird nur als Rückfall
  gelesen.
- Entwürfe ohne Position haben `sumGross` `"0"`. Sie kommen als `sum_gross = 0.0` in den Abzug
  und sind damit nie ähnliche Kandidaten (siehe [sevdesk-abgleich.md](sevdesk-abgleich.md)).

Die Tests in `tests/test_sevdesk.py` sind für diesen Abruf vorgesehen (zwei Seiten über
`httpx.MockTransport`, fehlender Lieferantenname). Die Testinhalte wurden für diese Doku nicht
im Einzelnen geprüft.

## Fehlerbehandlung

`raise_for_status()` von httpx nennt nur Status und URL („Client error '422 Unprocessable
Entity' for url …") — der eigentliche Grund steht ausschließlich im Antwortkörper, den
SevDesk als `{"error": {"message": …, "exceptionUUID": …}}` liefert.

`_raise_for_status()` ersetzt deshalb `raise_for_status()` und hängt diese Meldung an den
Fehlertext an. Der Ausnahmetyp bleibt bewusst `httpx.HTTPStatusError`, weil
`PaperlessSync.export_invoice` daran retrybare Ablehnungen (4xx) von mehrdeutigen
Serverfehlern (5xx) unterscheidet. Die angereicherte Meldung landet über
`_mark_export_failed` in `error_message` und damit in der Rechnungs-UI.

Auch `saveVoucher` ohne Beleg-ID in der Antwort (HTTP 200) gilt als mehrdeutig, siehe
[sync-und-aktionen.md](sync-und-aktionen.md).

## Hinweise

- Der E-Rechnungs-Upload als Beleg setzt SevDesk-**Systemversion 2.0** voraus (API-Feature
  seit 2024-11).
- Fehler werden als `SevdeskError` bzw. `httpx.HTTPStatusError` geworfen;
  `PaperlessSync.export_invoice` fängt sie ab und setzt den Rechnungsstatus auf `failed`
  (retrybar) oder `uncertain` (kein Auto-Retry).
- Tests: `tests/test_sevdesk.py` hält Pflichtfelder und Fehlerweitergabe über
  `httpx.MockTransport` fest.
