# Design

## Context

`PaperlessSync._correspondent_name(client, doc, corr_map)` liefert den Namen aus der Karte des Laufs,
sonst über `client.get_correspondent_name`. Jede Ausnahme des Einzelabrufs wird geschluckt und als
`None` zurückgegeben. Diesen Rückgabewert nutzen drei Stellen:

1. `_upsert_row` für `InvoiceUpsert.correspondent` (Rechnungs-Sync und SevDesk-Tag-Schritt),
2. `_extract_and_store` als GiroCode-Kreditor (`girocode_creditor_from_correspondent`),
3. die Empfänger-Vorschläge (`_suggest_for_doc`).

Im Repository gibt es schon das Muster „nicht gesetzt“: `_Unset`/`_UNSET` für `recipient_label` und
`paperless_voucher_ref`. `_upsert_invoice_locked` nimmt solche Felder weder in den Vergleich noch in
das `UPDATE` auf. `_sync_invoices` erzeugt das `synced`-Ereignis, wenn `before.correspondent !=
row.correspondent`.

## Goals / Non-Goals

**Goals:**
- Ein vorübergehender Fehler beim Einzelabruf ändert keine gespeicherten Daten und erzeugt keine
  Ereignisse.
- Die Unterscheidung bleibt klein und am bestehenden `_Unset`-Muster.

**Non-Goals:**
- Kein Wiederholversuch des Einzelabrufs im selben Lauf.
- Keine Änderung an GiroCode-Kreditor und Empfänger-Vorschlag (dort bedeutet „kein Name“ schon das
  Richtige: auf andere Quellen zurückfallen).
- Kein Abbruch des Laufs, wenn die Karte geladen wurde und nur einzelne Abrufe scheitern.

## Decisions

**D1 – Eigene Auflösung für den Sync statt geänderter Rückgabe von `_correspondent_name`.**
Eine neue Hilfsfunktion (z. B. `_correspondent_for_sync`) liefert `str | None | _Unset`: `None`, wenn
das Dokument keinen Korrespondenten hat; den Namen bei Erfolg; `_UNSET`, wenn der Einzelabruf eine
Ausnahme wirft. `_correspondent_name` behält Signatur und Verhalten für die Stellen 2 und 3 und nutzt
intern dieselbe Logik. Alternative: `_correspondent_name` liefert `_UNSET` für alle — verworfen, weil
die anderen Aufrufer dann jeweils `_UNSET` zu `None` umbiegen müssten.

**D2 – `InvoiceUpsert.correspondent` darf `_UNSET` sein.**
`_upsert_invoice_locked` behandelt `correspondent` wie `recipient_label`: Ist der Wert `_UNSET`, fehlt
das Feld in Vergleich und `UPDATE`. Beim `INSERT` wird `_UNSET` als `NULL` geschrieben. `upsert_invoice`
(Einzelweg) übernimmt den Typ ebenfalls, damit beide Wege gleich bleiben.

**D3 – Ereignisprüfung berücksichtigt `_UNSET`.**
In `_sync_invoices` zählt der Korrespondent nur als geändert, wenn `row.correspondent` kein `_UNSET`
ist und sich vom gespeicherten Wert unterscheidet. Titeländerungen erzeugen das Ereignis wie bisher.

**D4 – Warnung im Log.**
Beim Fehlschlag: `log.warning("Korrespondent %s nicht auflösbar: %s", id, type(error).__name__)`.
Bei vielen Dokumenten desselben Korrespondenten kann das je Lauf mehrfach erscheinen. Das ist
hinnehmbar, weil der Fall selten ist und die Karte den Normalfall abdeckt.

**D5 – HTTP 404 beim Einzelabruf.**
Auch ein 404 (Korrespondent zwischen Kartenbau und Abruf gelöscht) gilt als „nicht auflösbar“ und
behält den Wert. Im nächsten Lauf hat das Dokument entweder einen anderen oder keinen Korrespondenten,
dann greift der Normalfall.

## Risks / Trade-offs

- [Ein dauerhaft nicht abrufbarer Korrespondent hält einen veralteten Namen] → Die Warnung im Log macht
  den Fall sichtbar; die Karte des nächsten Laufs löst ihn im Regelfall.
- [`_UNSET` im Typ von `correspondent` kann an Stellen durchrutschen, die `str | None` erwarten] →
  `_UNSET` entsteht nur in `_upsert_row` und endet im Repository; Tests prüfen Vergleich, Insert und
  Ereignis.
