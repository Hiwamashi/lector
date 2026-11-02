# Kontext-Einstufung „IT-Consulting“

**Module:** `app/context_classification.py` (`classify`, `context_bucket`),
`app/invoice_overview.py` (`build_rows`, Filter), `app/repository.py`
(`correspondent_context_history`, `get_recipient_caches`), `app/recipient_llm.py`
(Wahrscheinlichkeit der KI), `app/paperless_sync.py` (`recipient_option_available`),
`app/main.py` (Anzeige-Labels). Die Herkunft der Felder steht in
[empfaenger-zuordnung.md](empfaenger-zuordnung.md) und [sync-und-aktionen.md](sync-und-aktionen.md).

## Zweck

Die Übersicht soll zeigen, ob eine Rechnung zum Geschäftskontext gehört. Dieser Change nutzt
dafür genau einen Kontext: **IT-Consulting**. Das Label ist konfigurierbar
(`SEVDESK_CONTEXT_LABEL`, Standard `IT-Consulting`). Die Einstufung dient der Auswahl der
Rechnungen, die nach SevDesk sollen. Ein Export erfolgt **nie** allein aufgrund der Einstufung.

Lector speichert die Einstufung **nicht**. Sie wird bei jedem Aufruf der Übersicht neu aus
SQLite berechnet. Begründung (Design 3): Die Änderung einer Rechnung verschiebt die Historie
anderer Rechnungen desselben Korrespondenten. Eine gespeicherte Spalte würde also laufend
veralten.

## Kontext-Option im Paperless-Feld „Empfänger“

- Der Kontext ist eine **Option** des bestehenden select-Feldes „Empfänger“ (`CF_RECIPIENT`,
  Standard `Empfänger`). Die Option muss in Paperless vorhanden sein. Lector legt sie **nicht**
  an.
- Der Vergleich mit dem Label läuft über `same_label` (`app/context_classification.py`): Randleerraum
  wird entfernt, Groß-/Kleinschreibung spielt keine Rolle. Dasselbe gilt überall im Code, wo Labels
  verglichen werden (siehe Fallstricke).
- **Option fehlt.** `PaperlessSync.recipient_option_available(label)` liefert:
  - `None`, solange das Feld noch nicht aufgelöst ist. Die Übersicht ruft dafür **keinen**
    Paperless-Aufruf aus. `None` gilt als „vorhanden“, die Einstufung wird also angezeigt.
  - `False`, wenn das Feld aufgelöst ist und die Option fehlt oder das Feld selbst fehlt.
  - `True`, wenn die Option vorhanden ist.
- Bei `False` zeigt die Übersicht den Hinweis „Rechnungen sind nicht einstufbar“ mit dem
  erwarteten Label. Jede Rechnung erhält die Quelle `unavailable` und das Label
  **„Nicht einstufbar“**. Konfidenz gibt es dann keine.
- Die Export-Prüfung ist davon **nicht** betroffen (siehe [sync-und-aktionen.md](sync-und-aktionen.md)).

## Rangfolge der Quellen (`classify`)

`classify(invoice, history, cache, *, context_label, option_available)` nimmt die **erste**
zutreffende Quelle. Die Quelle wird in der Zeile ausgewiesen.

| Rang | Quelle (Anzeige) | Bedingung | Konfidenz für IT-Consulting | Detail |
|---|---|---|---|---|
| 1 | Empfänger („Empfänger“) | Feld „Empfänger“ am Dokument ist gesetzt (`recipient_label`) | `1,0`, wenn das Label dem Kontext entspricht (`same_label`); sonst `0,0` | Label des Empfängers |
| 2 | Korrespondent („Korrespondent 3/3“ bzw. „2/2“) | Korrespondent ist gesetzt und hat **mindestens zwei andere** entschiedene Rechnungen; alle zeigen in dieselbe Richtung | IT: `0,9` bei genau 2, `0,95` ab 3. Anderer Empfänger: `0,1` bei 2, `0,05` ab 3 | „n/n <Kontext>“ bzw. „n/n anderer Empfänger“ |
| 3 | KI („KI“) | Im Empfänger-Cache steht eine gültige IT-Wahrscheinlichkeit (`it_probability`) | der gespeicherte Wert | Begründung der KI (`reasoning`) |
| – | keine | keine der drei Quellen trifft zu | keine (`None`) | Anzeige „Nicht eingeschätzt“ |

