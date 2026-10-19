# Design

## Context

Der Scan-Weg in `HauptAnsicht.swift` setzt im `fertig`-Callback des Scanners zwei Zustände
im selben Durchlauf:

```
fertig: { bilder in
    scannerOffen = false                       // fullScreenCover beginnt zu schließen
    uebergeben { _ in bilder.map { .bild($0) } }  // setzt erfassung -> .sheet(item:) soll erscheinen
}
```

SwiftUI präsentiert das Blatt, während die Vollbild-Ansicht noch abgebaut wird. Das Blatt wird
dabei einmal abgeräumt und, weil `erfassung` gesetzt bleibt, mit demselben Modell neu
präsentiert. Die Folgen im Code:

1. `ErfassungsAnsicht.onDisappear` ruft `modell.aufraeumen()` und löscht den Arbeitsordner.
2. Die `.task` des ersten Blatts wird abgebrochen. `starten()` prüft aber nach dem
   PDF-Zeichnen (`Task.detached`, ignoriert den Abbruch) nicht auf Abbruch und ruft `senden()`.
3. `MultipartRumpf.schreiben` öffnet die PDF per Pfad, die Datei ist weg:
   `UploadFehler.dateiNichtLesbar`. Den Fehler fängt nur der allgemeine `catch`, Meldung
   „Senden fehlgeschlagen.“.
4. Das zweite Blatt startet nichts (`zustand != .bereit`) und zeigt den Zustand des ersten Laufs.

Belege: Das Lector-Log zeigt beim Scan `GET /api/info`, `GET /api/v1/documents` und
`GET /events` der App, aber keinen `POST /api/v1/upload`. Die Fotoauswahl funktioniert, weil
`photosPicker` schon geschlossen ist, wenn `onChange(of: fotoAuswahl)` das Blatt öffnet.
Der Mechanismus (doppelte Präsentation) ist aus dem Code abgeleitet, nicht direkt beobachtet.
Die Korrektur ist deshalb zweigleisig ausgelegt: Ursache beseitigen und die Lebensdauer der
Datei unabhängig davon robust machen.

## Goals / Non-Goals

**Goals:**

- Der Scan wird zuverlässig übergeben.
- Die vorbereitete Datei lebt genau so lange wie die Übergabe-Ansicht aus Sicht der Person.
- Ein abgebrochener Ablauf löst keinen Upload mehr aus.
- Eine fehlende Datei wird als solche gemeldet.
- Ein automatischer Test fängt die Präsentationsfolge „Vollbild schließt, Blatt öffnet“ ab.

**Non-Goals:**

- Keine Änderung an PDF-Erzeugung, Upload-Format, Server oder Schnittstelle.
- Keine Änderung an der Share Extension (`TeilenModell`, eigener Ablauf ohne diese Präsentation).
- Keine Warteschlange und kein Speichern über das Schließen hinaus (Spec bleibt dabei).

## Decisions

### D1: Blatt erst nach dem Schließen des Scanners öffnen

Der `fertig`-Callback merkt sich die Bilder in einem `@State` (`ausstehenderScan: [UIImage]?`)
und setzt nur `scannerOffen = false`. Das `onDismiss` der `fullScreenCover` übernimmt die
Bilder und ruft `uebergeben`. `onDismiss` feuert erst, wenn die Vollbild-Ansicht vollständig
weg ist. Danach gibt es keine laufende Präsentation mehr.

Verworfen: eine feste Verzögerung (`DispatchQueue.main.asyncAfter`). Sie hängt von der
Animationsdauer ab und ist nicht deterministisch. Verworfen: den Scanner aus dem Blatt heraus
präsentieren. Das ändert den Bedienablauf ohne Mehrwert.

### D2: Aufräumen an das Schließen des Blatts binden, nicht an `onDisappear`

`ErfassungsAnsicht.onDisappear { modell.aufraeumen() }` entfällt. Aufgeräumt wird im
`onDismiss` von `.sheet(item: $erfassung, onDismiss:)` in `HauptAnsicht`, also wenn das Blatt
aus Sicht der Präsentation wirklich geschlossen ist. Das Modell, dessen Ordner gelöscht wird,
merkt sich `HauptAnsicht` dafür vor dem Zurücksetzen (z. B. `erfassung` beim Schließen-Button
und in `onDismiss` auswerten). So greift D2 auch dann, wenn D1 eine Präsentationsfolge nicht
abdeckt, und gilt gleich für den Foto- und den Testbild-Weg.

Alternative: `aufraeumen()` in `deinit` des Modells. Verworfen, weil `@MainActor`-Modelle in
`deinit` nicht isoliert arbeiten und der Zeitpunkt nicht verlässlich ist.

### D3: Abbruch nach der Vorbereitung beachten

`starten()` prüft nach `pdfErzeugen` mit `Task.isCancelled` bzw. `try Task.checkCancellation()`
und kehrt ohne Upload zurück. Der Zustand wird dabei auf `.bereit` zurückgesetzt statt in
`.vorbereiten` hängen zu bleiben, damit eine erneut präsentierte Ansicht den Ablauf von vorn
starten kann (Vorbereitung inklusive). Das ist einfacher als ein Wiederaufsetzen mitten im
Ablauf und kostet nur eine erneute PDF-Erzeugung.

