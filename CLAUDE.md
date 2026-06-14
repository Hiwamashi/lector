# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Projektstatus

Dieses Repository enthält bislang **nur** das PRD (`prd/PRD_Lector.md`) und die LICENSE — **noch keinen Quellcode**. Die folgende Architektur ist daher die im PRD festgelegte Soll-Vorgabe, nach der die Implementierung erfolgt. Das PRD ist die maßgebliche Quelle; bei Unklarheiten dort nachlesen.

## Was ist Lector?

Lector ist ein lokaler Backend-Service (zusätzlicher Docker-Container im bestehenden Paperless-ngx-Compose-Stack). Er überwacht einen Eingangsordner, veredelt eingehende Dokumente (Bilder, PDF, TIFF) per Cloud-OCR (Google Document AI) zu durchsuchbaren „Sandwich"-PDFs und legt sie für den automatischen Import in Paperless-ngx ab. E-Rechnungen (XRechnung, ZUGFeRD/Factur-X) werden deterministisch erkannt und **unverändert** durchgereicht.

**Kernprinzip:** Lector schiebt sich als reiner Veredelungsschritt **vor** Paperless, ersetzt es nicht. Es kümmert sich ausschließlich um Texterkennung und Bildaufbereitung. Klassifizierung, Tags und Korrespondenten bleiben vollständig bei Paperless.

## Geplanter Tech-Stack

- **Sprache/Runtime:** Python 3.12+
- **Web-Framework:** FastAPI + uvicorn (ein Prozess für Web-UI, interne API und Hintergrund-Worker)
- **UI:** Jinja2-Templates + HTMX + Tailwind (Standalone-CLI, **kein** Node-Buildchain)
- **Live-Status:** Server-Sent Events (SSE)
- **Bildvorverarbeitung:** OpenCV + Pillow (Deskew, Auto-Rotate, Kontrast/Graustufen)
- **PDF-Handling:** pypdf / pikepdf (Split/Merge, eingebettete Dateien) + reportlab (Textlayer)
- **OCR-Engine:** google-cloud-documentai, hinter einem austauschbaren Adapter-Interface
- **Watch-Folder:** watchdog
- **Datenbank:** SQLite (WAL-Mode)
- **Deployment:** Docker, Service im bestehenden Paperless-Compose

## Architektur-Eckpunkte

- **Ein Container, ein Prozess:** FastAPI/uvicorn bedient Web-UI und interne API; ein asynchroner Hintergrund-Worker (asyncio-Task) überwacht den Watch-Folder und arbeitet die Queue **seriell** ab.
- **CPU vs. I/O:** CPU-lastige Schritte (OpenCV-Vorverarbeitung, PDF-Bau) laufen in einem Thread-/Process-Pool, damit das UI responsiv bleibt. Die Document-AI-Aufrufe sind netzwerk-I/O-gebunden.
- **OCR-Adapter-Interface:** Jeder OCR-Adapter kennt sein eigenes Seitenlimit und chunkt **intern**. Bildvorverarbeitung und Sandwich-PDF-Bau sind engine-**unabhängig** und liegen gemeinsam darüber. Spätere Engines (Cloud Vision, AWS Textract) docken über dasselbe Interface an.
- **Chunking:** Dokumente werden lokal in Blöcke von ≤ 15 Seiten zerlegt (Online-Limit von Document AI), blockweise verarbeitet und anschließend wieder zu **einem** Gesamt-PDF zusammengeführt — ohne Google-Cloud-Storage-Roundtrip.
- **Sandwich-PDF:** Vorverarbeitetes Originalbild als sichtbare Ebene + unsichtbarer, durchsuchbarer Textlayer aus den OCR-Token-/Bounding-Box-Daten.

### Verarbeitungs-Pipeline (Soll)

