# Sync-Loop & UI-Aktionen

**Module:** `app/paperless_sync.py` (Orchestrierung), `app/sevdesk_export_checks.py`
(Prüfungen vor dem Export, `ExportOutcome`), `app/worker.py` (`_paperless_loop`),
`app/main.py` (Routen), Templates `invoices.html` / `invoice_detail.html` + Partials.
Abgleich und Einstufung: [sevdesk-abgleich.md](sevdesk-abgleich.md),
[kontext-einstufung.md](kontext-einstufung.md).

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
   Zusätzlich werden das Empfänger-Feld (`recipient_label`) und das Feld „SevDesk-Beleg“
   (`paperless_voucher_ref`) gespiegelt (`_mirrored_fields`). Fehlt ein Feld in Paperless,
   bleibt die lokale Spalte unverändert.
2. `_sync_sevdesk_tag` — Dokumente mit `SEVDESK_TAG` listen und über den Tag-Weg prüfen
   (siehe unten).
3. `_retry_write_backs` — fehlende Rückschreibe nach Exporten nachholen (siehe unten).
4. `recompute_matches()` — Treffer ohne SevDesk-Aufruf auf Basis des lokalen Abzugs neu
   berechnen ([sevdesk-abgleich.md](sevdesk-abgleich.md)).

### Korrespondenten-Auflösung: eine Karte je Lauf, nicht je Dokument

`_correspondent_name(client, doc, corr_map=None)` löst den Korrespondentennamen eines
Dokuments auf. `sync_once()` holt dafür **zu Beginn jedes Laufs** einmal die vollständige
Karte über `client.correspondent_map()` (eine paginierte Abfrage von `/api/correspondents/`)
und reicht sie durch `_sync_invoices` → `_extract_and_store` → `_extract_payment` sowie
`_sync_sevdesk_tag`. Aus vormals einem HTTP-Aufruf **je Dokument** (bei geteilten
Korrespondenten mehrere hundert Anfragen je Lauf, siehe Produktivlog) wird so **eine**
Anfrage je Lauf.

Zwei bewusste Entscheidungen dabei:

- **Nicht prozessweit gecacht.** Es gibt bereits `_corr_map_cached` (Instanzvariable
  `_corr_map`, für die Empfänger-Zuordnung/`list_recipient_documents`) — die bleibt für die
  gesamte Prozesslaufzeit bestehen. Für den Sync-Lauf ist das **nicht** verwendet: Die Karte
  aus `sync_once()` ist eine lokale Variable, die mit dem Lauf endet. Ein in Paperless
  umbenannter Korrespondent muss im **nächsten** Lauf ankommen, nicht erst nach einem
  Prozess-Neustart — bei einem prozessweiten Cache wäre er das nicht. Nicht "optimieren",
  indem man hier auf `_corr_map_cached` umstellt.
- **Rückfall auf den Einzelabruf.** Steht eine `correspondent_id` nicht in der Karte (z.B.
  weil der Korrespondent in Paperless erst NACH dem Bau der Karte angelegt wurde), holt
  `_correspondent_name` den Namen trotzdem per Einzelabruf (`get_correspondent_name`) — sonst
  würde der Name still als „kein Korrespondent" in der Rechnung landen.
- **Der Einzelvorschlagspfad bleibt einzeln.** `suggest_recipient(paperless_id)` (Vorschlag
  für genau EIN Dokument) ruft `_correspondent_name` ohne Karte auf — die vollständige Karte
  für ein einzelnes Dokument zu holen wäre teurer als der direkte Einzelabruf. Der
  KI-Batch-Lauf (`suggest_recipients_batch`) dagegen holt — analog zu `sync_once()` — seine
  eigene, unabhängige Karte einmal für den gesamten Batch (nur wenn tatsächlich Dokumente
  anstehen); Sync-Lauf und Batch-Lauf sind getrennte Läufe mit je eigener Karte.

### Tag-Weg (`_sync_sevdesk_tag`)

Der Paperless-Tag `SEVDESK_TAG` ist eine Abkürzung zur Übersicht. Er durchläuft dieselben
Prüfungen wie ein Export aus der Übersicht. Für jedes getaggte Dokument gilt:

- Bearbeitet wird **nur** ein Status `none`. Die Status `review` und `dismissed` sowie alle
  übrigen bleiben unverändert.
- Die Prüfung ist `_blockers_for(inv)`: `export_blockers` mit den aktuellen Treffern und dem
  lokalen Belegabzug (siehe „Prüfungen vor dem Export“).

| Ergebnis der Prüfung | Status | Ereignis | Export |
|---|---|---|---|
| harte Sperre (z. B. „bereits in SevDesk“), Status `none` | bleibt `none` | `sevdesk_review`: „nicht vorgemerkt: <Grund>“ | nein |
| harte Sperre, Status `queued` | bleibt `queued` | `sevdesk_review`: „nicht exportiert: <Grund>“ | nein |
| Rückfragegründe (z. B. mögliche Dublette, anderer Empfänger) | `review` mit `review_reason` | `sevdesk_review` mit den Gründen | nein, auch nicht bei Auto-Export |
| keine Gründe, aber kein Auto-Export oder noch kein erfolgreicher Belegabruf | `queued` (nur aus `none`) | `sevdesk_queued` | nein |
| keine Gründe, Auto-Export aktiv und erfolgreicher Belegabruf vorhanden | `queued`, dann `export_invoice` ohne Bestätigung | `sevdesk_queued`, bei Erfolg `sevdesk_exported` | ja |

- Eine `queued`-Rechnung wird nur bewertet, wenn `SEVDESK_AUTO_EXPORT=true` gilt. Ohne Auto-Export
  bleibt sie unberührt. Mit Auto-Export wird sie in **jedem** Sync-Lauf neu über `export_blockers`
  geprüft. Das gilt auch für Rechnungen, die vor dem ersten Belegabruf vorgemerkt wurden.
- Solange `sevdesk_sync_state.last_success_at` leer ist, also noch kein Belegabruf erfolgreich war,
  exportiert der Tag-Weg auch bei Auto-Export nicht. Ohne Abzug wäre die Dublettenprüfung leer.
- Das Ereignis für die harte Sperre entsteht nur beim ersten Erkennen bzw. wenn sich der Grund
  ändert (`_add_event_once`). So schreibt nicht jeder Lauf dasselbe Ereignis.
- Ein Prüffall `review` bleibt `review`, auch wenn die Gründe inzwischen entfallen. Die
  Entscheidung liegt dann beim Nutzer (Exportieren oder Verwerfen in der Detailansicht).
- Ein verworfener Prüffall (`dismissed`) wird nicht erneut vorgemerkt.
- Status `exported`, `exporting` und `uncertain` werden im Tag-Weg nicht angefasst.

### `_sync_invoices` — Rechnungen (Dokumentenliste)

Der Ablauf entspricht der Beschreibung unter `sync_once()`. Die Korrespondentenkarte und die
Feldauflösung kommen aus dem Lauf.

## Prüfungen vor dem Export

Die Prüfung ist `export_blockers(invoice, matches, voucher_ids_in_cache, *, context_label)` in
`app/sevdesk_export_checks.py`. Übersicht, Mehrfachexport und Tag-Weg verwenden **dieselbe**
Funktion. Sie liefert zwei Arten von Gründen:

- **Harte Sperre** (`hard`): Der Export ist gesperrt. Eine Bestätigung hebt sie nicht auf.
- **Rückfragegründe** (`reasons`): Der Export braucht eine ausdrückliche Bestätigung.

Die Reihenfolge der Prüfung ist fest. Der erste Treffer gewinnt:

