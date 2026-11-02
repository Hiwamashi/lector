# Design

## Context

Siehe proposal.md – Why. Ablauf heute (`app/paperless_sync.py`):

```
sync_once (alle 5 min, async, im einzigen Event-Loop)
  list_documents(doctype)            async, ~8 Seiten
  for doc in ~800 Rechnungen:        kein await dazwischen (corr_map im Speicher)
    get_invoice_by_paperless         SELECT
    upsert_invoice                   INSERT .. ON CONFLICT UPDATE + COMMIT + SELECT + SSE "inv:<id>"
    ggf. add_invoice_event           INSERT + COMMIT
    ggf. _extract_and_store          nur neue Rechnungen bzw. Giro-Status NONE (Netz)
  _sync_sevdesk_tag                  gleiches Muster für Rechnungen mit SevDesk-Tag
  recompute_matches                  synchron
```

`upsert_invoice` setzt `last_synced_at` bei jedem Aufruf neu; deshalb ändert sich jede Zeile,
und jeder Aufruf committet einzeln. SQLite läuft im WAL-Modus mit Standard-`synchronous`; jeder
Commit schreibt auf den Datenträger des NAS. Beobachtet: nach dem Laden der letzten Seite
~41 s ohne Logzeile und ohne Netzanfrage, zweimal reproduziert; die gleichzeitig laufende
Scan-Verknüpfung bricht mit leerer Meldung ab (Zeitüberschreitung des httpx-Clients, 30 s).
Die Zeit je Commit auf dem NAS ist nicht direkt gemessen; die Zeitmessung (D5) belegt den Fix.

Der Repository-Zugriff ist durch ein `threading.Lock` geschützt (Pipeline-Thread und
Event-Loop teilen die Verbindung).

## Goals / Non-Goals

**Goals:**
- Ein Lauf ohne Änderungen schreibt nichts und sendet keine Live-Signale.
- Ein Lauf mit vielen Änderungen (Erstbefüllung) committet einmal statt je Rechnung.
- Laufzeit je Schritt sichtbar im Log.

**Non-Goals:**
- Sync oder Datenbankzugriffe in einen eigenen Thread verlagern.
- `recompute_matches`, Belegabruf und Rückschriebe umbauen (nur messen).
- Den wiederholten Zahldaten-Versuch für Rechnungen mit Giro-Status NONE ändern.

## Decisions

### D1: Vergleich vor dem Schreiben im Repository

`upsert_invoice` liest die vorhandene Zeile und schreibt nur, wenn die Rechnung neu ist oder
sich eine übergebene Angabe unterscheidet. Verglichen wird in der gespeicherten Form (Datum wie
beim Schreiben formatiert, leerer Text = `None`); nicht übergebene Spiegelfelder (`_Unset`)
zählen nicht. Unverändert → kein Statement, kein Commit, kein `inv:`-Token.

Alternative: Vergleich in `paperless_sync.py`. Verworfen, weil dann jeder Aufrufer (auch Tests
und künftige) die Regel kennen müsste und die Normalisierung doppelt läge.

### D2: Gesammeltes Schreiben ohne Lock über `await`

Neue Repository-Methode `upsert_invoices(rows)`: nimmt die Angaben aller Rechnungen eines
Schritts, vergleicht wie D1, schreibt alle Änderungen unter einem Lock in **einer** Transaktion
mit einem Commit und sendet danach die Tokens nur für geänderte Rechnungen. Rückgabe je
`paperless_id`: Rechnungs-ID und Ergebnis (`new` | `changed` | `unchanged`) samt vorherigem
Stand, damit der Sync daraus sein `SYNCED`-Ereignis und die Zahldaten-Auslese ableitet.

`_sync_invoices` und `_sync_sevdesk_tag` werden zweiphasig: (1) Angaben aller Dokumente
sammeln (Korrespondentenname per `await`, ohne DB-Schreiben), (2) `upsert_invoices` einmal,
(3) Folgeschritte je Rechnung wie bisher (Ereignisse, `_extract_and_store`, Vormerken/Export).