1. Neue Datei in `scan-in` → **Vollständigkeitsprüfung** (Dateigröße über ein Intervall stabil bzw. `.tmp`/`.part`-Rename abwarten), um Teilverarbeitung großer Scans zu vermeiden.
2. DB-Eintrag `status=pending`, Format-/Typ-Erkennung.
3. **E-Rechnung** (deterministisch, keine KI):
   - XRechnung: `.xml` mit Root `Invoice` (UBL) bzw. `CrossIndustryInvoice` (UN/CEFACT CII), EN-16931-Namespace.
   - ZUGFeRD/Factur-X: PDF mit eingebetteter Datei (`factur-x.xml`, `zugferd-invoice.xml`, `ZUGFeRD-invoice.xml`, `xrechnung.xml`) bzw. XMP-Metadaten.
   - → **unverändert** nach `consume` kopieren, Original nach `processed`, `status=skipped_erechnung`. **Keine** OCR, **keine** Umbenennung, **keine** Paperless-Tags.
4. **OCR-Weg:** Seiten extrahieren → Bildvorverarbeitung pro Seite → Chunking → pro Block Document AI Online-Process → `processed_pages` aktualisieren → Sandwich-PDF bauen → Ergebnis nach `consume` (UID/GID 1000), Original nach `processed`, `status=done`.
5. **Fehler:** `attempt_count < 3` → `next_retry_at = now + 15 min`, `status=pending`. Sonst → Original nach `error`, `status=failed` (kein manueller Retry-Button).

### Datei-Lifecycle & Jobs

- Eingang `scan-in` → Erfolg: Original nach `processed` (auto-Löschung nach 30 Tagen) → endgültiger Fehler: Original nach `error` (bleibt liegen). Ergebnis-PDF stets nach `consume`.
- **Auto-Retry:** nach 15 min, max. 3 Versuche.
- **Retention-Job:** täglich, löscht Dateien in `processed` älter als 30 Tage. DB-Einträge bleiben erhalten.

### Datenmodell (SQLite)

- `documents`: `id, original_filename, source_path, file_hash, status, doc_type, ocr_engine, total_pages, processed_pages, attempt_count, next_retry_at, error_message, output_path, created_at, started_at, finished_at`
  - `status`: `pending | processing | done | skipped_erechnung | failed`
  - `doc_type`: `pdf | tiff | image | erechnung_xml | erechnung_pdf`
- `document_events` (1:n Verlaufs-Log): `id, document_id, timestamp, event_type, message`
  - `event_type`: `detected | preprocessing | ocr_chunk | built_pdf | moved_to_consume | retry_scheduled | skipped_erechnung | failed | done`

## Konfiguration (ENV)

Sämtliche Einstellungen laufen über Umgebungsvariablen — keine Config-Dateien für Laufzeitparameter. Wichtige Variablen:
`OCR_PROVIDER`, `GCP_PROJECT_ID`, `DOCAI_LOCATION` (`eu`), `DOCAI_PROCESSOR_ID`, `GOOGLE_APPLICATION_CREDENTIALS`, `WATCH_DIR`, `CONSUME_DIR`, `PROCESSED_DIR`, `ERROR_DIR`, `DB_PATH`, `PROCESSED_RETENTION_DAYS`, `RETRY_DELAY_MINUTES`, `RETRY_MAX`, `CHUNK_SIZE_PAGES`, `PREPROCESS_DESKEW`, `PREPROCESS_AUTOROTATE`, `PREPROCESS_CONTRAST`, `TZ`, `PUID`, `PGID`.

## Wichtige Vorgaben & Fallstricke

- **Paperless muss `PAPERLESS_OCR_MODE: skip` setzen** (am `webserver`-Service), sonst überschreibt Tesseract den eingebetteten Document-AI-Textlayer.
- **Ausgabe-Eigentümerschaft:** Ergebnis-PDFs nach `consume` mit UID/GID **1000** schreiben (geteilter Ordner mit Paperless).
- **Keine Authentifizierung** (Betrieb ausschließlich im LAN, Einzelnutzer).
- **Explizit ausgeschlossen:** inhaltliche Datenextraktion/Klassifizierung/Tags (Aufgabe von Paperless), manueller Datei-Upload, eigenes Scannen, Cloud-Anbindung außer der OCR-Engine.
- **E-Rechnungs-Bypass ist deterministisch** — niemals per KI/OCR raten.

