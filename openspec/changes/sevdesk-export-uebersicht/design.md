# Design

## Context

Ausgangslage siehe `proposal.md`. Für das Vorgehen maßgeblich:

- `PaperlessSync` (`app/paperless_sync.py`) synchronisiert Rechnungen periodisch nach
  `paperless_invoices` und merkt getaggte Dokumente als `queued` vor. `export_invoice` sichert
  per `claim_for_export` gegen Doppel-Belege und unterscheidet `failed` von `uncertain`.
- `SevdeskClient` (`app/sevdesk.py`) kann nur schreiben (`uploadTempFile`, `saveVoucher`). Der
  Beleg wird mit `voucherPosSave: None` angelegt, also ohne Positionen und damit ohne Summe.
- Der Empfänger lebt im Paperless-select-Feld (Option `IT-Consulting`, ID
  `NmrJA5mYHkiWvDJZ`, live geprüft). Lector speichert lokal nur den KI-Vorschlag
  (`document_recipients`). `paperless_invoices` kennt den gesetzten Empfänger heute nicht.
- Der KI-Aufruf (`RecipientSuggester.suggest`) erzwingt das Tool `set_recipient` mit `recipient`,
  `confidence`, `reasoning`. Der Batch-Lauf sammelt nur Dokumente ohne Empfänger und
  überspringt jeden vorhandenen Cache-Eintrag.
- Die Übersicht muss ohne Paperless-, SevDesk- oder KI-Aufrufe beim Seitenaufruf laden
  (bisheriges Muster: Liste aus SQLite, Live-Refresh per SSE).

## Goals / Non-Goals

**Goals:**

- Alle Merkmale der Übersicht (Kontext, Export, Abgleich) kommen aus SQLite.
- Datenmodell für den späteren beidseitigen Abgleich ohne Migration nutzbar.
- Bestehende Schutzmechanismen des Exports (Claim, `uncertain`, Stale-Reset) bleiben unverändert
  wirksam.

**Non-Goals:**

- Keine eigene Ansicht „Belege ohne Rechnung“ (nur die Abfrage wird vorbereitet).
- Kein Abgleich über Dateiinhalt oder Hash (SevDesk liefert die Datei nicht ohne Weiteres).
- Keine Mehrwertsteuer-Aufteilung am Beleg; die Summe ist eine Bruttovorbelegung.

## Decisions

### 1. `/invoices` wird zur Export-Übersicht umgebaut, keine zweite Seite

Die Rechnungsliste zeigt heute schon dieselbe Menge (Rechnungstyp + Tag). Sie bekommt die
Spalten Kontext und Abgleich, die neuen Filter, eine Mehrfachauswahl und den Knopf „Abgleich
aktualisieren“. Die Detailseite zeigt zusätzlich Kandidaten mit Bestätigen/Verwerfen und die
Rückfrage vor dem Export.
*Alternative:* eigene Seite `/sevdesk` — verworfen, weil zwei Listen derselben Rechnungen mit
unterschiedlichen Spalten auseinanderlaufen.

### 2. Der Sync spiegelt Empfänger und Beleg-Vermerk je Rechnung

`_sync_invoices`/`_sync_sevdesk_tag` lesen aus dem bereits geladenen Dokument die Werte des
Empfänger-Felds und des Felds „SevDesk-Beleg“ und speichern sie in neuen Spalten
`recipient_label` und `paperless_voucher_ref`. Damit sind Quelle 1 der Einstufung, die
Korrespondenten-Historie und der sichere Treffer reine SQL-Abfragen.
*Alternative:* beim Seitenaufruf live aus Paperless lesen — verworfen (Latenz, Paperless-Ausfall
legt die Übersicht lahm).

### 3. Einstufung wird beim Lesen berechnet, nicht gespeichert

Eine Funktion `classify(invoice, history, cache)` liefert `(konfidenz, quelle, detail)`:

| Quelle | Bedingung | Konfidenz für IT-Consulting |
|---|---|---|
| Empfänger | `recipient_label` gesetzt | 1,0 bzw. 0,0 |
| Korrespondent | ≥ 2 andere Rechnungen mit entschiedenem Kontext, alle gleich | 0,9 bei 2, 0,95 ab 3 (bzw. 0,1 / 0,05) |
| KI | `document_recipients.it_probability` vorhanden | Wert der KI |

„Entschieden“ heißt: `recipient_label` gesetzt oder `sevdesk_status = exported` bzw. bestätigter
Treffer (beides zählt als IT-Consulting). Die Historie wird je Seitenaufruf einmal in
einer Abfrage geholt und in Python je Korrespondent gruppiert, nicht je Zeile. Die Filter „IT-Consulting“ und „unsicher“ laufen
deshalb in Python über die bereits geladene Menge; bei einigen hundert Rechnungen unkritisch.
*Alternative:* Einstufung als Spalte persistieren — verworfen, weil jede Empfänger-Änderung oder
jeder Export die Werte anderer Rechnungen desselben Korrespondenten ändert.

### 4. KI: zusätzliches Pflichtfeld im bestehenden Tool

