# Design

## Context

Siehe `proposal.md` — Why, und die Tabelle der Absturzfenster.

Drei Eigenschaften des Bestands bestimmen den Lösungsraum:

1. **Die Verarbeitung ist streng seriell in genau einem Prozess.** Ein Vorgang auf
   `processing` kann beim Start deshalb zu keinem lebenden Bearbeiter gehören. Es braucht
   keine Heartbeat- oder Lease-Mechanik, um das festzustellen.
2. **Der Ausgabeordner ist kein verlässlicher Zeuge.** Paperless überwacht ihn und entfernt
   jede Datei, die es eingelesen hat. Die Abwesenheit eines Ergebnisses beweist also *nicht*,
   dass es nie abgelegt wurde — sie ist der Normalfall nach erfolgreicher Übergabe.
   Umgekehrt ist eine vorhandene Datei nicht zweifelsfrei einem Vorgang zuzuordnen, weil bei
   Namenskollisionen stumm ein Zusatz vergeben wird.
3. **Für die Rechnungsseite existiert ein Vorbild.** Verwaiste Export-Claims werden in der
   Startsequenz bereinigt, bevor der Worker läuft, und landen in einem Zustand, der bewusst
   keinen Auto-Retry auslöst. Diese Change spiegelt Ort und Haltung, nicht die Entscheidung
   selbst — die Fehlerkosten liegen hier anders.

## Goals / Non-Goals

**Goals:**

- Eine Auflösung, die sich auf Zustandsdaten des Vorgangs stützt statt auf Ratespiele im
  Dateisystem.
- Die Entscheidung ist in Grenzfällen erklärbar und im Verlauf nachlesbar.
- Kein Schema-Eingriff, kein neuer Zustand, keine Änderung der Verarbeitungsreihenfolge.

**Non-Goals:**

- Fortsetzen einer unterbrochenen Verarbeitung *mitten im Dokument*. Ein Neuversuch beginnt
  bei Seite eins. Das Zwischenspeichern bezahlter Teilergebnisse ist eine eigene bekannte
  Lücke und bleibt dort.
- Erkennen, ob der Worker *im laufenden Betrieb* hängt. Dafür braucht es einen
  aussagekräftigen Health-Endpunkt — eigene Change.
- Schutz gegen zwei gleichzeitig laufende Lector-Prozesse auf derselben Datenbank. Das
  widerspräche der seriellen Architektur und ist nicht vorgesehen.

## Decisions

### D1 — Der Fortschritt wird am Vorgang abgelesen, nicht im Ausgabeordner gesucht

Die Auflösung stützt sich auf zwei Tatsachen, die bereits gespeichert sind: **wo das Original
liegt** und **ob ein Ablageort vermerkt ist**.

| Original | Ablageort vermerkt | Auflösung |
|---|---|---|
| verarbeitet | egal | abschließen — die Ablage lag davor, sie ist passiert |
| Eingang | ja | abschließen, Original nachziehen |
| Eingang | nein | siehe D2 |
| nirgends auffindbar | egal | gescheitert, erklärende Meldung |

*Warum nicht den Ausgabeordner als Wahrheit nehmen?* Weil Paperless ihn leert (Context 2).
Ein „liegt nicht da, also nie abgelegt" wäre nach jeder erfolgreichen Übergabe falsch.

*Verworfene Alternative:* eine zusätzliche Spalte für die erreichte Phase. Sie würde das
Modell erweitern, ohne mehr auszusagen als die beiden vorhandenen Tatsachen — die
Reihenfolge der Schritte ist bekannt und fest.

### D2 — Das verbleibende Fenster wird als unklar behandelt, nicht geraten

Bleibt ein Vorgang mit Original im Eingangsordner und ohne vermerkten Ablageort, ist er
entweder vor der Ablage gestorben (dann ist ein Neuversuch richtig) oder exakt zwischen dem
Verschieben der Ergebnisdatei und dem Vermerk (dann wäre ein Neuversuch eine Doppelablage).

Die Auflösung prüft deshalb, ob im Ausgabeordner eine Datei mit dem erwarteten Namen liegt,
die **nach dem Beginn dieses Vorgangs** verändert wurde. Trifft das zu, gilt der Vorgang als
unklar und wird als gescheitert markiert — mit einer Meldung, die zur Prüfung in Paperless
auffordert. Andernfalls wird er neu eingereiht.

