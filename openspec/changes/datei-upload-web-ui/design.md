# Design

## Context

Siehe `proposal.md` — Why. Für den Entwurf relevant ist der bestehende Eingangsweg:

```
   scan-in  --(scan_dir, alle POLL_INTERVAL_SECONDS)-->  StabilityTracker
                                                              |
                        Teil-Suffix?  -> nie fertig            |
                        Groesse < 1?  -> nie fertig            |
                        Groesse >= STABILITY_WINDOW_SECONDS    |
                        unveraendert  -> fertig ---------------+
                                                              v
                                                       _intake_file()
                              is_supported? -> Hash -> Dedup -> create_document(pending)
                                                              |
                                                              v
                                                      Queue -> Pipeline
```

Maßgebliche Randbedingungen:

- `StabilityTracker` (`app/watcher.py`) ist rein zeitbasiert und poll-unabhängig. Ein zusätzlicher
  Auslöser verfälscht die Logik nicht, verkürzt aber auch das Stabilitätsfenster nicht.
- `PARTIAL_SUFFIXES` (Standard `.tmp,.part,.crdownload`) schließt Dateien mit diesen Endungen
  bedingungslos von der Aufnahme aus — unabhängig davon, wer sie geschrieben hat.
- `WATCH_DIR` ist im Betrieb ein eigener Bind-Mount (`./scan-in:/scan-in`), getrennt von
  `/tmp` im Container.
- `fileops.unique_target()` vergibt bereits kollisionsfreie Zielnamen (`_1`, `_2`, …).
- Der Start prüft `WATCH_DIR` bereits auf Schreibbarkeit (`_check_writable_paths` in
  `app/main.py`).
- Die Oberfläche ist serverseitiges Jinja2 mit Vanilla-JS, ohne HTMX und ohne Buildchain.
  Bestehende Schreib-Aktionen laufen als `POST` + `303 Redirect`.
- `python-multipart` ist bereits Abhängigkeit (für die vorhandenen `Form(...)`-Routen).

## Goals / Non-Goals

**Goals:**

- Der Upload-Weg endet an der Übergabe in `WATCH_DIR`. Ab dort existiert **kein**
  upload-spezifischer Code.
- Keine neuen Zustände, Felder oder Ereignistypen im Datenmodell.
- Der Entwurf soll ohne JavaScript funktionieren.

**Non-Goals (auf Entwurfsebene, ergänzend zum Proposal):**

- Kein Fortschrittsbalken während der Übertragung. Ein `XMLHttpRequest`-basierter Fortschritt
  wäre nachrüstbar, ohne den hier beschriebenen Server-Teil zu ändern.
- Keine Verkürzung oder Umgehung des Stabilitätsfensters für hochgeladene Dateien.
- Kein eigener Zwischenspeicher und keine Warteschlange vor dem Eingangsordner.

## Decisions

### Entscheidung 1: Der Upload schreibt in den Eingangsordner, statt direkt aufzunehmen

**Gewählt:** Der Endpunkt legt die Datei in `WATCH_DIR` ab und ist damit fertig. Die Aufnahme
übernimmt der normale Scan-Lauf.

**Alternative: Direkt-Aufnahme** — der Endpunkt ruft die Aufnahme selbst auf, nachdem er die
Datei geschrieben hat. Vorteil: der Vorgang erscheint sofort statt nach bis zu rund acht
Sekunden (`POLL_INTERVAL_SECONDS` 2 s + `STABILITY_WINDOW_SECONDS` 6 s).

**Warum verworfen:** Es entstünde ein zweiter Eingangspfad, der an der Vollständigkeitsprüfung
vorbeiführt. Inhaltlich wäre das vertretbar — der Dienst hat die Datei ja selbst geschrieben und
weiß, dass sie vollständig ist —, aber es müsste zusätzlich verhindert werden, dass der
anschließende Scan-Lauf dieselbe Datei ein zweites Mal aufnimmt. Der vorhandene Prüfsummen-
Abgleich fängt das nur ab, solange der erste Vorgang noch aktiv ist; bei einer sehr schnell
abgeschlossenen Verarbeitung entstünde ein Doppel-Vorgang. Die gewonnene Latenz rechtfertigt
diese zusätzliche Kopplung zwischen Web-Schicht und Worker nicht.