`set_recipient` erhält `it_consulting_probability` (number, required). Der System-Block bekommt
einen Absatz, was eine Ausgabe des Kontexts ist (Label aus `SEVDESK_CONTEXT_LABEL`, beim Start
fest, damit Prompt-Caching erhalten bleibt). `RecipientSuggestion` und `document_recipients`
erhalten `it_probability` (NULL = nicht eingeschätzt; Werte außerhalb 0..1 → NULL).
`_collect_missing_ids` überspringt künftig nur Einträge mit Status ≠ `none` **und**
`it_probability IS NOT NULL`.
*Alternative:* eigener Klassifikator — mit dem Nutzer verworfen (doppelte Aufrufe, zweiter
Batch-Lauf).

### 5. SevDesk-Belege: Vollabruf in `sevdesk_vouchers`, Treffer in `invoice_voucher_matches`

```
paperless_invoices 1 --- n invoice_voucher_matches n --- 1 sevdesk_vouchers
                           kind: id | similar | confirmed | rejected
                           score REAL, decided_at
```

- `SevdeskClient.list_vouchers()` blättert `GET /Voucher` mit `limit`/`offset` und liefert
  ID, `voucherDate`, `supplierName` (bzw. Name des eingebetteten Kontakts), `sumGross`,
  `currency`, `description`, `status`.
- **Befund 1.1(a), 2026-11-01, gegen die echte API:** Antwort `{"objects": [...]}`, mit
  `countAll=true` zusätzlich `total`. `limit=1000` liefert den Gesamtbestand (306 Belege) in
  einem Aufruf, `offset` blättert korrekt. Alle Zahlen kommen als **Strings**
  (`sumGross: "0"`, `status: "50"`, `id: "…"`), Datumsfelder als ISO-Zeitstempel mit Zeitzone
  (Länge 25, z. B. `2026-10-03T00:00:00+02:00`) — das Mapping wandelt beides um und nimmt nur
  den Datumsteil. `supplierName` ist ein Feld des Belegs; ein eingebetteter Kontakt
  (`supplier` mit `embed=supplier`) fehlte bei den Stichproben und wird nur als Rückfall
  gelesen. Lectors bisherige Entwürfe haben `sumGross` `"0"` und sind deshalb nur über die
  ID zuzuordnen (wie in Risiken angenommen). Blättern bleibt eingebaut (Schrittweite 1000).
- Ein Abruf ersetzt den Bestand in einer Transaktion (Upsert + Löschen nicht mehr gelieferter
  IDs). Nur ein vollständig durchgelaufener Abruf löscht; ein abgebrochener ändert nichts
  (Spec: gescheiterter Abruf behält den Abzug). `sevdesk_sync_state` hält `last_success_at`,
  `last_error`, `last_error_at`.
- Nach jedem Abruf wird das Matching neu berechnet: `id`-Treffer aus `sevdesk_voucher_id` bzw.
  `paperless_voucher_ref`; `similar`-Treffer werden gelöscht und neu ermittelt;
  `confirmed`/`rejected` bleiben unangetastet.
- Ein erfolgreicher Export fügt den neuen Beleg sofort in den Abzug ein, damit der sichere
  Treffer ohne Warten auf den nächsten Abruf sichtbar ist.
- Abruf im bestehenden `_paperless_loop` mit eigenem Intervall (`SEVDESK_VOUCHER_SYNC_MINUTES`,
  Standard 60) und per Route `POST /invoices/sevdesk-refresh`; ein `asyncio.Lock` verhindert
  Überlappung.

*Alternative:* Belege je Rechnung gezielt in SevDesk suchen — verworfen: viele Einzelaufrufe,
und der beidseitige Abgleich bräuchte trotzdem den Vollbestand.

### 6. Score der ähnlichen Treffer

Kandidaten: gleicher Betrag (|Δ| < 0,005), gleiche Währung, Belegdatum innerhalb
`SEVDESK_MATCH_WINDOW_DAYS` (Standard 14) um `document_date`, nicht anderweitig `id`/`confirmed`
vergeben, nicht für diese Rechnung `rejected`. Belege mit `sumGross` 0 gelten als „ohne Summe“
und sind nie ähnliche Kandidaten (Befund 1.1(a): Entwürfe ohne Position stehen auf 0).
`score = 0,6 · (1 − Δtage / Fenster) + 0,4 · namensähnlichkeit`. Die Namensähnlichkeit ist das
Maximum aus Token-Überdeckung und `difflib.SequenceMatcher`, beides nach Normalisierung
(Kleinschreibung, Rechtsformen wie GmbH/AG/SARL/Ltd/Inc entfernt), verglichen gegen
`creditor_name` und `correspondent`. Angezeigt ab `SEVDESK_MATCH_MIN_SCORE` (Standard 0,4).
Gleicher Betrag ist bereits das stärkste Signal; der Score ordnet nur, er entscheidet nicht.

### 7. Statusmodell