Alternative: ein Transaktions-Kontext (`with repo.batch():`) um die bestehende Schleife.
Verworfen: Die Schleife enthält `await`s (`_extract_and_store`, Export); ein über `await`
gehaltenes `threading.Lock` blockiert den Event-Loop, sobald eine andere Coroutine das
Repository nutzt (Verklemmung). Ohne Lock wiederum könnte der Pipeline-Thread mitten in die
offene Transaktion committen.

Doppelte Dokumente (verschobene Seiten beim Paginieren) entfernt der Sync vor dem Sammeln;
`upsert_invoices` wertet je `paperless_id` nur das erste Vorkommen, damit ein zweites
„unverändert“ kein „neu“ überschreibt.

`upsert_invoice` (Einzelfall) bleibt für bestehende Aufrufer und Tests erhalten und nutzt
dieselbe Vergleichslogik.

### D3: „Zuletzt geändert“ ohne Schemaänderung

Die Spalte `last_synced_at` bleibt und wird nur noch bei `new`/`changed` gesetzt; ihre
Bedeutung ist damit „zuletzt geändert“. Beschriftung in `invoice_sections.html` wird
„Zuletzt geändert“. Das Modellfeld behält den Namen, ein Kommentar und die Doku nennen die
Bedeutung.

Alternative: Spalte umbenennen. Verworfen: `_MIGRATIONS` kennt nur Spalten-Zugänge; eine
Umbenennung bringt Migrationsrisiko ohne Nutzen für den Nutzer. Bestehende Werte bleiben
(Zeitpunkt des letzten Laufs vor dem Update) und werden ab der nächsten Änderung korrekt.

### D4: Ereignisse wie bisher

Das `SYNCED`-Ereignis entsteht weiter nur bei Neuanlage oder geändertem Titel/Korrespondent;
die Entscheidung stützt sich auf den von `upsert_invoices` gelieferten vorherigen Stand statt
auf einen eigenen `get_invoice_by_paperless` je Rechnung.

### D5: Zeitmessung

`sync_once` misst mit `time.monotonic()` die Schritte Rechnungen, SevDesk-Tag, Rückschriebe und
`recompute_matches` und loggt am Ende eine INFO-Zeile: geprüft, neu, geändert, Dauer je
Schritt. Keine Titel oder Namen im Log.

### D6: Fehlertyp im Log der Scan-Verknüpfung

`PaperlessLinker.run_once` loggt beim Abbruch `type(error).__name__` und die Meldung
(`ReadTimeout: ` statt leer).

## Risks / Trade-offs

- [Rest-Blockade durch Lesezugriffe je Rechnung im Tag-Schritt (`_blockers_for`, Treffer,
  Belege)] → nur für Rechnungen mit SevDesk-Status NONE/queued, kein Commit; die Zeitmessung
  zeigt es. Bleibt ein Schritt über 2 s, folgt ein eigener Change (Thread).
- [`recompute_matches` ist rechenintensiv] → gemessen (D5), nicht geändert.
- [Vergleich verfehlt eine Formatabweichung, z. B. Datum mit Zeitzone] → jede Rechnung würde
  weiter je Lauf geschrieben, aber gesammelt (D2) in einem Commit; Test mit echtem
  Paperless-Datumsformat.
- [„Zuletzt geändert“ zeigt nach dem Update zunächst den alten Lauf-Zeitpunkt] → akzeptiert.

## Migration Plan

Kein Schema-Update. Rollout wie üblich (Merge → Image → Komodo). Nachweis im Betrieb:
`/healthz`-Antwortzeiten über zwei Sync-Takte messen und die neue Logzeile prüfen.
Rückweg: Revert des Commits; Daten bleiben kompatibel.
