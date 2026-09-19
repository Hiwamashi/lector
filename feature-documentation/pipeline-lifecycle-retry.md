# Pipeline, Datei-Lifecycle & Auto-Retry

**Module:** `app/pipeline.py` (Orchestrierung), `app/fileops.py` (Dateioperationen)

## `run_pipeline(document_id, repo, settings, adapter)`

Läuft synchron im seriellen Thread-Pool des Workers. Ablauf:

1. Status → `processing`; `detect()`; Event `detected`; `doc_type` speichern.
2. **E-Rechnung:** `copy_into(consume)` (unverändert), Original `move_into(processed)`,
   Status `skipped_erechnung`.
3. **OCR-Weg:** `extract_pages` → `total_pages`/`ocr_engine` setzen → `preprocess_page` je Seite
   → `adapter.process(progress)` (Fortschritt + Event `ocr_chunk` je Block) →
   `build_sandwich_pdf` (Temp) → `move_into(consume, uid/gid)` → Original `move_into(processed)`
   → Status `done`.

Events entlang des Wegs: `preprocessing`, `ocr_chunk`, `built_pdf`, `moved_to_consume`, `done`.

## Fehler & Auto-Retry (`_handle_failure`)

- `attempt_count` wird inkrementiert.
- Solange `attempt_count < RETRY_MAX`: `schedule_retry(RETRY_DELAY_MINUTES)` setzt
  `next_retry_at` und Status zurück auf `pending`; Event `retry_scheduled`.
- Sonst: Original `move_into(error)`, Status `failed` mit `error_message`, Event `failed`.
- Mit Defaults `RETRY_MAX=3` ⇒ Versuche 1+2 planen Retry, Versuch 3 schlägt endgültig fehl.
- **Kein** manueller Retry-Button (PRD §3.1).

## Auflösung beim Start (`resolve_stale_processing`, `app/recovery.py`)

**Problemstellung:** Ein Prozessabbruch mitten in der Verarbeitung hinterlässt Vorgänge mit
`status=processing`. Die Verarbeitung läuft streng seriell in genau einem Prozess — ein solcher
Vorgang gehört beim Neustart zu keinem lebenden Bearbeiter mehr. Wenn der Dienst neugestartet
wird, muss jeder dieser Vorgänge aufgelöst werden, bevor neue Arbeit angenommen wird
(siehe `lifespan`, `app/main.py:166`).

**Auflösungsprinzip:** Die Entscheidung richtet sich nach zwei Tatsachen, die bereits in der
Datenbank stehen:
- **Wo das Original liegt:** im Eingangsordner (`watch_dir`) oder bereits im
  Verarbeitet-Ordner (`processed_dir`)
- **Ob ein Ablageort vermerkt ist:** `document.output_path` ist gesetzt oder `None`

Der Ausgabeordner (`consume_dir`) taugt **nicht** als Zeuge: Paperless überwacht ihn und
entfernt jede eingelesene Datei. Ein Fehlen beweist also nicht, dass die Ablage nie stattfand
— es ist der Normalfall nach erfolgreicher Übergabe.

### Entscheidungstabelle (Decision D1)

| Ort des Originals | Ablageort vermerkt | Auflösung |
|---|---|---|
| `processed_dir` | egal | **Abgeschlossen:** Ablage lag vor dem Verschieben, ist also passiert |
| `watch_dir` | ja | **Abgeschlossen:** Ablage war erfolgt, Original jetzt nachziehen |
| `watch_dir` | nein | siehe Grenzfall D2 |
| nirgends auffindbar | egal | **Gescheitert:** Erklärende Meldung, Fehlerordner |

Abgeschlossene Vorgänge durchlaufen die gleiche Finalisierung (`_finish`, `app/recovery.py:213`)
wie im Normalablauf: Original nachziehen (falls noch im `watch_dir`), dokumenttypgerechten
Endzustand setzen, Verlaufseintrag schreiben.

### Grenzfall (Decision D2): Ungeklärter Fortschritt

Bleibt ein Vorgang mit Original im Eingangsordner und ohne vermerkten Ablageort, ist unklar,
ob er vor der Ablage starb (Neuversuch ist richtig) oder exakt zwischen dem Verschieben der
Ergebnisdatei und dem Datenbank-Vermerk (Neuversuch wäre eine Doppelablage).

Die Auflösung führt eine Stichprobe im Ausgabeordner durch: Liegt dort eine Datei mit dem
**erwarteten Namen**, die **nach dem Beginn dieses Vorgangs** (`document.started_at`) verändert
wurde? Wenn ja, wird der Vorgang als unklar markiert und **als gescheitert** aufgelöst
(`DocStatus.FAILED`). Andernfalls wird er neu eingereiht (`DocStatus.PENDING`).

**Warum im Zweifel gescheitert statt Neuversuch?** Die Fehlerkosten sind asymmetrisch:
- Ein zu Unrecht als gescheitert markierter Vorgang ist **sichtbar und reversibel:** ein Blick
  in den Fehlerordner, erneute manuelle Ablage.
- Eine verursachte Doppelablage erzeugt **zwei Dokumente in Paperless** und ist erst dort
  aufgefallen — von Hand aufzuräumen und schwerer zu erkennen.

Bei Unklarheit gewinnt die sichtbare Variante.

### Erwarteter Ergebnis-Name je Dokumenttyp

Der Name, nach dem in der Stichprobe (D2) gesucht wird, **hängt vom erkannten Dokumenttyp ab**:

- **E-Rechnung** (`DocType.ERECHNUNG_XML`, `DocType.ERECHNUNG_PDF`): Der Weg
  `_handle_erechnung` (`app/pipeline.py`) legt per `copy_into()` unverändert ab
  (`unique_target` verwendet den **Originalnamen**, z.B. `invoice.xml`).
- **OCR-Weg** (alle anderen Typen): Erzeugt einen Sandwich-PDF unter dem Stammnamen
  plus `.pdf`-Endung (z.B. `scan_2026_09_20.pdf`).

Bei Namenskollisionen hängt `unique_target` (`app/fileops.py`) in beiden Fällen
`_1`, `_2`, … vor die Endung an.

Ruling R2 (`app/recovery.py:188`): Beim Zeitvergleich wird `document.started_at` **explizit**
als UTC in einen Epoch-Wert umgerechnet — nie über eine implizite (System-)Zeitzone. Dies
garantiert, dass die Vergleichbarkeit mit `Path.stat().st_mtime` unabhängig von der TZ-Einstellung
des Containers ist.

## fileops

- `file_hash` (SHA-256, Dedup).
- `unique_target` (kollisionsfreier Zielname, hängt `_1`, `_2`, … an).
- `move_into`/`copy_into` mit optionalem `chown` auf `PUID/PGID` (geteilter consume-Ordner mit
  Paperless). chown-Fehler ohne Root werden bewusst ignoriert.