### D4: Eigene Meldung für `UploadFehler.dateiNichtLesbar`

`senden()` fängt `UploadFehler.dateiNichtLesbar` ausdrücklich und setzt
`.abgewiesen("Der vorbereitete Beleg liegt nicht mehr vor. Bitte neu erfassen.")`.
`.abgewiesen` statt `.fehlgeschlagen`, weil erneutes Senden ohne Datei nicht helfen kann.
`vorbereitet` wird dabei verworfen.

### D5: Regressionstest über den Testbild-Weg

Neues Startargument `-UITEST_TESTSCAN`: Im Menü erscheint „Testscan übergeben“. Der Eintrag
öffnet eine einfache Vollbild-Ansicht (`fullScreenCover`) mit einem Button „Speichern“, der
dieselbe Übergabe-Logik wie der echte Scanner nutzt (dieselbe `fertig`-Closure bzw. derselbe
`ausstehenderScan`-Weg). Der UI-Test tippt „Speichern“ und erwartet `erfassung.uebergeben`.
Damit ist der Präsentationspfad des Scanners auf dem Simulator abgedeckt, wo
`VNDocumentCameraViewController` nicht verfügbar ist. Mit dem alten Code sollte der Test
fehlschlagen (Nachweis vor dem Fix, siehe Tasks).

Unit-Tests in `ErfassungsModellTests`: Abbruch nach der Vorbereitung löst keinen Upload aus.
Eine fehlende Datei ergibt `.abgewiesen` mit der neuen Meldung.

## Risks / Trade-offs

- **Der UI-Test reproduziert den Fehler mit dem alten Code nicht.** Das Timing des echten
  Scanners kann sich von einer einfachen Vollbild-Ansicht unterscheiden. → Vor dem Fix prüfen.
  Schlägt der Test nicht fehl, deckt er zumindest den neuen Weg ab. Die Geräteabnahme auf dem
  iPhone bleibt der maßgebliche Nachweis.
- **Testscan-Weg nur in Debug.** Wie der bestehende Testbild-Weg hinter `#if DEBUG`, kein
  Einfluss auf Release.
- **Hypothese zum Mechanismus nicht direkt beobachtet.** D2 und D3 wirken unabhängig von der
  genauen Präsentationsfolge. Selbst wenn D1 den Auslöser nicht vollständig trifft, verschwindet
  die Datei nicht mehr während einer offenen Übergabe.

## Migration Plan

Neuer TestFlight-Build mit erhöhter `CURRENT_PROJECT_VERSION`. Keine Server-Änderung, kein
Datenbestand betroffen. Rücknahme: vorherigen Build in TestFlight wieder aktivieren.

## Open Questions

_keine_

## Nacharbeit aus dem Review

### D6: Verwaiste Arbeitsordner wegräumen

Das Aufräumen hängt jetzt am `onDismiss` des Blatts. Fällt `HauptAnsicht` mit offenem Blatt weg
(Sitzung abgelaufen, Wechsel zur Anmeldung), feuert es nicht, und der Ordner bleibt liegen.
Zwei Ergänzungen:

- `uebergeben` räumt ein noch vorgemerktes `offeneErfassung` auf, bevor es ein neues Modell setzt.
  Damit geht kein Verweis mehr verloren.
- Eine statische Funktion `ErfassungsModell.verwaisteAufraeumen(ausser:)` löscht alle
  `erfassung-*`-Ordner im temporären Verzeichnis außer dem des offenen Modells.
  `HauptAnsicht` ruft sie beim Erscheinen auf (`.task`). Das erfasst auch Reste nach einem
  Absturz oder Beenden der App. Die Share Extension hat ein eigenes temporäres Verzeichnis
  und ist nicht betroffen.

Verworfen: `onDisappear` an `HauptAnsicht`. Ob es beim Präsentieren eines Vollbilds feuert, ist
nicht verlässlich. Damit stünde dieselbe Fehlerklasse wieder im Raum.

### D7: Fehlende Datei und nicht schreibbarer Upload-Rumpf unterscheiden

`MultipartRumpf.schreiben` meldet bisher jeden Fehler als `UploadFehler.dateiNichtLesbar`, auch
einen nicht schreibbaren Rumpf, etwa bei vollem Speicher. `hochladen` unterscheidet künftig:

- `dateiNichtLesbar`: Die Quelldatei lässt sich nicht öffnen. Meldung wie D4, `.abgewiesen`.
- `rumpfNichtSchreibbar` (neu): Der Rumpf lässt sich nicht anlegen oder schreiben. `.fehlgeschlagen`
  mit „Der Beleg konnte nicht zum Senden vorbereitet werden. Ist der Gerätespeicher voll?“.
  Die Datei liegt noch vor, „Erneut senden“ bleibt möglich.

Das `TeilenModell` der Share Extension fängt den Fehler nicht gezielt ab und meldet ihn weiter
über seinen allgemeinen Zweig. Das Verhalten dort bleibt unverändert.