`SevdeskStatus` erhält `review` („zu prüfen“) und `dismissed` („verworfen“), dazu die Spalte
`review_reason`. `claim_for_export` bleibt bei seiner Ausschlussliste
(`exported`, `exporting`, `uncertain`), sodass `review` nach Bestätigung claim-bar ist.
`_sync_sevdesk_tag` vergibt `queued` weiterhin nur aus `none`; `dismissed` wird damit nicht
erneut vorgemerkt. Die Prüfung vor dem Export ist eine Funktion
`export_blockers(invoice) -> (hard, reasons)` und wird von Übersicht, Mehrfachexport und
Tag-Weg gleich verwendet. Die Route `POST /invoices/{id}/export` nimmt ein Feld `confirm=1`;
fehlt es bei vorhandenen Gründen, antwortet sie mit der Rückfrage statt zu exportieren.

### 8. Empfänger-Rückschrieb mit Nachholung

`_write_back_export` setzt zusätzlich das Empfänger-Feld auf die Options-ID der Kontext-Option
(über `_recipient_field_cached`). Scheitert der Rückschrieb, bleibt `written_back_at` leer; der
Sync versucht für `exported`-Rechnungen ohne `written_back_at` den Rückschrieb erneut
(idempotent: Felder setzen, Tag hinzufügen; die Notiz wird nur geschrieben, wenn sie noch nicht
existiert). Lokal wird `recipient_label` sofort gesetzt.

### 9. Summe über eine Belegposition

SevDesk berechnet Belegsummen aus Positionen. Bei gesichertem Betrag (`giro_status` in
`ready`, `edited`) sendet der Export eine Position in `voucherPosSave` mit `sumGross`, Steuersatz
0 und dem Rechnungstitel als Text; sonst bleibt `voucherPosSave: None`.

**Befund 1.1(b), 2026-11-01 — Änderung gegenüber der ersten Fassung:** In Systemversion 2.0
braucht die Position ein Buchungskonto (`accountDatev`), keine `accountingType`. Ein Testentwurf
mit `accountDatev` 4279 („6837 laufende Gebühren für Lizenzen“, das meistgenutzte Konto des
Mandanten), `taxRate` 0, `net` false, `sumGross` 1,00 und `taxRule` 10 wurde mit HTTP 201
angenommen und zurückgelesen als `sumGross` 1 / `sumNet` 1 / `status` 50 (danach gelöscht).
Daraus folgt: neue ENV `SEVDESK_ACCOUNT_DATEV_ID` (ohne Standardwert). **Nur wenn sie gesetzt
ist**, sendet der Export die Position mit Betrag; ohne sie bleibt der Export wie bisher ohne
Summe. Das Konto ist eine Vorbelegung, die endgültige Kontierung erfolgt in SevDesk.
Konto-IDs lassen sich über `GET /ReceiptGuidance/forAllAccounts` nachschlagen
(`forTaxRule?taxRule=10` antwortet mit HTTP 422 „TaxRule 10 is not supported“).

## Risks / Trade-offs

- [Neue Statuswerte brechen ein Rollback auf die alte Version (Enum-Parse schlägt fehl)] →
  Rollback-Schritt: `UPDATE paperless_invoices SET sevdesk_status='none' WHERE sevdesk_status IN
  ('review','dismissed')`; in `PROGRESS.md` festgehalten.
- [Mehr Tokens je KI-Aufruf und ein Nachlauf über bereits bewertete Dokumente] → einmalige Kosten;
  der Nutzer steuert die Menge je Lauf wie bisher über das Limit.
- [Die KI überschätzt geschäftliche Rechnungen] → Quelle 1 und 2 haben Vorrang; die Schwelle ist
  konfigurierbar; exportiert wird nie automatisch nur aufgrund der Einstufung.
- [Vollabruf wird bei vielen Belegen langsam] → läuft im Hintergrund, stündlich; bei Bedarf
  später auf Zeitraum begrenzen (Löscherkennung dann nur im Zeitraum).
- [Betrag in Fremdwährung oder Teilzahlungen] → nur exakter Betrag und gleiche Währung; ein
  fehlender Treffer heißt nicht „sicher nicht vorhanden“, die Übersicht formuliert das so.
- [Felder von `GET /Voucher` weichen von der Annahme ab] → Task 1.1 prüft vor dem Bau gegen die
  echte API; Mapping ist an einer Stelle gekapselt.

## Migration Plan

1. `_migrate()` ergänzt Spalten (`recipient_label`, `paperless_voucher_ref`, `review_reason` an
   `paperless_invoices`; `it_probability` an `document_recipients`) und legt die neuen Tabellen
   mit `CREATE TABLE IF NOT EXISTS` an.
2. Nach dem Deployment füllt der erste Sync die gespiegelten Felder, der erste Belegabruf den
   Abzug und das Matching. Bis dahin zeigt die Übersicht „Abgleich nicht verfügbar“.
3. Der Nutzer startet einen Batch-Lauf der Empfänger-Zuordnung, um Einschätzungen nachzuholen.
4. Rollback: Image zurückrollen und die SQL-Anweisung aus den Risiken ausführen; neue Spalten und
   Tabellen stören die alte Version nicht.

## Open Questions

- Ob die Gewichte des Scores (0,6/0,4) gut trennen, zeigt erst der echte Bestand; sie lassen sich
  ohne Spec-Änderung anpassen.
