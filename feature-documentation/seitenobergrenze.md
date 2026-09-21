# Seitenobergrenze, Wartezustand und Freigabe

**Module:** `app/pages.py` (`count_pages`), `app/pipeline.py` (`_block_oversized`,
`_handle_ocr`), `app/decisions.py`, `app/repository.py`
(`transition_from_blocked`), `app/main.py` (zwei POST-Routen),
`app/templates/partials/detail_body.html`.

## Wozu

Jede Seite kostet bei Document AI Geld. Vor dieser Funktion gab es keine Grenze: Ein
versehentlich als ein Dokument eingescannter Stapel oder eine irrtümlich nach `scan-in`
kopierte Datei erzeugte die Kosten vollständig und lautlos, bevor jemand davon erfuhr.

Jetzt wird die Seitenzahl vor dem ersten Engine-Aufruf gegen `MAX_PAGES_PER_DOCUMENT`
geprüft (Standard 100, `0` oder kleiner schaltet die Prüfung ab). Überschreitet ein
Dokument die Grenze, wird es **angehalten** statt verarbeitet — es entstehen keine Kosten.

## Ablauf

```
OCR-Weg → count_pages()  ← zählt OHNE zu rastern
            ├─ Seitenzahl ≤ Grenze, oder Grenze ≤ 0, oder Vorgang freigegeben
            │    → extract_pages() → normale Veredelung
            └─ Seitenzahl > Grenze
                 → status = blocked, Verlaufseintrag `blocked`
                   Original bleibt im Eingangsordner, keine Engine, kein Retry

blocked  ──[Freigeben]──→ pending (page_limit_approved = 1) → normale Verarbeitung
         └─[Verwerfen]──→ failed, Original nach ERROR_DIR
```

## Warum ohne Rasterung gezählt wird

`extract_pages` rendert jede PDF-Seite bei 200 DPI. Stünde die Prüfung erst danach, wäre
ein 800-Seiten-Scan vollständig in den Arbeitsspeicher gerendert, bevor er angehalten wird
— die Grenze hätte den Schaden nur von Geld auf Speicher verschoben. `count_pages` liest
deshalb nur den Seitenbaum (PDF, über dieselbe Bibliothek wie beim Rendern) bzw. die
Frame-Zahl (TIFF).

Dass beide Wege dieselbe Zahl liefern, ist durch Tests belegt
(`tests/test_pages.py`): Bei einer Abweichung würde der Dienst nach einer Zahl blockieren,
die die Extraktion später nicht bestätigt.

## Der Zustand `blocked`

Ein **Wartezustand**, kein Endzustand:

- Kein `finished_at`, kein eingeplanter Wiederholversuch, kein erhöhter Versuchszähler —
  die Blockade ist kein Fehlversuch.
- Das **Original bleibt im Eingangsordner**. Der Dublettenschutz
  (`find_by_hash_active`) hält jeden Zustand außer `failed` für aktiv, deshalb nimmt der
  Watcher die liegengebliebene Datei nicht erneut auf. Diese Eigenschaft ist als
  Ausschlussliste formuliert und damit verletzlich; `tests/test_web.py` sichert sie ab.
- Der Vorgang verlässt den Zustand **nur** durch eine ausdrückliche Entscheidung.

## Die beiden Entscheidungen

In der Detailansicht eines angehaltenen Vorgangs stehen Seitenzahl und geltende Grenze,
dazu zwei Schaltflächen:

| Entscheidung | Route | Wirkung |
|---|---|---|
| Freigeben | `POST /documents/{id}/release` | `page_limit_approved = 1`, zurück auf `pending` ohne Wiederholzeitpunkt; die Grenze gilt für diesen Vorgang nicht mehr — auch nach einem Neustart und über Wiederholversuche hinweg |
| Verwerfen | `POST /documents/{id}/discard` | Original nach `ERROR_DIR`, Vorgang auf `failed` mit erklärender Meldung |

Ohne das Verwerfen wäre `blocked` eine Sackgasse: Das Original liegt im Eingangsordner,
und der Vorgang stünde auf Dauer in der Übersicht.

**Warum `failed` und kein eigener Endzustand „verworfen"?** Weil `failed` die gewünschte
Semantik bereits trägt — Original bleibt im Fehlerordner erhalten, wird nicht automatisch
gelöscht, Vorgang ist abgeschlossen. Der Verlaufseintrag `discarded` sagt, wie es dazu kam.

