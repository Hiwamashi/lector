# SevDesk-Abgleich: Belegabzug und Zuordnung zu Rechnungen

**Module:** `app/sevdesk_matching.py` (reine Matching-Logik, ohne I/O),
`app/paperless_sync.py` (`sync_vouchers`, `recompute_matches`, `decide_match`-Aufrufer),
`app/repository.py` (Abzug, Treffer, Sync-Zustand), `app/db.py` (Tabellen),
`app/worker.py` (`_paperless_loop`), `app/main.py` (Routen), `app/invoice_overview.py`
(Anzeigezustand je Zeile). Die Oberfläche ist in [rechnungs-ui.md](rechnungs-ui.md) beschrieben.

## Zweck

Vor einem Export soll sichtbar sein, ob in SevDesk schon ein passender Beleg liegt. Lector
ruft dafür die Belege aus SevDesk ab, hält sie lokal vor und ordnet jede Paperless-Rechnung
entweder **sicher** (über die Beleg-ID) oder **ähnlich** (über Betrag, Datum und Lieferant)
einem Beleg zu. Der Abgleich läuft nie beim Seitenaufruf gegen SevDesk, sondern immer aus
SQLite.

Die Zuordnung ist als eigene Beziehung modelliert (Tabelle `invoice_voucher_matches`), damit
ein späterer beidseitiger Abgleich (SevDesk-Belege ohne Paperless-Dokument) nur eine weitere
Ansicht wird. Die Abfrage dafür existiert bereits (`Repository.vouchers_without_invoice()`),
eine Route oder Oberfläche dazu gibt es **nicht**.

## Datenmodell

| Tabelle | Inhalt | Besonderheit |
|---|---|---|
| `sevdesk_vouchers` | Abzug der SevDesk-Belege: `voucher_id` (PK), `voucher_date`, `supplier_name`, `sum_gross`, `currency`, `description`, `status`, `last_seen_at` | Keine Beziehung zu Rechnungen; wird als Ganzes ersetzt |
| `invoice_voucher_matches` | Zuordnung: `invoice_id`, `voucher_id`, `kind`, `score`, `decided_at`, `created_at` (PK: `invoice_id` + `voucher_id`) | `voucher_id` hat **keinen** Fremdschlüssel auf den Abzug; ein `id`-Treffer darf also auf einen Beleg zeigen, der im Abzug fehlt |
| `sevdesk_sync_state` | Genau eine Zeile (`id = 1`): `last_success_at`, `last_error`, `last_error_at` | Stand des letzten Belegabrufs |

`kind` hat vier Werte (`MatchKind` in `app/models.py`):

| `kind` | Bedeutung | Quelle |
|---|---|---|
| `id` | sicher | automatisch: Beleg-ID aus Lectors Export oder aus dem Paperless-Feld „SevDesk-Beleg“ |
| `similar` | ähnlich, mit `score` | automatisch: Berechnung in `compute_matches` |
| `confirmed` | vom Nutzer als derselbe Beleg bestätigt | Nutzerentscheidung |
| `rejected` | vom Nutzer als anderer Beleg verworfen | Nutzerentscheidung |

Die Zeitstempel sind UTC im Format `YYYY-MM-DD HH:MM:SS`.

## Abzug: Abruf der Belege

### Auslöser

- **Periodisch:** `Worker._paperless_loop` (`app/worker.py`) ruft `PaperlessSync.sync_vouchers()`
  beim Start und danach alle `SEVDESK_VOUCHER_SYNC_MINUTES` Minuten auf. Die Prüfung läuft im
  Takt der Schleife (`PAPERLESS_SYNC_INTERVAL_SECONDS`); der tatsächliche Abstand ist deshalb
  auf ein Vielfaches dieses Takts aufgerundet.
- **Auf Anforderung:** `POST /invoices/sevdesk-refresh` (Knopf „Abgleich aktualisieren“ in der
  Übersicht) ruft `sync_vouchers()` sofort auf und leitet auf die Übersicht zurück.
- Ohne `FEATURE_SEVDESK_EXPORT=true` und `SEVDESK_API_TOKEN` passiert nichts
  (`sync_vouchers` gibt dann `False` zurück).

### Ablauf von `sync_vouchers()`