**Alternative: Worker nach dem Schreiben wecken** — spart den Poll-Anteil, aber das
Stabilitätsfenster greift weiterhin. Der Gewinn beträgt maximal zwei Sekunden bei zusätzlicher
Kopplung; verworfen.

### Entscheidung 2: Schreiben unter Teil-Suffix, dann Umbenennen auf den Zielnamen

**Gewählt:** Die Übertragung wird nach `<zielname>` + einem konfigurierten Teil-Suffix
geschrieben und nach vollständigem Schreiben per atomarem Rename auf den Zielnamen gebracht.

**Warum:** Ein direkt unter dem Zielnamen geschriebener Stream wäre *fast* sicher — der Tracker
sieht die wachsende Größe und beginnt das Fenster jeweils neu. Stockt die Übertragung jedoch
länger als `STABILITY_WINDOW_SECONDS` bei unveränderter Größe (langsames WLAN, hängender Client),
gilt der unvollständige Stand als fertig und ein halbes PDF geht in die Verarbeitung. Das
Teil-Suffix schließt diesen Fall hart aus und nutzt einen Mechanismus, den der Eingangsordner
ohnehin beherrscht — inklusive des bereits spezifizierten Verhaltens beim Umbenennen auf den
Zielnamen.

Der Zielname wird **vor** dem Schreiben über `unique_target()` bestimmt, damit das Teil-Suffix
an einem bereits kollisionsfreien Namen hängt. Ein Restrisiko bleibt: zwischen Namensvergabe und
Umbenennen könnte eine gleichnamige Datei von außen entstehen. Bei einem Einzelnutzer-Betrieb mit
gelegentlichen Uploads ist das hinnehmbar; ein zweiter `unique_target()`-Aufruf unmittelbar vor
dem Umbenennen kann es weiter verkleinern.

### Entscheidung 3: Zwischenablage innerhalb des Eingangsordners, nicht in `/tmp`

**Gewählt:** Die Teil-Datei entsteht im Eingangsordner selbst.

**Warum:** `WATCH_DIR` ist ein eigener Mount. Ein Verschieben von `/tmp` dorthin wäre ein
Kopieren über Dateisystemgrenzen — also kein atomarer Rename, und die Zieldatei würde erneut
sichtbar wachsen. Damit wäre der Gewinn aus Entscheidung 2 wieder verloren.

**Trade-off:** Die Teil-Datei belegt Platz im Eingangsordner und bleibt bei einem Absturz
mitten in der Übertragung liegen. Da sie ein Teil-Suffix trägt, wird sie nie verarbeitet — sie
ist eine Leiche, kein Fehler. Ein Aufräumen beim Start ist möglich, aber für den ersten Wurf
nicht vorgesehen; siehe Risiken.

### Entscheidung 4: Format-Prüfung über die vorhandene Endungs-Liste, aber mit Rückmeldung

**Gewählt:** Der Endpunkt prüft gegen dieselbe Endungs-Liste wie der Eingangsordner
(`detection.is_supported`) und weist ab, statt zu übergehen.

**Warum die Abweichung im Verhalten:** Im Eingangsordner ist stilles Übergehen richtig — die
Datei bleibt sichtbar liegen und der Nutzer sieht selbst, dass nichts passiert. Beim Upload
verschwindet die Datei aus dem Blickfeld des Nutzers; ohne Rückmeldung bliebe unklar, ob sie
angekommen ist. Das ist die einzige Stelle, an der sich beide Wege fachlich unterscheiden.

**Bewusst nicht gewählt:** eine Prüfung des Dateiinhalts (Magic Bytes). Der Eingangsordner
entscheidet ebenfalls allein über die Endung, und eine strengere Prüfung im Upload-Weg würde
beide Wege auseinanderlaufen lassen.

### Entscheidung 5: Namensabsicherung durch Reduktion auf den reinen Namensanteil

**Gewählt:** Der gelieferte Name wird auf seinen letzten Pfadbestandteil reduziert; zusätzlich
werden Namen zurückgewiesen oder ersetzt, die danach leer sind oder nur aus Punkten bestehen.

