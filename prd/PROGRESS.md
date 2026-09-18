# Entwicklungsfortschritt — Lector

> Fortlaufend gepflegter Stand der MVP-Umsetzung (siehe `PRD_Lector.md`).
> Legende: ✅ umgesetzt · 🚧 in Arbeit · ⬜ offen

**Stand:** 2026-09-18

## Getroffene Entscheidungen (vormals offene Fragen)

1. **Watch-Folder-Vollständigkeit:** kombiniert — Rename aus `.tmp`/`.part`/`.crdownload` bevorzugt, Größenstabilität über N Sekunden als Fallback.
2. **Bereits durchsuchbare PDFs:** Es laufen **immer** alle PDFs durch Document AI (einheitliches Ergebnis).
3. **Document-AI-Throttling:** seitenbasiertes Rate-Limit im Worker (`DOCAI_MAX_PAGES_PER_MINUTE`).

## MVP-Features

| Feature | Status |
|---|---|
| Projektgerüst, ENV-Config | ✅ |
| SQLite-Historie (`documents`, `document_events`) | ✅ |
| Watch-Folder + Vollständigkeitsprüfung | ✅ |
| Serielle Verarbeitungs-Queue / Worker | ✅ |
| Format-Erkennung & Routing | ✅ |
| E-Rechnungs-Bypass (deterministisch) | ✅ |
| Bildvorverarbeitung (Deskew/Kontrast; Orientierung via Document AI) | ✅ |
| OCR-Adapter-Interface | ✅ |
| Document-AI-Adapter (Region eu) | ✅ |
| Chunking ≤15 Seiten | ✅ |
| Sandwich-PDF (Bild + Textlayer) | ✅ |
| Ablage nach consume (UID/GID 1000) | ✅ |
| Datei-Lifecycle (processed/error) | ✅ |
| Auto-Retry (15 min, max 3) | ✅ |
| Retention-Job (30 Tage) | ✅ |
| Web-UI Dashboard + Historie + Detail | ✅ |
| Live-Updates via SSE | ✅ |
| Docker / Compose-Integration | ✅ |

**MVP vollständig umgesetzt.** `ruff` sauber, Docker-Image baut und startet.
Feature-Doku unter `feature-documentation/`.

## Zusatz-Feature: Paperless-Integration (GiroCode & SevDesk) — entkoppelt

Unabhängig vom OCR-Veredelungspfad. Lector liest Rechnungen über den Paperless-Dokumententyp,
erzeugt GiroCodes und exportiert getaggte Belege nach SevDesk; Status wird ans Paperless-
Dokument zurückgeschrieben. Standardmäßig deaktiviert (`FEATURE_PAPERLESS_SYNC=false`).

| Feature | Status |
|---|---|
| Paperless-REST-Client (lesen/zurückschreiben, `app/paperless.py`) | ✅ |
| GiroCode-Extraktion E-Rechnung (UBL/CII) + OCR-Heuristik (`app/girocode.py`) | ✅ |
| EPC069-12-QR-Erzeugung (segno, SVG) | ✅ |
| SevDesk-Beleg-Upload (`app/sevdesk.py`) | ✅ |
| Periodischer Sync + UI-Aktionen (`app/paperless_sync.py`, Worker-Loop) | ✅ |
| Neue Tabellen `paperless_invoices` / `invoice_events` | ✅ |
| Rückschrieb: Custom Fields + Tags + Notiz (Auto-Anlage) | ✅ |
| Web-UI „Rechnungen" + GiroCode-Anzeige + Aktionen + SSE | ✅ |
| Rechnungs-UI: Dokumentdatum, sortierbare Spalten, Dokumentvorschau/-Sprung | ✅ |
| Empfänger-Zuordnung pro Dokument (Paperless select-Feld, `/empfaenger`) | ✅ |
| KI-Empfänger-Vorschlag (Anthropic, `app/recipient_llm.py`) — einzeln + Batch, Auto-Apply | ✅ |
| Tabelle `document_recipients` (KI-Vorschlag-Cache) | ✅ |
| Batch-Lauf: Menge wählbar, Retry mit Backoff, Fortschritt + Abbruch | ✅ |