| # | Bedingung | Art | Meldung (Auszug) |
|---|---|---|---|
| 1 | Status `exported` | hart | „bereits exportiert (Beleg <id>)“ |
| 2 | Status `exporting` | hart | „Export läuft bereits“ |
| 3 | Status `uncertain` | hart | „Ausgang des letzten Exports unklar — in SevDesk prüfen …“ |
| 4 | bestätigter Treffer (`confirmed`) | hart | „bereits in SevDesk (Beleg <id>)“ |
| 5 | Beleg-ID vermerkt (Treffer `id`, `sevdesk_voucher_id` oder `paperless_voucher_ref`) und der Beleg steht im Abzug | hart | „bereits in SevDesk (Beleg <id>)“ |
| 6 | Beleg-ID vermerkt, der Beleg fehlt im Abzug | hart | „Beleg <id> ist vermerkt, im SevDesk-Abzug aber nicht zu finden — die Rechnung wurde bereits exportiert“ |
| 7 | offene ähnliche Treffer (`similar`) | Rückfrage | „mögliche Dublette: Beleg <id> (Score 0,xx)“ |
| 8 | Empfänger gesetzt, der nicht dem Kontext-Label entspricht | Rückfrage | „anderer Empfänger: <Label> (nicht <Kontext>)“ |

Hinweise zur Prüfung:

- Die Sperre aus Punkt 6 geht über die Spec hinaus: Ein vermerkter, aber fehlender Beleg sperrt
  den Export. Begründung laut Code: Die Rechnung wurde schon einmal exportiert, und der Beleg
  kann nur gelöscht oder noch nicht abgerufen sein. Wer neu exportieren will, entfernt den
  Vermerk bewusst in Paperless.
- Der Status `dismissed` kommt in der Prüfung **nicht** vor. Ein verworfener Prüffall sperrt
  den manuellen Export also nicht (siehe „Bewusste Entscheidungen“).
- Ein Empfänger, der sich vom Kontext-Label nur in der Groß-/Kleinschreibung unterscheidet,
  löst **keine** Rückfrage aus. Der Vergleich ist hier ohne Berücksichtigung der Schreibweise
  (siehe [kontext-einstufung.md](kontext-einstufung.md)).

## Export (`export_invoice`)

Signatur: `export_invoice(invoice_id, confirmed=False) -> ExportOutcome`. Der Aufruf wirkt in
dieser Reihenfolge:

1. Rechnung laden. Unbekannt → `skipped`.
2. Harte Sperre → `blocked` mit der Meldung. **Am Status ändert sich nichts** (auch nicht bei
   `none`, `queued` oder `review`).
3. Rückfragegründe und nicht `confirmed` → `needs_confirmation` mit den Gründen. Nichts wird
   exportiert, der Status bleibt.
4. SevDesk-Export nicht aktiv (`sevdesk_enabled` falsch) → Status `failed` mit der Meldung
   „SevDesk-Export ist deaktiviert“. Dieser Zweig setzt den Status tatsächlich auf `failed`,
   also retrybar. Die Sperre (2) und die Rückfrage (3) werden vorher geprüft.
5. Atomarer Claim (`repo.claim_for_export`): Setzt den Status auf `exporting`, wenn er nicht
   `exported`, `exporting` oder `uncertain` ist. Verliert der Aufruf den Claim → `skipped` mit
   „bereits exportiert oder in Arbeit“. Schutz gegen Doppelbelege bei Doppelklick, gleichzeitigem
   Auto-Export und manuellem Klick. Ein Prüffall `review`, `failed` oder `dismissed` ist claim-bar.