## Offene Fragen (vor Implementierung klären)

1. Vollständigkeitserkennung im Watch-Folder: Größenstabilität vs. `.tmp`/`.part`-Rename — abhängig davon, wie Dateien auf der NAS in `scan-in` landen.
2. Bereits durchsuchbare PDFs: überspringen und durchreichen oder stets durch Document AI laufen lassen?
3. Throttling gegen Document-AI-Quota („pages per minute") bei großen Dokumenten/Stoßlast.

---

# Zwingende Regeln (1:1 aus dem PRD übernommen)

## Dokumentations-Richtlinie

> Im Ordner `feature-documentation/` müssen alle neuen Funktionen und Features sowie deren Anpassungen in einzelnen `.md`-Dateien im Markdown-Format dokumentiert werden. Pro Funktion und Markdown eine Datei. Sollte ein Feature aus mehreren Funktionen bestehen, dürfen Unterordner pro Feature angelegt werden. Diese Dokumentation dient vor allem anderen KI-Coding-Agenten zum besseren Verständnis der Codebase.

> Der aktuelle Entwicklungsfortschritt ist fortlaufend neben dem PRD zu dokumentieren — z.B. in einer `PROGRESS.md` neben dem PRD. Dort wird festgehalten, welche MVP-Features bereits umgesetzt sind, welche in Arbeit sind und welche noch ausstehen. So haben alle Beteiligten (Mensch und KI-Agent) jederzeit einen aktuellen Überblick über den Stand der Entwicklung.

## Token-Protokoll (nach jeder Session)

Am Ende JEDER Session hängst du genau eine Zeile an die Datei
`prd/token-log.csv` an. Lege den Ordner `prd/` und die Datei mit Header an,
falls sie noch nicht existieren.

Header (nur einmalig):
`datum;uhrzeit;session_id;modell;input_tokens;output_tokens;tokens_gesamt;geschaetzt;thema`

Pro Session eine Zeile, z. B.:
`2026-06-08;14:32;<session>;<modell>;12000;3400;15400;ja;"Token-Protokoll einrichten"`

Regeln:
- Spalte `geschaetzt` = "ja", wenn keine exakten Zähler verfügbar sind (Standardfall),
  "nein" nur bei belegbaren Werten.
- Semikolon als Trennzeichen (Excel-DE-freundlich), Thema in Anführungszeichen.
- Niemals bestehende Zeilen ändern – nur anhängen.
- Wenn kein verlässlicher Tokenwert bekannt ist: Wert leer lassen statt zu raten
  und `geschaetzt=ja` setzen.

## Graphify — Codebase Knowledge Graph

Dieses Projekt nutzt [Graphify](https://github.com/safishamsi/graphify/tree/v8)
zur strukturierten Codebase-Analyse.

### Setup (einmalig pro Repo)

Wenn `graphify-out/` nicht existiert oder `graphify-out/graph.json` fehlt:

1. Prüfe, ob `graphify` als CLI verfügbar ist (`graphify --version`).
   Falls nicht: `uv tool install graphifyy`
2. Prüfe, ob der Graphify-Skill registriert ist (`~/.claude/skills/graphify/`).
   Falls nicht: `graphify install`
3. Erkenne relevante Dateitypen im Repo und installiere passende Extras:
   - `.pdf` vorhanden → `uv tool install "graphifyy[pdf]"`
   - `.docx` / `.xlsx` vorhanden → `uv tool install "graphifyy[office]"`
   - `.sql` vorhanden → `uv tool install "graphifyy[sql]"`
   - `.mp4` / `.mov` / `.mp3` vorhanden → `uv tool install "graphifyy[video]"`
   - Im Zweifel: `uv tool install "graphifyy[all]"`
4. Baue den Graphen: `/graphify .`
5. Registriere im Global Graph: `graphify global add graphify-out/graph.json --as <repo-name>`
   Verwende den Verzeichnisnamen als `<repo-name>`.
6. Generiere die Architekturübersicht: `graphify export callflow-html`
7. Registriere Graphify für dieses Repo: `graphify claude install`
8. **Nur nach expliziter Freigabe durch den Benutzer:**
   Schlage `graphify hook install` vor (auto-rebuild bei git commit).
   Erkläre kurz, was der Hook tut, und warte auf Bestätigung.

### Nutzung

- Lies `graphify-out/GRAPH_REPORT.md` bevor du Architektur- oder
  Abhängigkeitsfragen beantwortest.
- Nutze `graphify query "<frage>"` für Strukturfragen, bevor du
  manuell Dateien durchsuchst.
- Nutze `graphify explain "<Knoten>"` um einzelne Konzepte zu verstehen.
- Nutze `graphify path "<A>" "<B>"` um Verbindungen zwischen
  Komponenten zu finden.
- Bei `AMBIGUOUS`-Kanten im Graphen: Quellcode gegenchecken.

### Aktualisierung

- Nach größeren Refactorings: `/graphify . --force`
- Nach Änderungen an Docs/PDFs: `/graphify . --update`
- Callflow-Export aktualisieren: `graphify export callflow-html`

## Subagents proaktiv nutzen

- Prüfe bei jeder nicht-trivialen Aufgabe, ob sie sich für die Delegation an einen Subagent (Agent/Task-Tool) eignet – insbesondere bei:
  - breiter Codebase-Recherche (mehr als ~3 Suchanfragen)
  - unabhängigen, parallelisierbaren Teilaufgaben
  - Aufgaben, die viel Kontext (Logs, große Dateien) erzeugen würden
- Wenn eine Delegation sinnvoll ist, schlage sie **aktiv vor**, bevor du selbst loslegst: nenne kurz den Subagent-Typ und warum.
- Bei mehreren unabhängigen Teilaufgaben: schlage vor, sie parallel über mehrere Subagents laufen zu lassen.

### Beispielhafte Subagent-Rollen

Die folgenden Rollen sind **nur Beispiele** zur Orientierung, keine abschließende Liste. Leite passende Subagents jeweils aus der konkreten Aufgabe ab:

- **Dokumentations-Experte** – Erstellt/aktualisiert Doku (z.B. `feature-documentation/`, README, Changelog). Vorschlagen, wenn neue Funktionen ergänzt oder bestehende geändert wurden und die Doku nachgezogen werden muss.
- **Code-Reviewer** – Prüft Diffs auf Bugs, Sicherheitslücken (OWASP), Performance und Stil. Vorschlagen nach größeren Änderungen oder vor einem Commit/PR. **Prüfe aber zuerst, ob bereits Hooks, Review-Gates oder Review-Skills (z.B. pre-commit-Hooks, CI-Checks, ein `/code-review`-Skill oder ein konfiguriertes Stop-Review-Gate) vorhanden sind** – wenn ja, nutze bzw. verweise auf diese, statt einen zusätzlichen Review-Subagent doppelt einzusetzen.
- **Recherche-/Explore-Experte** – Durchsucht die Codebase oder externe Quellen und liefert eine verdichtete Zusammenfassung. Vorschlagen bei "Wo ist X?", "Wie hängt Y zusammen?" oder breiter Architektur-Recherche.
- **Test-/Verifikations-Experte** – Führt Tests, Builds oder Linting aus und meldet nur das Ergebnis zurück. Vorschlagen, bevor eine Änderung als fertig gemeldet wird.
- **Refactoring-Experte** – Nimmt mechanische Umbenennungen/Umstrukturierungen über viele Dateien vor. Vorschlagen bei wiederkehrenden Änderungen an vielen Stellen.
- **Datenbank-/Migrations-Experte** – Prüft Schema-Änderungen und Migrationen auf Sicherheit. Vorschlagen bei Eingriffen in DB-Struktur oder Migrationen.

Diese Rollen kannst du entweder ad-hoc über das Agent/Task-Tool ansprechen oder als feste Subagents unter `~/.claude/agents/` bzw. `.claude/agents/` definieren (mit `use proactively` in der `description`).