*Warum im Zweifel gescheitert statt Neuversuch?* Die Fehlerkosten sind unsymmetrisch. Ein zu
Unrecht als gescheitert markierter Vorgang kostet einen Blick in den Fehlerordner und eine
erneute Ablage — sichtbar und reversibel. Eine Doppelablage erzeugt zwei Dokumente in
Paperless, fällt erst dort auf und ist von Hand aufzuräumen. Bei Unklarheit gewinnt die
sichtbare Variante.

*Verworfene Alternative:* den Ablageort schon **vor** dem Verschieben vermerken. Das
verschiebt die Unklarheit nur: Dann bedeutet ein vermerkter Ablageort ohne Datei entweder
„Verschieben kam nie zustande" oder „Paperless hat sie längst geholt". Gleiche Zweideutigkeit,
zusätzlicher Umbau an der Pipeline.

### D3 — Die Auflösung läuft in der Startsequenz, vor dem Worker

Sie gehört an dieselbe Stelle wie die Bereinigung der Export-Claims: nach dem Öffnen der
Datenbank, vor dem Start des Workers. Damit ist zugesichert, dass kein neu aufgenommenes
Dokument einem unaufgelösten Vorgang zuvorkommt, und die Anzahl lässt sich in einer Zeile
protokollieren.

### D4 — Ein Vorgang wird über denselben Weg abgeschlossen wie im Normalfall

Abschließen heißt: Original nachziehen, sofern es noch im Eingangsordner liegt, Endzustand
setzen und Verlaufseintrag schreiben — also die Schritte, die der reguläre Ablauf ohnehin
kennt. Der E-Rechnungs-Weg endet dabei in seinem eigenen Endzustand, nicht im Endzustand des
OCR-Wegs; die Unterscheidung ergibt sich aus dem bereits erkannten Dokumenttyp.

## Risks / Trade-offs

**Ein Absturz im Mikrofenster, während Paperless die Datei bereits geholt hat** → Der
Nachweis aus D2 findet nichts und der Vorgang wird neu verarbeitet — Doppelablage. Das
Fenster ist die Zeitspanne zwischen einem abgeschlossenen Verschiebevorgang und einem
Datenbankschreibzugriff, und es muss zusätzlich mit dem Abfragetakt von Paperless
zusammenfallen. Nicht ausschließbar, aber um Größenordnungen unwahrscheinlicher als der heute
garantierte Totalausfall. Bewusst in Kauf genommen statt durch ein Transaktionsprotokoll
über Dateisystem und Datenbank erschlagen.

**Der Namensabgleich aus D2 greift zu weit** → Ein unbeteiligtes Dokument gleichen Namens im
Ausgabeordner könnte einen Vorgang fälschlich als unklar einstufen. Abgemildert durch die
Zeitschranke (Änderung nach Beginn des Vorgangs) und dadurch, dass die Folge lediglich eine
sichtbare manuelle Prüfung ist, kein Datenverlust.

**Wiederkehrende Unterbrechungen bleiben unbemerkt** → Wird der Dienst regelmäßig mitten in
der Arbeit neu gestartet, häufen sich aufgelöste Vorgänge, ohne dass jemand die Ursache
sieht. Abgemildert durch die protokollierte Anzahl je Start; eine echte Auswertung wäre
Sache des Health-Endpunkts.

**Auflösung schlägt selbst fehl** → Ein Fehler während der Auflösung darf den Start nicht
verhindern, sonst macht ein einzelner kaputter Vorgang den Dienst unstartbar. Je Vorgang
einzeln behandeln, Fehler protokollieren, mit dem nächsten weitermachen.

## Migration Plan

Kein Datenmigrationsschritt: kein Schema-Eingriff, kein neuer Zustand, keine neue
Konfiguration. Vorgänge, die **heute schon** auf `processing` festhängen, werden beim ersten
Start mit der Änderung nach denselben Regeln aufgelöst — der Rückstand räumt sich also von
selbst ab.

Rollback ist ein Zurücksetzen des Images. Bereits aufgelöste Vorgänge bleiben aufgelöst; sie
stehen dann in regulären Endzuständen, die die alte Fassung ebenso versteht.