### Beide Entscheidungen sind bedingt

`transition_from_blocked` prüft und schreibt in einem Schritt
(`UPDATE ... WHERE id = ? AND status = 'blocked'`) und meldet, ob eine Zeile betroffen war.
Ohne das würde ein Doppelklick auf „Freigeben", oder Freigeben in der einen und Verwerfen
in einer zweiten Ansicht, beide Zweige ausführen: Das Original wanderte in den
Fehlerordner, während der Vorgang schon in der Verarbeitungsreihe steht. Eine wirkungslose
Entscheidung beantworten die Routen mit `409`, ein unbekannter Vorgang mit `404` — nicht
mit einer stillen Weiterleitung.

### Scheitert das Verschieben, wird der Übergang zurückgenommen

Beim Verwerfen wird **zuerst** der Übergang beansprucht und **danach** die Datei bewegt —
umgekehrt als in `_handle_failure` und in der Recovery, wo zuerst bewegt wird. Das ist
nötig, weil der Anspruch gegen eine zeitgleiche Freigabe stehen muss.

Damit entsteht aber die Lage, vor der Ruling R10 warnt: ein Vorgang auf `failed`, dessen
Original noch im Eingangsordner liegt. `find_by_hash_active` schließt genau `failed` aus —
der Watcher legte die Datei beim nächsten Durchgang als **zweiten Vorgang** an. Deshalb
nimmt `discard_document` den Übergang zurück, wenn `move_into` scheitert (Rechte auf dem
Fehlerordner, volles Volume, hängender Mount): zurück auf `blocked`, `finished_at` geleert,
die Ursache in `error_message` und im Verlauf. Der Anwender kann erneut entscheiden, die
Route antwortet mit `500` und einer erklärenden Meldung statt mit einem Stacktrace.

### Beide Routen arbeiten außerhalb des Eventloops

Freigeben prüft die Existenz des Originals, Verwerfen verschiebt es. Auf dem NAS liegen
Eingangs- und Fehlerordner auf verschiedenen Volumes: `shutil.move` kopiert dann, statt
umzubenennen. Im Eventloop ausgeführt, hielte das bei einem großen Scan den gesamten Dienst
an — Watcher, Retry-Schleife, SSE-Streams und jede weitere Anfrage. Beide Routen rufen ihre
Entscheidung deshalb über `asyncio.to_thread` auf.

### Freigabe ohne Original

Entfernt jemand die Datei von Hand aus `scan-in`, liefe die Freigabe ins Leere — der
Vorgang würde eingereiht und scheiterte drei Versuche lang an derselben fehlenden Datei.
Stattdessen endet er sofort auf `failed` mit einer Meldung, die das fehlende Original
benennt.

## Wiederaufnahme nach der Freigabe

Die Route setzt nur den Zustand. Eingereiht wird der Vorgang von `claim_due_retries` beim
nächsten Takt der Retry-Schleife — also **binnen 30 Sekunden**, nicht sofort. Das ist
Absicht: Keine Route koppelt an die Worker-Queue, und die Freigabe übersteht dadurch einen
Neustart zwischen Klick und Verarbeitungsbeginn. Die Oberfläche zeigt den Vorgang in dieser
Zeit als `pending`.

## Anzeige

Eigene Statuskachel und eigener Filterwert („Angehalten"), eigener Farbton
(`--violet` / `--violet-bg`, Kontrast 6.3:1 in hell wie dunkel). Die Kachelreihe verteilt
sich seit dem sechsten Zustand über `auto-fit` statt über eine feste Spaltenzahl.

`tests/test_status_consistency.py` hält die vier Stellen zusammen, an denen die
Zustandsmenge redundant gepflegt ist (`DocStatus`, `STATUS_LABELS`, `tile_order`, CSS).
Ein vergessener Eintrag knallt sonst nicht — er geht still daneben.

## Vor einem Rollback

Die Spalte `page_limit_approved` stört eine ältere Fassung nicht (sie liest sie nicht).
Ein Vorgang, der zum Zeitpunkt des Rollbacks auf `blocked` steht, wäre für sie aber ein
**unbekannter Zustandswert** — `DocStatus(row["status"])` wirft dort beim Zurücklesen.
Deshalb vor einem Rollback alle offenen angehaltenen Vorgänge entscheiden (freigeben oder
verwerfen). Sind keine offen, ist der Rollback folgenlos.