129 Tests grün. `ruff` sauber. (Fix-Runde nach Schlussreview: leeres/unlesbares Mengenfeld
fällt auf die Vorbelegung statt auf das Maximum zurück, Start-Button bleibt bei einem
Paperless-Aussetzer nutzbar, SSE-Drossel greift auch über den Einzel-`rec:<id>`-Pfad,
Ausnahmen vor der Dokumentschleife und der leere Empfänger-Feld-Fall setzen `aborted_reason`
statt wortlos zu enden, Anzeige benennt „ohne gesetzten Empfänger" statt eine 1:1-Deckung mit
der Arbeitsmenge zu suggerieren, Batch-Task wird beim Shutdown abgebrochen statt auf der
geschlossenen DB-Verbindung weiterzulaufen, `retry-after` ist auf 60 s gedeckelt, übersprungene
Dokumente zählen sichtbar und der offene Rest berücksichtigt auch abgebrochene Läufe.)
Feature-Doku unter `feature-documentation/paperless-integration/`
(neu: `rechnungs-ui.md`, `empfaenger-zuordnung.md`).
Empfänger-Feature **live gegen die Paperless-Instanz verifiziert**: select-Feld-Auflösung,
`custom_field_query`-Filter „ohne Empfänger" (1504 Dok.), Setzen/Leeren des Feldes (reversibel)
und KI-Vorschlag (korrekte Zuordnung bzw. „unbekannt") end-to-end getestet. Dokumentdatum (`created`) und Vorschau-Endpoint
(`/preview/`, liefert `application/pdf` mit `X-Frame-Options: SAMEORIGIN`) gegen die
Live-Paperless-Instanz verifiziert — daher wird die Vorschau über einen Lector-Proxy
ausgeliefert.

**End-to-End live verifiziert (2026-09-18):** gegen die echte Paperless-Instanz
(Token/URL/Dokumententyp-Name) und gegen ein echtes SevDesk-Konto (API-Token,
Systemversion 2.0 für E-Rechnungs-Belege).

## Zusatz-Feature: Image-Deployment über Scaleway Container Registry

Das Image wird nicht mehr auf dem NAS gebaut, sondern als Multi-Arch-Image
(amd64 + arm64) aus `rg.nl-ams.scw.cloud/krinke-dockersolutions` gezogen. Build
und Push laufen auf dem Entwicklungsrechner, der Rollout aufs NAS bleibt ein
getrennter manueller Schritt.

| Feature | Status |
|---|---|
| Push-Skript Multi-Arch amd64+arm64 als Manifest-Liste (`scripts/push-image.sh`) | ✅ |
| Tags `latest` + `git-<sha>`, Index nach dem Push verifiziert | ✅ |
| Gate: kein Push ohne Registry-Login | ✅ |
| Gate: kein Push aus schmutzigem Worktree (SHA-Tags reproduzierbar) | ✅ |
| Compose auf Registry-Image umgestellt, `build:` deaktiviert + Regressionstest | ✅ |
| arm64-Lauffähigkeit lokal belegt (Container gestartet, HTTP-Antwort) | ✅ |
| Rollout auf dem NAS (`compose pull` + `up -d`) | ✅ vom Anwender durchgeführt (2026-09-18) |

## Im Betrieb verifiziert (2026-09-18)

Alle zuvor offenen Verifikationspunkte sind vom Anwender geschlossen:

- **End-to-End mit echtem Document AI:** Der OCR-Weg läuft mit echten GCP-Credentials
  (`GCP_PROJECT_ID`, `DOCAI_PROCESSOR_ID`, Service-Account-JSON) — nicht mehr nur
  Fake-Adapter und E-Rechnungs-Bypass.
- **Registry-Deployment:** `docker compose pull lector && docker compose up -d lector`
  auf dem NAS (`Teams/Docker/paperless-ngx-stack`) ausgeführt, Dienst auf Port 8001 erreichbar.
- **Paperless & SevDesk:** Sync und Beleg-Upload gegen die produktiven Konten bestätigt.

## Bewusste Abweichungen vom PRD-Tech-Stack

- UI ohne HTMX/Tailwind-Laufzeit: serverseitiges Jinja2 + offline-CSS + Vanilla-JS-SSE
  (LAN-only, keine Cloud-/Node-Abhängigkeit). Funktional identisch (Live-Updates via SSE).
- `pypdfium2` ergänzt für PDF→Bild-Rasterung (keine System-Abhängigkeit).
- **Kein lokales Auto-Rotate** (PRD §3.1 nennt es als Vorverarbeitungsschritt): Die Heuristik
  über die Varianz der Zeilensummen kann 0° nicht von 180° (bzw. 90° nicht von 270°)
  unterscheiden — die Werte sind mathematisch identisch, die Entscheidung fiel nur über den
  Fließkomma-Rundungsfehler und drehte ~22 % korrekt ausgerichteter Seiten zufällig (oft auf
  den Kopf). Schritt entfernt; Orientierung übernimmt Document AI. `PREPROCESS_AUTOROTATE`
  entfällt. Siehe `feature-documentation/bildvorverarbeitung.md`.

## Nice-to-have (später)

- Weitere OCR-Adapter (Cloud Vision, AWS Textract) — Interface vorbereitet.
- Confidence-Score-Auswertung mit Qualitätswarnung im UI.