### Was „entschieden“ heißt

Die Historie (`Repository.correspondent_context_history`) fasst alle Rechnungen mit gesetztem
Korrespondenten zusammen. Eine Rechnung zählt als entschieden, wenn:

- `recipient_label` gesetzt ist. Gleicht das Label dem Kontext (`same_label`), zählt sie als
  IT-Consulting, sonst als anderer Empfänger. Oder
- kein Empfänger gesetzt ist, aber der SevDesk-Status `exported` ist oder ein `confirmed`-Treffer
  besteht. Das zählt als IT-Consulting.

Rechnungen ohne Korrespondent gehen nicht in die Historie ein. Die gerade bewertete Rechnung wird
herausgerechnet, damit sie sich nicht selbst bestätigt.

### Widersprüchliche Historie

Enthält die Historie eines Korrespondenten **beide** Richtungen, wird die Quelle „Korrespondent“
übersprungen. Die nächste Quelle (KI) greift.

## Einstufungsbereiche (`context_bucket`)

Aus der Konfidenz entsteht der Bereich, nach dem die Filter arbeiten:

| Bereich | Anzeige | Bedingung |
|---|---|---|
| `it` | Kontext-Label, z. B. „IT-Consulting“ | Konfidenz ≥ `SEVDESK_CONTEXT_MIN_CONFIDENCE` (Standard 0,75) |
| `not_it` | „Nicht IT-Consulting“ | Konfidenz `0`; oder Quelle Empfänger bzw. Korrespondent mit Konfidenz unter 0,5 |
| `unsure` | „Unsicher“ | übrige Werte über 0 und unter der Schwelle (in der Praxis nur KI-Werte) |
| `unknown` | „Nicht eingeschätzt“ | keine Konfidenz |

Die Quelle `unavailable` (Option fehlt) erscheint als „Nicht einstufbar“. Der Bereich ist dann
`unknown`.

Die Schwelle gilt für den Filter „IT-Consulting ab Schwelle“ (`ctx=it`) und die Anzeige.

**Abweichung von der Spec:** Die Spec verlangt für Werte unter der Schwelle, aber über 0, die
Kennzeichnung „unsicher“. Der Code kennzeichnet die deterministischen Quellen mit Konfidenz unter
0,5 dagegen als „Nicht IT-Consulting“. Das folgt Design 3 (dort ist „not_it“ für diese Fälle
festgelegt). Siehe Abschnitt „Offene Punkte“.

## Berechnung beim Lesen (`build_rows`)

`build_rows(repo, invoices, *, context_label, threshold, option_available)` in
`app/invoice_overview.py` berechnet Einstufung, Abgleich und Exportsperren für die geladene Menge:

- **Eine** Historie-Abfrage für alle Rechnungen (`correspondent_context_history`). Die Aggregation
  nach Korrespondent läuft in Python über die Zeilen einer `SELECT`-Abfrage. Ein `GROUP BY` wird
  **nicht** verwendet (Abweichung von Design 3).
- **Eine** Abfrage der Empfänger-Caches für die Paperless-IDs (`get_recipient_caches`).
- Keine Paperless-, SevDesk- oder KI-Aufrufe. Die KI wird nur im Batch-Lauf oder beim
  Einzelvorschlag aufgerufen, nicht beim Anzeigen.

Die Filter „IT-Consulting“ (`ctx=it`), „Nicht exportiert“ (`open=1`) und „Mögliche Dublette“
(`dup=1`) laufen in Python über diese Menge (`apply_filters`). Die Obergrenze für gefilterte
Ansichten liegt deshalb höher, siehe [rechnungs-ui.md](rechnungs-ui.md).

