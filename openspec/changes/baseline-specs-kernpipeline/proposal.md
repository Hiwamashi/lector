# Proposal

## Why

Lector läuft produktiv, aber `openspec/specs/` ist leer: Es gibt keine
maschinenlesbare Beschreibung dessen, was der Dienst zusichert. PRD und
`feature-documentation/` beschreiben **wie** gebaut wurde, nicht **was gelten
muss** — beide veralten lautlos, und keine der beiden kann ausdrücken, dass das
Verhalten von der Absicht abweicht.

Das ist jetzt relevant, weil eine Analyse der Kernpipeline mehrere Lücken
zutage gefördert hat, die alle dasselbe Muster haben: Sie scheitern still
(siehe „Bekannte Lücken"). Ohne festgeschriebenes Soll-Verhalten ist jede
dieser Lücken eine Einzelmeinung; mit Specs wird sie ein Delta.

## What Changes

Diese Change ändert **kein Verhalten**. Sie nimmt das heutige Ist-Verhalten der
Kernpipeline als Capabilities auf, damit künftige Änderungen dagegen als Delta
formuliert werden können.

- Fünf neue Capabilities für den OCR-Veredelungsdienst (Phase 1), jeweils
  **as-built**: Die Requirements beschreiben, was der Code heute tatsächlich
  tut — nicht, was wünschenswert wäre.
- Kein `design.md` und kein `tasks.md`: Es wird nichts implementiert.
- Keine Änderung an `feature-documentation/`. Die bleibt bestehen und behält
  ihre Aufgabe (erklärend, implementierungsnah); die Specs übernehmen die
  verhaltensbindende Rolle.

**Bewusst as-built statt Soll:** Eine Spec-Sammlung, gegen die der Code ab Tag
eins rot validiert, wird nicht gepflegt. Die Basis bildet die Wahrheit ab; die
bekannten Abweichungen stehen unten namentlich und werden je eigene Change.

## Capabilities

### New Capabilities

- `dokumenteneingang`: Überwachung des Watch-Folders, Vollständigkeitserkennung
  neuer Dateien (Rename aus `.tmp`/`.part`/`.crdownload` bzw. Größenstabilität),
  Aufnahme in die Historie.
- `format-routing`: Deterministische Format- und Typerkennung sowie der
  E-Rechnungs-Bypass (XRechnung UBL/CII, ZUGFeRD/Factur-X) ohne KI oder OCR.
- `ocr-veredelung`: Seitenextraktion, Bildvorverarbeitung, Chunking auf das
  Online-Limit der OCR-Engine, Aufruf über das Adapter-Interface und Bau des
  durchsuchbaren Sandwich-PDFs.
- `verarbeitungs-lebenszyklus`: Serielle Queue, Statusübergänge, Auto-Retry,
  seitenbasiertes Rate-Limit, Ablage nach `consume`/`processed`/`error`,
  Eigentümerschaft der Ausgabe und Retention.
- `verarbeitungs-historie`: Persistierter Verlauf (`documents`,
  `document_events`), Weboberfläche und Live-Aktualisierung via SSE.

### Modified Capabilities

Keine — `openspec/specs/` ist leer, es gibt nichts zu ändern.

## Impact

**Betroffen:** ausschließlich `openspec/`. Kein Produktionscode, keine
Abhängigkeiten, keine API, kein Deployment.

**Nicht in dieser Change (Phase 2):** Die Paperless-Integration
(`FEATURE_PAPERLESS_SYNC`) — GiroCode, SevDesk-Export und Empfänger-Zuordnung.
Sie ist vom Veredelungspfad entkoppelt, ist inhaltlich eher drei Capabilities
als eine, und wird als eigene Change aufgenommen.

**Nachgelagert:** Nach `openspec sync`/`archive` entstehen die Dateien unter
`openspec/specs/<capability>/spec.md`. Das ist ein getrennter Schritt.

## Hinweis zur Validierung

Die Specs sind auf Deutsch verfasst und verwenden die deutschen Normbegriffe `MUSS`,
`MÜSSEN` und `DARF (NICHT)`. `openspec validate` läuft damit grün; `openspec validate
--strict` meldet je Requirement eine Warnung, weil es die englischen Token `SHALL`/`MUST`
sucht — laut eigener Meldung eine „best practice for English specs".

Das ist eine bewusste Abweichung, kein offener Mangel: Die Projektsprache ist Deutsch, und
eine Umstellung auf englische Schlüsselwörter in deutschen Sätzen würde die Lesbarkeit für
den einzigen Zweck einer Heuristik opfern. Wer künftig `--strict` in eine CI hängt, muss
diese Warnklasse ausnehmen — nicht die Specs umschreiben.

## Bekannte Lücken (je eigene Folge-Change)

Diese Abweichungen sind belegt und beim Schreiben der Specs bewusst **nicht**
in die Requirements aufgenommen worden — die Basis beschreibt das Ist. Jede
wird eine eigene Change, die das betroffene Requirement modifiziert:

| Lücke | Betroffene Capability | Fundstelle | Status |
|---|---|---|---|
| Nach Prozessneustart bleibt ein Dokument in `processing` dauerhaft liegen — kein Retry, kein `failed` | `verarbeitungs-lebenszyklus` | `app/pipeline.py:101` vs. `app/repository.py:289` | ✅ geschlossen durch `recovery-unterbrochener-verarbeitung` |
| Keine Obergrenze für Seiten pro Dokument und kein Kostenbudget vor dem OCR-Aufruf | `ocr-veredelung` | `app/pipeline.py:42` | ✅ Obergrenze geschlossen durch `seitenobergrenze-mit-freigabe`; ein kumulatives Kostenbudget bleibt bewusst offen |
| Teilergebnisse bereits verarbeiteter Chunks werden bei einem Fehler verworfen; der Retry bezahlt sie erneut | `ocr-veredelung` | `app/ocr/documentai.py:116` | ✅ geschlossen durch `chunk-teilergebnisse-bewahren` |
| Fehler werden nicht nach transient/permanent unterschieden; ein dauerhaft defektes Dokument verbraucht alle Versuche | `verarbeitungs-lebenszyklus` | `app/pipeline.py:71-90,116` | offen |
| Fehlende bzw. falsche Pflicht-ENV wird nicht beim Start abgewiesen, sondern erst beim ersten Dokument | `verarbeitungs-lebenszyklus` | `app/config.py:12-116` | ✅ geschlossen durch `startvalidierung-und-healthcheck` |
| `/healthz` meldet unbedingt `ok`; kein `HEALTHCHECK` in Dockerfile oder Compose | `verarbeitungs-historie` | `app/main.py:231` | ✅ geschlossen durch `startvalidierung-und-healthcheck` |
| Eingebettete E-Rechnungen mit Dateinamen außerhalb der festen Liste werden nicht erkannt | `format-routing` | `app/detection.py:28-33` | offen |
| Confidence-Werte werden von der Engine geliefert, aber nach dem PDF-Bau verworfen | `ocr-veredelung` | `app/ocr/documentai.py:71`, `app/models.py:173` | offen |
| Log-Level ist nicht über ENV steuerbar, sondern fest auf `INFO` verdrahtet — entgegen der Vorgabe, dass alle Laufzeitparameter über Umgebungsvariablen laufen | `verarbeitungs-lebenszyklus` | `app/main.py:41` | offen |