1. `_voucher_lock` (`asyncio.Lock`) sperrt. Ein zweiter Aufruf **wartet**, bis der erste fertig
   ist, und läuft danach selbst. Er wird also nicht verworfen.
2. `SevdeskClient.list_vouchers()` blättert alle Belege vollständig in den Speicher (Details
   in [sevdesk-export.md](sevdesk-export.md#abruf-der-belege-list_vouchers)). Fehlt `objects` in einer
   Antwort, auch auf einer Folgeseite, oder ist es keine Liste, bricht der Abruf mit einem Fehler ab.
   Eine leere Liste ist dagegen ein gültiger Abruf mit 0 Belegen.
3. Nur bei vollständigem Abruf: `Repository.replace_vouchers()` ersetzt den Abzug in **einer**
   Transaktion (Upsert aller gelieferten Belege, Löschen aller nicht mehr gelieferten IDs).
   Ein Fehler vor diesem Schritt, auch mitten im Blättern, lässt den Abzug unverändert.
4. Erfolg: `set_sevdesk_sync_success()` setzt `last_success_at` und **löscht** `last_error` und
   `last_error_at`.
5. Fehler: `set_sevdesk_sync_error()` schreibt die Meldung (`Typ: Text`, höchstens 500 Zeichen)
   und den Zeitpunkt. `last_success_at` bleibt stehen. Die Ausnahme wird nicht nach außen
   geworfen.
6. Danach `recompute_matches()` und das SSE-Token `vouchers:sync` (`notify_vouchers()`).

### Anzeige des Abrufstands

- Solange `last_success_at` leer ist (noch nie erfolgreich abgerufen), liefert
  `recompute_matches()` nichts, und jede Rechnung zeigt **„Abgleich nicht verfügbar“**. Ein
  leerer Abzug würde sonst „kein Treffer“ behaupten.
- Nach einem Fehler bei einem früheren Erfolg bleiben die Treffer aus dem letzten Stand sichtbar.
  Die Übersicht zeigt zusätzlich eine Fehlerbox mit Zeitpunkt, dem Stand des letzten Erfolgs und
  dem Grund (`partials/invoice_overview_status.html`).
- Die Statuszeile nennt „Abgleich: Stand <Zeitpunkt>“ bzw. „Abgleich: noch nicht abgerufen“.

### Aktualisierung nach einem Export

Ein erfolgreicher Export übernimmt den neuen Beleg sofort in den Abzug
(`repo.upsert_voucher`, siehe [sync-und-aktionen.md](sync-und-aktionen.md)). Dort steht
`sum_gross` auf dem gesendeten Betrag oder auf `None`, wenn keine Position mitging. Mit dem
nächsten Abruf übernimmt der Abzug den Wert aus SevDesk. Scheitert die Übernahme, ist der
Export trotzdem gültig; der nächste Abruf holt den Beleg nach.

## Matching

Die Berechnung liegt in `compute_matches(invoices, vouchers, existing_matches, *, window_days,
min_score)` (`app/sevdesk_matching.py`). Sie ist eine reine Funktion. `recompute_matches()`
ruft sie mit allen Rechnungen (`_ALL_INVOICES`), dem Abzug und den vorhandenen Treffern auf.
Danach ersetzt `Repository.replace_auto_matches()` nur die automatischen Treffer (`id` und
`similar`). `confirmed` und `rejected` bleiben unverändert.

### Sichere Treffer (`id`)

- Quelle ist die Beleg-ID der Rechnung. Vorrang hat `paperless_invoices.sevdesk_voucher_id`
  (Lectors eigener Export), dann `paperless_voucher_ref` (gespiegeltes Paperless-Feld
  „SevDesk-Beleg“, Custom-Field-Name über `CF_SEVDESK_ID`).
- Der Score ist fest `1.0`.
- Ob der Beleg im Abzug steht, entscheidet der Anzeigezustand, nicht der Treffer selbst (siehe
  unten: `in_sevdesk` bzw. `missing_in_sevdesk`).
- Die Beleg-ID eines `id`-Treffers gilt als **vergeben**. Der Beleg erscheint deshalb bei keiner
  anderen Rechnung als ähnlicher Treffer.

### Ähnliche Treffer (`similar`)

Ein Beleg kommt als Kandidat für eine Rechnung in Frage, wenn **alle** Bedingungen gelten:

| Bedingung | Regel im Code |
|---|---|
| Rechnung ohne `id`-Treffer und ohne `confirmed` | sonst keine ähnlichen Treffer |
| Rechnung hat einen Betrag | `amount` ist nicht `None`. Ausnahme: Rechnung im Status `uncertain` für Belege ohne Summe (siehe Sonderfall unten) |
| Rechnung hat ein Datum | `document_date` (Tagesteil) ist gesetzt |
| Beleg ist nicht vergeben | weder `id`-Treffer noch `confirmed` bei einer anderen Rechnung |
| Beleg hat ein Datum | `voucher_date` ist parsebar |
| Beleg hat eine Summe | `sum_gross` ist gesetzt und der Betrag der Summe (Absolutwert) ist mindestens 0,005; Summe 0 zählt als „ohne Summe“. Belege ohne Summe sind nur im Sonderfall `uncertain` Kandidaten |
| Betrag stimmt auf den Cent | nur bei Belegen mit Summe: Differenz zwischen Belegsumme und Rechnungsbetrag ist kleiner als 0,005 (eine 1-Cent-Abweichung schließt aus) |
| Gleiche Währung | nur bei Belegen mit Summe: Vergleich ohne Groß-/Kleinschreibung; fehlende Währung zählt als leer |
| Datum im Fenster | Abstand zwischen Belegdatum und Rechnungsdatum in Tagen ist höchstens `SEVDESK_MATCH_WINDOW_DAYS` (Grenze inklusive) |
| Paar nicht verworfen | `rejected` für genau dieses Paar (Rechnung, Beleg) schließt nur dieses Paar aus |
| Score erreicht Mindestwert | `score >= SEVDESK_MATCH_MIN_SCORE` |

#### Sonderfall: Rechnungen im Status `uncertain`

Ein Export mit unklarem Ausgang kann den Beleg ohne Betrag angelegt haben. Damit der Abgleich ihn
trotzdem findet, gilt für Rechnungen im Status `uncertain`:

- **Belege ohne Summe** sind Kandidaten. Betrag und Währung spielen dabei keine Rolle.
- Der Score wird wie sonst berechnet. Die Namensähnlichkeit ist hier das Maximum aus
  Lieferantenname und Ähnlichkeit von Rechnungstitel und Belegbeschreibung.
- **Belege mit Summe** werden wie bei jeder anderen Rechnung geprüft. Der Betrag muss also stimmen.
- Alle übrigen Bedingungen (Datum, Fenster, Verwerfen, Mindest-Score) gelten unverändert.

Für alle anderen Status bleiben summenlose Belege ausgeschlossen.

**Score:**

```
score = round(0.6 · (1 − Δtage / Fenster) + 0.4 · Namensähnlichkeit, 3)
```

- `Δtage` ist die absolute Differenz der Tage zwischen Belegdatum und Rechnungsdatum.
- `Namensähnlichkeit` ist das Maximum aus Token-Überdeckung und `difflib.SequenceMatcher`-Ratio
  auf den normalisierten Namen. Verglichen wird der Lieferant des Belegs (`supplier_name`) mit
  `creditor_name` **und** mit `correspondent` der Rechnung; der bessere Wert zählt. Fehlt auf
  einer Seite ein Name, ist der Wert `0`.
- Token-Überdeckung: Anzahl gemeinsamer Token geteilt durch die Anzahl Token des **kürzeren**
  Namens.

**Normalisierung** (`normalize_name`): Kleinschreibung; `&`, Satzzeichen und `_` werden zu
Leerzeichen; Rechtsformen werden als Token entfernt. Die Liste im Code lautet: `gmbh`, `ag`,
`ug`, `kg`, `se`, `sarl`, `sàrl`, `sa`, `ltd`, `limited`, `inc`, `llc`, `bv`, `co`.

**Gewichte:** Datum 0,6, Name 0,4. Der Betrag ist **kein** Gewicht, sondern eine harte
Bedingung. Der Score ordnet nur, er entscheidet nicht. Die Entscheidung trifft der Nutzer.

**Folgerung aus der Formel** (abgeleitet, nicht gemessen): Mit den Standardwerten (Fenster 14,
Schwelle 0,4) reicht bei **fehlender** Namensähnlichkeit ein Datumsabstand von höchstens 4 Tagen
(0,6 · (1 − 4/14) ≈ 0,43). Bei 5 Tagen liegt der Score unter 0,4 (≈ 0,39). Ob die Gewichte im
echten Bestand gut trennen, ist offen. Das Design nennt dies ausdrücklich als offene Frage;
Abnahme auf dem NAS steht aus (Task 9.1).

**Beispiel aus der Spec** (112,00 EUR, Rechnung vom 03.10., Beleg vom 04.10. mit anderem
Lieferantennamen): Der Datumsanteil allein ergibt ≈ 0,557. Der Beleg erscheint also als
mögliche Dublette, auch wenn der Name kaum übereinstimmt.

## Entscheidungen des Nutzers

Auf der Detailseite stehen die Kandidaten einer Rechnung mit Score und zwei Knöpfen:

- **„Derselbe Beleg“** → `decision=confirm`
- **„Anderer Beleg“** → `decision=reject`

Route: `POST /invoices/{invoice_id}/matches/{voucher_id}` (Formfeld `decision`). Andere Werte
antworten mit HTTP 400 („Unbekannte Entscheidung“). Danach leitet die Route auf die
Detailseite zurück.

Die Route prüft vorher:

- Unbekannte Rechnung → HTTP 404.
- Das Paar hat keinen **offenen** ähnlichen Treffer → HTTP 404. Eine Entscheidung ist nur über
  einen offenen Kandidaten möglich.
- Dieselbe Entscheidung steht bereits (Doppelklick) → Weiterleitung ohne Wirkung.

Ein entschiedenes Paar lässt sich über die Oberfläche nicht umentscheiden. Die Gegenentscheidung
antwortet dann mit 404, weil kein offener Treffer mehr besteht.

Bei „Derselbe Beleg“ auf eine Rechnung im Status `uncertain` setzt die Route zusätzlich den Status
`exported` mit der Beleg-ID und schreibt das Ereignis `sevdesk_exported` („als unklaren Export
bestätigt“). Danach läuft `recompute_matches()`. Der Rückschrieb an Paperless fehlt zu diesem
Zeitpunkt noch (`written_back_at` leer). Ihn holt der nächste Sync nach (siehe
[sync-und-aktionen.md](sync-und-aktionen.md)).

Ablauf in `Repository.decide_match(invoice_id, voucher_id, confirmed)`:

- Die Zeile wird auf `confirmed` bzw. `rejected` gesetzt (Upsert). Der Score bleibt erhalten.
- Ein `id`-Treffer ist **nicht entscheidbar**. Die Methode gibt dann `False` zurück und ändert
  nichts.
- Bei Erfolg: Ereignis `match_confirmed` bzw. `match_rejected` mit „Beleg <id>“,
  `recompute_matches()` (ohne Abruf bei SevDesk) und `notify_vouchers()`.

Wirkung der Entscheidung:

- **Bestätigt:** Die Rechnung gilt als in SevDesk vorhanden (`in_sevdesk`). Der Export wird nicht
  mehr angeboten (harte Sperre). Die Rechnung zählt außerdem als IT-Consulting-Quelle für die
  Korrespondenten-Historie (siehe [kontext-einstufung.md](kontext-einstufung.md)).
- **Verworfen:** Das Paar (Rechnung, Beleg) erscheint nie wieder als mögliche Dublette. Andere
  Rechnungen sind davon nicht betroffen.
- **Dauerhaft:** `replace_auto_matches` löscht nur `id` und `similar`. Ein automatischer Treffer
  für ein Paar mit Entscheidung wird übersprungen (`INSERT OR IGNORE`). Die Entscheidung gewinnt.
  Ausnahme: Ein `id`-Treffer löscht ein früheres `rejected` für dasselbe Paar. Die Beleg-ID ist sicher,
  eine frühere „anderer Beleg“-Entscheidung über ein bloß ähnliches Paar darf sie nicht unterdrücken.

Die Prüfung „offener Kandidat“ liegt in der Route (siehe oben). `Repository.decide_match` prüft das
selbst nicht. Die Methode legt eine Zeile auch ohne Kandidaten an.

## Anzeigezustand (`match_status_for`)

Jede Zeile der Übersicht bekommt genau einen Zustand. Die Auswertung folgt dieser Reihenfolge:

| Zustand (`MatchState`) | Anzeige | Bedingung |
|---|---|---|
| `unavailable` | „Abgleich nicht verfügbar“ | Kein erfolgreicher Abruf (`last_success_at` leer) |
| `in_sevdesk` | „In SevDesk“ | Bestätigter Treffer (`confirmed`); oder `id`-Treffer bzw. Beleg-ID der Rechnung, deren Beleg im Abzug steht |
| `missing_in_sevdesk` | „Beleg in SevDesk nicht gefunden“ | Beleg-ID vermerkt, der Beleg fehlt im Abzug |
| `possible_duplicate` | „Mögliche Dublette“ | Offener `similar`-Treffer; angezeigt wird der beste Score |
| `no_amount` | „Ohne Betrag nicht prüfbar“ | Kein Treffer, und der Betrag der Rechnung fehlt |
| `no_match` | „Kein Treffer“ | Sonst |

Bei `in_sevdesk` und `missing_in_sevdesk` nennt die Zeile die Beleg-ID. Bei `in_sevdesk` aus
einer Bestätigung wird nicht geprüft, ob der Beleg noch im Abzug steht.

Die Formulierung „Kein Treffer“ ist eine Aussage über den Abzug, keine über SevDesk insgesamt.
Der Abgleich erkennt nur exakte Beträge in derselben Währung. Teilzahlungen und Fremdwährungen
werden nicht erkannt.

## Vorbereitung: Belege ohne Rechnung

`Repository.vouchers_without_invoice()` liefert alle Belege des Abzugs ohne `id`-, `similar`-
oder `confirmed`-Treffer. `rejected` zählt dabei **nicht** als Treffer. Die Methode wird von
keiner Route und keiner Oberfläche genutzt. Sie ist nur die Abfrage für den späteren Abgleich B.

## Ereignisse und SSE

- `recompute_matches()` schreibt das Ereignis `vouchers_synced` in `invoice_events`, aber nur für
  Rechnungen, deren automatische Treffer sich geändert haben.
- Das SSE-Token `vouchers:sync` (`notify_vouchers()`) aktualisiert die Listenseite und die
  Statuszeile (`#overview-status`). Die Detailseite reagiert nur auf Tokens ihrer eigenen
  Rechnung (`inv:<id>`), siehe `app/static/app.js`.

## Grenzen

- **Entwürfe ohne Position haben die Summe 0.** SevDesk zeigt solche Belege mit `sumGross` `"0"`
  (Befund 1.1(a)). Sie sind nur für Rechnungen im Status `uncertain` ähnliche Kandidaten (siehe
  Sonderfall oben), sonst nie. Das betrifft alle Lector-Exporte ohne Betrag oder ohne
  `SEVDESK_ACCOUNT_DATEV_ID` (siehe [sevdesk-export.md](sevdesk-export.md)).
- **Kein Abgleich über den Dateiinhalt oder einen Hash.** SevDesk liefert die Datei nicht ohne
  Weiteres (Design, Nicht-Ziel).
- **Ein fehlender Treffer heißt nicht „sicher nicht vorhanden“.** Die Oberfläche formuliert das
  entsprechend (Design, Risiko „Betrag in Fremdwährung oder Teilzahlungen“).
- **Vollabruf:** Der Abruf liest jedes Mal den gesamten Bestand. Eine Begrenzung auf einen
  Zeitraum ist nicht umgesetzt (Design, Risiko „Vollabruf wird bei vielen Belegen langsam“).

## Konfiguration

| ENV | Default | Wirkung |
|---|---|---|
| `SEVDESK_MATCH_WINDOW_DAYS` | `14` | Datumsfenster in Tagen (inklusive) |
| `SEVDESK_MATCH_MIN_SCORE` | `0.4` | Mindest-Score für ähnliche Treffer |
| `SEVDESK_VOUCHER_SYNC_MINUTES` | `60` | Abstand zwischen zwei Abrufen |

Details und Validierung: [konfiguration.md](../konfiguration.md).

## Tests

Die Matching-Logik liegt in `tests/test_sevdesk_matching.py`, der Belegabruf in
`tests/test_voucher_sync.py`. Welche Fälle diese Tests genau abdecken, hat diese Doku nicht
geprüft.