**Warum:** Der Name kommt vom Client und ist damit unvertrauenswürdig — unabhängig davon, dass
der Dienst im LAN ohne Authentifizierung betrieben wird. Ein Name wie `../../data/lector.db`
darf unter keinen Umständen zu einem Schreibzugriff außerhalb des Eingangsordners führen. Die
Reduktion ist billig und macht die Klasse von Fehlern strukturell unmöglich, statt sie durch
Prüfungen abzufangen.

### Entscheidung 6: Formular im Dashboard, `POST` + `303 Redirect`

**Gewählt:** Ein Formular mit Mehrfachauswahl über der bestehenden Filterleiste in
`dashboard.html`, abgeschickt an einen neuen Endpunkt, der auf die Übersicht zurückleitet.

**Warum:** Es folgt dem Muster der bestehenden Schreib-Aktionen (`/documents/{id}/release`,
`/empfaenger/…`) und funktioniert ohne JavaScript. Eine eigene Seite `/upload` mit Nav-Eintrag
wäre sauberer getrennt, kostet aber für eine seltene Aktion einen zusätzlichen Klick.

Die Rückmeldung über abgewiesene Dateien und über die verzögerte Sichtbarkeit wird beim Redirect
mitgegeben und in der Übersicht ausgegeben. Der bestehende SSE-Kanal trägt den Vorgang
anschließend von selbst nach, sobald er angelegt wurde — dafür ist nichts zu ändern.

## Risks / Trade-offs

**Der Vorgang erscheint erst nach bis zu rund acht Sekunden** → Die Oberfläche benennt das nach
der Übergabe ausdrücklich, damit der Nutzer nicht in der Annahme, es sei nichts passiert, erneut
hochlädt. Wird die Wartezeit in der Praxis als störend empfunden, ist
`STABILITY_WINDOW_SECONDS` bereits konfigurierbar — ohne Codeänderung.

**Ein Doppel-Upload derselben Datei wird still verworfen** → Der Prüfsummen-Abgleich greift erst
bei der Aufnahme, also nach der Rückmeldung an den Nutzer. Der Upload kann das nicht sofort
melden, ohne die Prüfsumme selbst zu bilden und den Abgleich vorzuziehen — was den Upload-Weg
fachlich vom Eingangsordner abkoppeln würde. Bewusst ausgeklammert (siehe `proposal.md`). Sollte
es stören, ist es nachrüstbar, ohne die hier getroffenen Entscheidungen zu berühren.

**Abgebrochene Übertragungen hinterlassen Teil-Dateien im Eingangsordner** → Sie tragen ein
Teil-Suffix und werden daher nie verarbeitet. Sie belegen Platz und fallen beim Blick in den
Ordner auf. Der Endpunkt räumt bei einem erkannten Fehlschlag selbst auf; gegen einen
Prozessabbruch mitten im Schreiben hilft das nicht. Ein Aufräum-Schritt beim Start wäre die
naheliegende Ergänzung, ist hier aber nicht vorgesehen.

**Sehr große Dateien belegen Verarbeitungszeit und verursachen OCR-Kosten** → Bewusst nicht
begrenzt: der Dienst läuft im LAN, der Nutzerkreis ist bekannt und die vorhandene Grenze
`MAX_PAGES_PER_DOCUMENT` greift in der Pipeline. Ein `MAX_UPLOAD_SIZE_MB` wäre eine kleine,
jederzeit nachrüstbare Ergänzung.

**Der Dienst bleibt unauthentifiziert** → Wer die Oberfläche erreicht, kann künftig nicht nur
lesen und Vorgänge steuern, sondern auch Dateien in das Dateisystem des Dienstes schreiben.
Das ist eine bewusste Entscheidung für den LAN-Betrieb (siehe `proposal.md`). Die
Namensabsicherung aus Entscheidung 5 begrenzt den Schreibzugriff dabei strukturell auf den
Eingangsordner.

## Migration Plan

Keine Migration nötig. Es gibt keine Schema-Änderung, keine neue Abhängigkeit und keinen neuen
Pflichtparameter; `WATCH_DIR` ist im Compose-Stack bereits beschreibbar eingebunden. Ein
Rollback ist das Zurückrollen des Images — bereits übergebene Dateien liegen dann als gewöhnliche
Dateien im Eingangsordner und werden normal verarbeitet.