## KI-Wahrscheinlichkeit als Quelle 3

- Wert: `document_recipients.it_probability` (siehe [empfaenger-zuordnung.md](empfaenger-zuordnung.md)).
- Gültig ist eine Zahl von 0 bis 1. Alles andere wird zu `NULL` und damit zu „nicht
  eingeschätzt“: Strings, Wahrheitswerte, NaN und Werte außerhalb des Bereichs. Der
  Empfänger-Vorschlag bleibt dabei gültig.
- Die Einschätzung kommt im selben KI-Aufruf wie der Empfänger-Vorschlag, also ohne zweiten Aufruf.

## Anzeige

`partials/invoice_rows.html` zeigt je Rechnung:

- Badge mit dem Bereichslabel (Kontext-Label, „Nicht IT-Consulting“, „Unsicher“, „Nicht
  eingeschätzt“ oder „Nicht einstufbar“),
- Konfidenz in Prozent und die Quelle („Empfänger“, „Korrespondent n/n“, „KI“).

`partials/invoice_sections.html` zeigt zusätzlich eine Begründung je Quelle:

- Empfänger: „Am Dokument ist der Empfänger „…“ gesetzt.“
- Korrespondent: „Frühere Rechnungen dieses Korrespondenten — …“
- KI: „Einschätzung der KI — …“
- Keine Quelle: „Keine Quelle liefert eine Einschätzung …“

## Konfiguration

| ENV | Default | Wirkung |
|---|---|---|
| `SEVDESK_CONTEXT_LABEL` | `IT-Consulting` | Label der Option; Teil des KI-Prompts; Vergleich in Quelle 1 und 2 (ohne Randleerraum und Groß-/Kleinschreibung) |
| `SEVDESK_CONTEXT_MIN_CONFIDENCE` | `0.75` | Schwelle für den Bereich `it` (größer 0 bis 1; Startprüfung) |

Der KI-Prompt bekommt das Label beim Start fest (`RecipientSuggester`, Konstruktor
`context_label`). Dadurch bleibt das Prompt-Caching erhalten. Die Details stehen in
[konfiguration.md](../konfiguration.md).

## Fallstricke

- **Ein Label-Vergleich, überall gleich.** Einstufung (Quelle 1), Historie, Exportsperre
  (`export_blockers`, Rückfrage „anderer Empfänger“), Optionsprüfung
  (`recipient_option_available`) und die Suche der Option beim Rückschrieb nutzen alle `same_label`.
  Ein Empfänger „it-consulting“ zählt damit als Kontext, in der Einstufung wie beim Export.
  Das konfigurierte Label (`SEVDESK_CONTEXT_LABEL`) wird beim Laden um Randleerraum bereinigt.
- **Leeres Label:** `RecipientSuggester` übernimmt das Label mit `or None`. Ein leeres Label
  lässt das Feld `it_consulting_probability` aus dem KI-Aufruf weg. Die Pflichtprüfung
  (`SEVDESK_CONTEXT_LABEL` nicht leer) gilt nur bei `FEATURE_SEVDESK_EXPORT=true`.
- **Historie wirkt rückwirkend.** Eine Entscheidung an einer Rechnung kann die Einstufung
  anderer Rechnungen desselben Korrespondenten ändern. Das ist beabsichtigt (siehe oben).
- **Kosten:** Die zusätzliche Wahrscheinlichkeit erhöht den Tokenverbrauch je KI-Aufruf
  (Design-Risiko). Einmalig kommt ein Nachlauf über bereits bewertete Dokumente hinzu.
- **Die Schwelle begrenzt nur die Anzeige.** Ein Export wird durch die Einstufung weder
  ausgelöst noch verhindert. Maßgeblich sind die Sperren und Rückfragen in
  [sync-und-aktionen.md](sync-und-aktionen.md).

## Offene Punkte

- Ob die Gewichte und die Schwelle 0,75 im echten Bestand passen, zeigt erst die Abnahme auf dem
  NAS (Task 9.1). Die Stichprobe von zehn Rechnungen steht aus.