6. Original aus Paperless laden und `uploadTempFile`. Fehler → `failed` (retrybar). Noch kein Beleg.
7. Betrag bestimmen: nur bei `giro_status` `ready` oder `edited` und mit konfiguriertem
   `SEVDESK_ACCOUNT_DATEV_ID` geht die Summe als Belegposition mit (siehe
   [sevdesk-export.md](sevdesk-export.md#belegposition-mit-betrag)).
8. `saveVoucher`. Fehlerklassifizierung siehe unten.
9. Erfolg: Status `exported` mit der Beleg-ID, Ereignis `sevdesk_exported`. Der Beleg wird in
   den lokalen Abzug übernommen und `recompute_matches()` läuft. Danach der Rückschrieb an
   Paperless (siehe unten). Bei einem Fehler im Rückschrieb bleibt `written_back_at` leer, und
   das Ereignis `write_back_failed` wird geschrieben. Der Export selbst gilt trotzdem als erfolgreich.

### Ergebnis (`ExportOutcome`)

| `status` (`ExportStatus`) | Bedeutung | Anzeige (Mehrfachexport) |
|---|---|---|
| `exported` | Beleg angelegt | „Exportiert“ |
| `blocked` | harte Sperre, nichts geändert | „Übersprungen“ |
| `needs_confirmation` | Rückfragegründe, ohne Bestätigung nichts getan | „Übersprungen“ |
| `failed` | eindeutig fehlgeschlagen, kein Beleg, erneut exportierbar | „Fehlgeschlagen“ |
| `uncertain` | Ausgang unklar, nicht automatisch erneut exportieren | „Unklar – prüfen“ |
| `skipped` | nichts getan (unbekannte Rechnung, Claim verloren, Mehrfachexport) | „Übersprungen“ |

`ExportOutcome` trägt `status`, `message`, `reasons` (Rückfragegründe) und `voucher_id`.

### Fehlerklassifizierung

Der Export ist in Schritte getrennt, um Doppel-Belege bei Wiederholung zu vermeiden:

- Download und `uploadTempFile` legen **keinen** Beleg an. Fehler sind eindeutig und
  **retrybar** (`failed`, wieder claim-bar).
- `saveVoucher` legt den Beleg an. Nur eine **4xx**-Antwort ist eine eindeutige
  Client-Ablehnung (kein Beleg) → `failed` (retrybar). **5xx**-Serverfehler sind **mehrdeutig**
  (der Server kann den Beleg erzeugt haben, bevor die Fehlerantwort kam), ebenso
  Transportfehler/Timeout und eine fehlende Beleg-ID in einer 200-Antwort → Status
  `uncertain`, **nicht** auto-retrybar. Der Nutzer muss in SevDesk prüfen, ob der Beleg
  existiert, bevor erneut exportiert wird.
- Bei einem harten Absturz **während** des Uploads bleibt der Status auf `exporting`. Beim
  nächsten Start bereinigt `repo.reset_stale_exports()` (Aufruf im Lifespan) solche
  verwaisten Claims auf `uncertain` — nicht auf `failed`, weil unklar ist, ob bereits ein
  Beleg angelegt wurde. So bleibt die Rechnung nicht dauerhaft in `exporting` blockiert,
  wird aber bewusst **nicht** automatisch erneut exportiert (manuelle Prüfung in SevDesk).

### Rückschrieb an Paperless (`_apply_export_write_back`)

Nach einem Export schreibt Lector an das Paperless-Dokument:

- Custom Field „SevDesk-Beleg“ (`CF_SEVDESK_ID`): die Beleg-ID.
- Custom Field „SevDesk-Export am“ (`CF_EXPORTED_AT`): das **aktuelle** Datum (UTC) im Format
  `YYYY-MM-DD`.
- Empfänger-Feld (`CF_RECIPIENT`): die Options-ID der Kontext-Option (`SEVDESK_CONTEXT_LABEL`,
  Vergleich über `same_label`). Beim Erstexport wird der Empfänger gesetzt, sofern die Option im
  Feld existiert. Der Nutzer hat den Export bestätigt. Beim Nachholen gilt die Einschränkung unten.
  Fehlt die Option im Feld, werden die übrigen Felder trotzdem geschrieben, und ein Ereignis
  `written_back` mit dem Hinweis „Empfänger nicht gesetzt …“ wird einmalig festgehalten.
- Lokal wird `recipient_label` nur **nach** dem erfolgreichen Schreiben in Paperless auf die
  Kontext-Option gesetzt.
- Tag `sevdesk-exportiert` (`TAG_SEVDESK_DONE`).
- Notiz „Nach SevDesk exportiert — Beleg <id>“, mit Link, falls vorhanden. Die Notiz wird nur
  geschrieben, wenn noch keine Notiz mit diesem Präfix existiert. Die Prüfung verlangt eine
  Wortgrenze, damit Beleg „12“ nicht durch eine Notiz zu Beleg „123“ als vorhanden gilt.

Bei Erfolg setzt Lector `written_back_at` und schreibt das Ereignis `written_back`.

Scheitert der Rückschrieb beim Erstexport, bleibt `written_back_at` leer. Status und Beleg-ID
bleiben erhalten. Der Fehler wird als Ereignis `write_back_failed` („Rückschrieb fehlgeschlagen“)
an der Rechnung festgehalten. Die Meldung ist gekürzt auf höchstens 200 Zeichen (`Typ: Text`).
Derselbe Text wird nicht erneut geschrieben (`_add_event_once`). Der nächste Sync holt den
Rückschrieb nach (siehe unten).

Der offene Rückschrieb ist außerdem sichtbar:

- **Listenzeile:** Kennzeichen „Rückschrieb offen“, solange der Status `exported` ist und
  `written_back_at` leer bleibt.
- **Detailseite:** Hinweis „Rückschrieb an Paperless offen — wird beim nächsten Sync nachgeholt.“
- **Live-Aktualisierung:** `data-rev` der Zeile enthält den Stand von `written_back_at`. Ändert er
  sich, leuchtet die Zeile auf.

### Nachholen der Rückschriebe (`_retry_write_backs`)

Läuft in jedem `sync_once()` nach `_sync_sevdesk_tag` (also nur mit aktivem Paperless-Sync). Er
nimmt alle Rechnungen mit Status `exported`, bei denen `written_back_at` leer und eine Beleg-ID
gesetzt ist, und ruft `_apply_export_write_back` mit `retry=True` auf. Bei Erfolg folgt
`written_back_at` und das Ereignis „Rückschrieb nachgeholt“. Eine Obergrenze für Versuche gibt es
nicht: Jeder Sync versucht die offenen Rückschriebe erneut.

Im Nachholpfad liest Lector das Dokument **live**, bevor es schreibt. Daraus ergibt sich:

- **Anderer Empfänger am Dokument:** Der Empfänger wird nicht überschrieben. Die übrigen Felder,
  der Tag und die Notiz werden trotzdem geschrieben. Ein einmaliger Hinweis „Empfänger nicht
  überschrieben: …“ steht im Verlauf (Ereignis `written_back`). Der Rückschrieb gilt als erledigt.
- **Leerer Empfänger oder Kontext-Option:** Der Empfänger wird auf die Kontext-Option gesetzt.
- **404 von Paperless** (Dokument gelöscht): Der Rückschrieb gilt als erledigt. `written_back_at`
  wird gesetzt und der Hinweis „Dokument in Paperless nicht mehr vorhanden — Rückschrieb entfällt“
  einmalig festgehalten. Ohne diese Behandlung würde jeder Lauf mit 404 scheitern.
- **Andere Fehler:** Ereignis `write_back_failed` (einmalig je Text). `written_back_at` bleibt
  leer, und der nächste Sync versucht es erneut.

Beim Erstexport gibt es keine 404-Sonderbehandlung. Jeder Fehler dort, auch ein 404, ergibt
`write_back_failed`. Den Fall klärt dann der Nachholpfad im nächsten Sync.

„SevDesk-Export am“ bekommt in beiden Pfaden das Datum des **Schreibens** (UTC). Beim Nachholen
ist das also das Nachholdatum, nicht das des Exports. Der Tag wird ergänzt, die Notiz nur, wenn
sie fehlt.

**Seiteneffekt bei bestehenden Rechnungen (verbleibend):** Alle Rechnungen mit Status `exported`
ohne `written_back_at` werden beim ersten Sync nach dem Deployment nachgeholt. Ist der Empfänger
leer, setzt das Nachholen ihn **ohne Rückfrage** auf die Kontext-Option. „SevDesk-Export am“ bekommt
das Nachholdatum. Ein bereits gesetzter anderer Empfänger bleibt dagegen erhalten.

TODO: Wie viele Bestandsrechnungen beim ersten Lauf betroffen sind, lässt sich aus dem Code nicht
ermitteln. Die Zahl ist auf dem NAS abzufragen (`written_back_at IS NULL` bei
`sevdesk_status = 'exported'`).

### Mehrfachexport (`export_invoices`)

`export_invoices(invoice_ids)` arbeitet die Liste **sequenziell** ab und ruft für jede Rechnung
`export_invoice(id, confirmed=False)` auf:

- Rechnungen mit harter Sperre oder Rückfragegrund werden **nicht** exportiert. Sie kommen als
  `skipped` mit ihren Gründen zurück. Eine Bestätigung ist im Mehrfachexport nicht möglich.
- `failed` und `uncertain` behalten ihren Status.
- Eine Ausnahme bei einer Rechnung wird abgefangen und als `failed` gemeldet.

Route: `POST /invoices/export-batch` (Formfeld `ids`, mehrfach). Die Antwort ist **keine**
Weiterleitung, sondern die Ergebnisseite `invoice_batch_result.html` mit der Zahl der Exporte und
einer Zeile je Rechnung (Ergebnis, Grund). Ohne Auswahl leitet die Route zurück zur Übersicht.
Ein erneutes Absenden ist harmlos, weil exportierte Rechnungen durch den Claim übersprungen werden.

## Dismiss (Prüffall verwerfen)

`dismiss_invoice(invoice_id)` setzt über `repo.dismiss()` den Status `dismissed` und leert den
Grund. Das Ereignis `sevdesk_dismissed` wird geschrieben. Bei `exported`, `exporting` oder
`uncertain` bleibt es wirkungslos (`False`). Route: `POST /invoices/{id}/dismiss`.

Die Detailseite zeigt den Knopf „Verwerfen“ nur bei Status `review`.

„Verwerfen“ heißt **nicht** „nicht exportieren“. Der Tag-Weg übergeht `dismissed` (keine erneute
Vormerkung). Der manuelle Export bleibt aber möglich: Der Knopf „Nach SevDesk exportieren“ und der
Mehrfachexport sperren `dismissed` nicht. Das ist bewusst so (siehe „Bewusste Entscheidungen“).

## Rückfrage vor dem Export

Die Übersicht und die Detailseite nutzen dieselbe Prüfung:

- Ein Export ohne Bestätigung und mit Rückfragegründen liefert `needs_confirmation`. Die Route
  `POST /invoices/{id}/export` (Formfeld `confirm`) leitet dann auf `/invoices/{id}?ask=1`.
- Die Detailseite zeigt den Block „Vor dem Export klären“ mit den **live** berechneten Gründen
  und dem Knopf „Trotzdem exportieren“ (`confirm=1`). Der Block verschwindet, sobald keine
  Gründe mehr bestehen.
- Der Prüffall-Kasten (Status `review`) hat ebenfalls „Trotzdem exportieren“. Dieser Knopf sendet
  **kein** `confirm`. Die Route leitet dann über `?ask=1` zur Rückfrage mit den heutigen Gründen.
- Der Knopf „Nach SevDesk exportieren“ ist bei harter Sperre oder ohne aktiven SevDesk-Export
  deaktiviert.

## Empfänger-Feld und Kontext-Option

Die Kontext-Option wird durch den Export gesetzt, nicht vorab. Die Einstufung und die
Empfänger-Zuordnung sind in [kontext-einstufung.md](kontext-einstufung.md) und
[empfaenger-zuordnung.md](empfaenger-zuordnung.md) beschrieben.

## UI-Aktionen (weitere)

- `save_giro_edits(...)` — manuell korrigierte Zahldaten speichern (`giro_status=edited`),
  optional Rückschrieb.
- `set_paid(id, paid)` — als überwiesen markieren; Rückschrieb (Custom Field `Überwiesen`,
  Tag `überwiesen`, Notiz).

## Routen (`app/main.py`)

| Route | Zweck |
|---|---|
| `GET /invoices` | Export-Übersicht mit Filtern (`q`, `sevdesk`, `ctx`, `open`, `dup`, `review`) und Sortierung (`sort`, `dir`) |
| `GET /fragment/invoices` | Tabellenkörper (SSE-Refresh; trägt Filter und Sortierung mit) |
| `GET /fragment/invoices/overview-status` | Statuszeile: Abrufstand, Fehlerbox, Hinweis „nicht einstufbar“ (SSE `vouchers:sync`) |
| `POST /invoices/sevdesk-refresh` | Belegabruf sofort, danach Weiterleitung (Formfeld `back`) |
| `POST /invoices/export-batch` | Mehrfachexport (Formfeld `ids`, mehrfach), Ergebnisseite |
| `GET /invoices/{id}` | Detailseite; `?ask=1` zeigt die Rückfrage nach einem Export-Versuch |
| `GET /fragment/invoices/{id}` | Detail-Body (SSE-Refresh) |
| `GET /invoices/{id}/preview` | PDF-Vorschau über Lector (Proxy) |
| `POST /invoices/{id}/giro` | Zahldaten speichern |
| `POST /invoices/{id}/export` | Nach SevDesk exportieren (Formfeld `confirm`) |
| `POST /invoices/{id}/dismiss` | Prüffall verwerfen |
| `POST /invoices/{id}/matches/{voucher_id}` | Ähnlichen Treffer bestätigen (`decision=confirm`) oder verwerfen (`decision=reject`). HTTP 404 bei unbekannter Rechnung und bei Paaren ohne offenen ähnlichen Treffer; dieselbe Entscheidung nochmals wirkt nicht |
| `POST /invoices/{id}/paid` | Überwiesen-Status umschalten |

Statische Pfade müssen vor den parametrisierten registriert sein. Sonst fängt
`/fragment/invoices/{invoice_id}` den Pfad `/fragment/invoices/overview-status` ab (Kommentar in
`app/main.py`).

Der Formularparameter `back` (Mehrfachexport, Belegabruf) führt zurück zur Übersicht. Er wird
gegen eine Whitelist geprüft: nur die Parameter `q`, `sevdesk`, `ctx`, `open`, `dup`, `review`,
`sort`, `dir`, nur relativ auf `/invoices`. Andernfalls geht es zu `/invoices`.

Live-Updates: `EventBus` verteilt Tokens `inv:<id>` (Rechnungen) und `vouchers:sync` (Belegabzug);
`app/static/app.js` aktualisiert die passende Liste, die Statuszeile bzw. die Detailansicht.

## Worker-Anbindung

`Worker.__init__` nimmt optional `paperless_sync`. Ist das Feature aktiv, startet `start()`
zusätzlich den Task `_paperless_loop`, der `sync_once()` im Intervall aufruft. Netzwerk-I/O
läuft direkt im asyncio-Loop (kein Thread-Pool nötig, anders als die CPU-lastige OCR-Pipeline).

Die Schleife ruft außerdem `sync_vouchers()` auf, sobald `sevdesk_enabled` gilt. Der erste Abruf
erfolgt beim Start, danach nach jeweils `SEVDESK_VOUCHER_SYNC_MINUTES`. Ist ein Abruf fällig, läuft
er **vor** dem jeweiligen `sync_once()`. Der Auto-Export im selben Durchlauf findet so bereits einen
aktuellen Abzug vor. Die Fälligkeit wird bei jedem Schleifendurchlauf geprüft (Details in
[sevdesk-abgleich.md](sevdesk-abgleich.md)).

## Bewusste Entscheidungen

- **Verworfener Prüffall bleibt manuell exportierbar.** `dismissed` ist in `export_blockers` keine
  Sperre. „Verwerfen“ wirkt nur auf den Tag-Weg (keine erneute Vormerkung). Diese Lage ist so
  belassen worden, sie weicht von der Spec ab (die „nicht exportiert“ verlangt).
- **Ungültige KI-Werte führen weiter zu erneuter Anfrage** im Batch-Lauf. Der Kostenhinweis aus
  [empfaenger-zuordnung.md](empfaenger-zuordnung.md) gilt unverändert.

## Offene Punkte

- **Nachholen des Rückschriebs.** Datum und ein leerer Empfänger werden ohne Rückfrage gesetzt. Die
  Zahl der betroffenen Bestandsrechnungen ist unbekannt (TODO oben).

Entschieden und in der Spec festgehalten: Ein vermerkter, aber im Abzug fehlender Beleg sperrt den
Export hart (die Rechnung wurde bereits einmal exportiert). Der Betrag geht nur mit konfigurierter
Konto-ID mit (`SEVDESK_ACCOUNT_DATEV_ID`, Design 9).
