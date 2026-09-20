# Proposal

## Why

Stirbt der Prozess, während ein Dokument verarbeitet wird, bleibt sein Vorgang dauerhaft im
Zustand `processing` liegen. Die Wiederaufnahme beim Start berücksichtigt ausschließlich
Vorgänge im Zustand `pending`; ein `processing`-Vorgang wird also weder wiederholt noch als
gescheitert markiert. Er verschwindet lautlos aus dem Betrieb, und die zugehörige Datei
bleibt unbearbeitet im Eingangsordner liegen.

Das trifft jeden Container-Neustart, jedes Deployment und jeden Speicherengpass, der mitten
in einem längeren Dokument zuschlägt — also den Normalfall im Betrieb, nicht den Ausnahmefall.

Für die Rechnungsseite ist genau dieses Problem bereits gelöst: Verwaiste Export-Claims
werden beim Start bereinigt. Der OCR-Weg — das eigentliche Produkt — hat kein Gegenstück.

## What Changes

- Beim Start wird jeder Vorgang im Zustand `processing` aufgelöst. Danach existiert kein
  Vorgang mehr in diesem Zustand, der zu keinem laufenden Prozess gehört.
- Die Auflösung richtet sich nach dem **erreichten Fortschritt**, nicht pauschal nach dem
  Zustand. Ein einfaches Zurücksetzen auf `pending` wäre falsch (siehe unten).
- Der Verlauf hält fest, dass und wie ein Vorgang nach einem Neustart aufgelöst wurde.

**Kein** neuer Zustand: Jeder unterbrochene Vorgang endet in einem der bestehenden Zustände
`done`, `skipped_erechnung`, `pending` oder `failed`.

### Warum ein Zurücksetzen auf `pending` nicht genügt

Die Veredelung legt das Ergebnis ab, **bevor** sie den Vorgang als abgeschlossen markiert.
Zwischen diesen Schritten liegen mehrere Fenster, in denen ein Absturz unterschiedliche
Spuren hinterlässt:

| Absturz nach … | Ergebnis im Ausgabeordner | Original | Folge eines naiven Neuversuchs |
|---|---|---|---|
| Texterkennung, vor der Ablage | nein | Eingang | korrekt — Neuversuch ist richtig |
| Ablage des Ergebnisses | **ja**, am Vorgang noch nicht vermerkt | Eingang | **Doppelablage**: Paperless importiert das Dokument zweimal |
| Vermerk des Ablageorts | ja, vermerkt | Eingang | Doppelablage |
| Verschieben des Originals | ja, vermerkt | verarbeitet | Neuversuch scheitert dreimal mangels Original und endet auf `failed`, obwohl das Ergebnis korrekt abgeliefert wurde |

Die Doppelablage bleibt unbemerkt, weil bei einer Namenskollision im Ausgabeordner
automatisch ein Namenszusatz vergeben wird, statt einen Fehler zu melden. Aus einem
abgestürzten Lauf würden also zwei Dokumente in Paperless — und das fällt erst dort auf.

## Capabilities

### New Capabilities

Keine.

### Modified Capabilities

- `verarbeitungs-lebenszyklus`: Ergänzt um eine Zusicherung, dass beim Start kein Vorgang im
  Zustand `processing` zurückbleibt und wie ein unterbrochener Vorgang je nach erreichtem
  Fortschritt aufgelöst wird. Die bestehende Zusicherung zu fälligen Wiederholversuchen
  bleibt unverändert — sie betrifft `pending` und wird von dieser Änderung nicht berührt.

## Impact

**Betroffener Code:** die Startsequenz des Dienstes, die Datenzugriffsschicht (eine neue
Abfrage plus Auflösungslogik) und die Verarbeitungs-Pipeline, soweit der Fortschritt
nachvollziehbar sein muss.

**Keine Änderung** an der OCR-Engine, der Formaterkennung, der Weboberfläche, am Datenmodell
(keine neue Spalte, kein neuer Zustand), an der Konfiguration oder am Deployment.

**Nicht in dieser Change:** Die übrigen sieben bekannten Lücken aus
`baseline-specs-kernpipeline`, insbesondere der aussagekräftige Health-Endpunkt. Ein
Recovery hilft nicht dabei zu bemerken, dass der Worker überhaupt steht — das bleibt eine
eigene Change.

**Risiko:** Die Auflösung entscheidet anhand von Spuren im Dateisystem und in der Datenbank.
Eine Fehlentscheidung in die eine Richtung erzeugt eine Doppelablage, in die andere ein
verlorenes Ergebnis. Der sichere Ausweg bei Unklarheit ist der Zustand `failed` mit einer
erklärenden Meldung — das Original bleibt dann im Fehlerordner erhalten und ist manuell
prüfbar. Diese Abwägung gehört nach `design.md`.
