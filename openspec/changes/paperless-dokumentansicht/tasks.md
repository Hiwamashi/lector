# Tasks

Testbefehle: `uv run pytest`, `uv run ruff check .`. Nach Codeänderungen `graphify update .`.
Aufgaben mit **(manuell)** führt der Anwender aus; der Agent bereitet sie vor und hakt erst
nach Rückmeldung ab.

## 1. Paperless-Client und Namens-Cache

- [x] 1.1 `app/paperless.py`: `PaperlessDocument` um `added`, `archive_serial_number`, `page_count` (optional) erweitern und in `_to_document` mappen; neue Methoden `document_type_map()`, `tag_map()`, `custom_field_map()` (ID→Name) und `get_note_entries(doc_id)` (Text, Verfasser, Zeitpunkt). Prüfen: Tests mit `httpx.MockTransport` für jede Methode, inklusive Notiz ohne Verfasser und Dokument ohne ASN.
- [x] 1.2 `app/paperless_sync.py`: Namens-Cache für Korrespondenten, Dokumenttypen, Tags und Felder mit 10 Minuten Lebensdauer (Design D4), bisheriges `_corr_map` darin aufnehmen; bei unbekannter ID einmal die betroffene Liste neu laden, sonst `#<id>`. Prüfen: Test mit Fake-Client zählt Abrufe (zweiter Zugriff ohne HTTP, nach Ablauf bzw. unbekannter ID genau ein Neuladen); bestehende Tests in `tests/test_recipients.py` bleiben grün.
- [x] 1.3 `PaperlessSync.view_enabled` (URL + Token), `load_document_view(paperless_id)` (Dokument und Notizen parallel, Namen aufgelöst, Rechnung aus dem Repo per `paperless_id`, Empfänger-Feld und aktueller Wert) und `fetch_document_preview(paperless_id)`. Prüfen: Tests für Dokument mit allen Angaben, ohne Korrespondent, unbekannte ID (404 von Paperless → `None`) und Paperless-Fehler (Ausnahme läuft durch).

## 2. Routen

- [x] 2.1 Vorschau-Hilfsfunktion aus `invoice_preview` herauslösen (Typprüfung, 415, 502, Frame-/CSP-Header, `Cache-Control: private, max-age=300`); neue Route `GET /paperless/{paperless_id:int}/preview`, `/invoices/{id}/preview` delegiert. Prüfen: bestehende Vorschau-Tests in `tests/test_web_auth.py` grün, dazu neue Tests für die neue Route (PDF, aktiver Inhalt 415, Header in beiden Auth-Modi).
- [x] 2.2 Routen `GET /paperless/{paperless_id:int}` (Seite) und `GET /fragment/paperless/{paperless_id:int}` (Fragment, `?ask=1` durchreichen); 404 ohne `view_enabled` und bei unbekannter ID, Paperless-Fehler über den bestehenden `httpx.HTTPError`-Handler. Prüfen: `tests/test_web.py` deckt Seite, Fragment, 404-Fälle und Hinweis bei nicht erreichbarem Paperless ab; `test_no_route_is_shadowed_by_a_parametrised_one` bleibt grün.
- [x] 2.3 `/invoices/{id}` antwortet mit 303 auf `/paperless/{paperless_id}`, `/fragment/invoices/{id}` liefert das neue Fragment, unbekannte Rechnung bleibt 404. Prüfen: Tests für Weiterleitung, Fragment und 404; bestehende Detailtests auf die neue Adresse umgestellt und grün.
- [x] 2.4 Leisten-Antwort der Aktionen (Design D6): bei Kopf `X-Lector-Panel: 1` leiten `/invoices/{id}/giro`, `/export`, `/dismiss`, `/matches/{voucher_id}`, `/paid`, `/empfaenger/{paperless_id}` und `/empfaenger/{paperless_id}/suggest` auf `/fragment/paperless/{paperless_id}` (bei Rückfrage mit `?ask=1`) statt auf ihre bisherigen Ziele. Prüfen: parametrisierter Test je Route mit und ohne Kopf prüft das Redirect-Ziel; Herkunftsprüfung bei `AUTH_MODE=paperless` greift auch mit Kopf.

## 3. Templates

- [x] 3.1 Rechnungsabschnitte aus `partials/invoice_detail_body.html` in `partials/invoice_sections.html` herauslösen; neues `partials/paperless_doc_body.html` (Kopf mit Titel und „In Paperless öffnen ↗“, Vorschau, Metadaten mit „—“ für Leeres, Notizen, Empfänger-Formular, Rechnungsbereich nur bei Rechnung und `sync.enabled`) und Seite `paperless_doc.html`. Formulare in der Ansicht tragen `data-panel-form`. Prüfen: Tests prüfen, dass Tags ohne Bedienelement erscheinen, der Rechnungsbereich bei Nicht-Rechnungen fehlt und der Empfänger auch dort bearbeitbar ist.
- [x] 3.2 Listen-Templates: `<aside id="panel">` auf Rechnungen, Empfänger und Dokumente; Zeilen mit `data-panel-url`/`data-page-url`, Rechnungszeilen zusätzlich `data-paperless-id`; Empfänger-Titel wird Link auf `/paperless/{id}`; Spalten, die die Leiste zeigt, mit `col-secondary`; Details-Spalte der Rechnungsliste entfällt. Bei `?doc=` rendert der Server die Leiste gleich mit und markiert die Zeile mit `aria-current`. Prüfen: Tests für jede Liste mit und ohne `?doc=`, Titel-Links funktionieren ohne JS (zeigen auf die Seite).
- [x] 3.3 Dokumente-Liste: `?doc=<lector-id>` öffnet `partials/detail_body.html` in der Leiste mit `data-fragment="/fragment/documents/{id}"`. Prüfen: Test rendert Startseite mit `?doc=` und findet Stammdaten und Verlauf in `#panel`.

## 4. Seitenleiste im Browser

- [x] 4.1 `app/static/app.js`: Klick-Delegation auf Zeilen/Titel mit `data-panel-url` (Modifikatortasten und Mittelklick öffnen weiter normal), Laden über `loadFragment` mit `AbortController` beim schnellen Wechsel, `history.pushState` mit `?doc=`, `popstate`, Markierung `aria-current`, Schließen-Knopf; Fokus auf Leistenüberschrift nach Laden. Prüfen: Tests in `tests/test_app_js.py` (bestehendes Muster) für die neuen Handler; **(manuell)** Öffnen, Wechseln, Zurück-Taste und Neuladen in Chrome. (manuelle Prüfung offen)
- [x] 4.2 Leisten-Formulare per `fetch` mit `X-Requested-With: fetch` und `X-Lector-Panel: 1` senden, Antwort-Fragment in die Leiste setzen, danach Listen-Refresh; Fehler als Hinweis in der Leiste, Inhalt bleibt. Prüfen: `tests/test_app_js.py`; **(manuell)** „überwiesen“ setzen und Empfänger ändern aus der Leiste, Zeile aktualisiert sich ohne Neuladen. (manuelle Prüfung offen)
- [x] 4.3 Tastatur (Design D8): ↑/↓, j/k, Esc, Enter; ignoriert Eingabefelder, Auswahllisten, `contenteditable`, die Vorschau und Modifikatortasten; Fokus nach Esc auf die zuletzt geöffnete Zeile. Prüfen: `tests/test_app_js.py`; **(manuell)** mit Tastatur durch zehn Empfänger-Dokumente blättern, im Betragsfeld „j“ tippen. (manuelle Prüfung offen)
- [x] 4.4 SSE: `refreshFragment` lädt `#panel[data-fragment]` mit, `currentDetail()` erkennt `/paperless/(\d+)` und den Leisten-Zustand. Prüfen: `tests/test_app_js.py`; **(manuell)** Dokument in der Leiste geöffnet lassen, während ein Scan verarbeitet wird, Verlauf läuft mit. (manuelle Prüfung offen)

## 5. Gestaltung

- [x] 5.1 `app/static/app.css`: Grid-Layout `.has-panel` ab 1280 px mit sticky Leiste, Überlagerung zwischen 720 und 1280 px, Vollbild darunter (Design D7); `col-secondary` unter `.has-panel` ausblenden; Vorschau in der Leiste füllt die Höhe; Zeilenmarkierung `aria-current`; reduced-motion beachten. Prüfen: **(manuell, mit Agent)** Vorschau per file:// bzw. auf dem NAS bei 1800, 1024 und 390 px: kein waagerechtes Scrollen, Titel und Datum sichtbar; Kontrast hell/dunkel nach WCAG AA.
- [x] 5.2 `DESIGN.md`: Tokens `panel-surface`, `panel-border`, `row-current` und Abschnitt „Seitenleiste“ (Stufen, Tastatur, Fokus). Prüfen: Impeccable-Detector ohne neue Befunde.

## 6. Dokumentation und Abschluss

- [x] 6.1 `PRODUCT.md`: Positionierung und Prinzip 3 auf „Lector als Alltags-UI, Paperless als Backend für Details“ umstellen; Grenze lesend/bearbeitend festhalten; Hinweis, dass die Ansicht jedes für Lectors Token lesbare Dokument zeigt. Prüfen: Abschnitt liest sich ohne Widerspruch zu `CLAUDE.md`-Kernprinzip, Widerspruch ggf. dort mit nachgezogen.
- [x] 6.2 `feature-documentation/paperless-integration/dokumentansicht.md` neu (Routen, Freischaltung, Leiste, Tastatur, Sicherheit des Proxys), `feature-documentation/ui-erscheinungsbild.md` ergänzen, `prd/PROGRESS.md` nachziehen. Prüfen: Dateien vorhanden, Links zwischen den Dokumenten stimmen.
- [x] 6.3 Gesamtprüfung: `uv run pytest` und `uv run ruff check .` grün, `graphify update .` gelaufen, Token-Log-Zeile angehängt. Prüfen: Befehlsausgaben ohne Fehler.
- [ ] 6.4 **(manuell)** Abnahme auf dem NAS nach Rollout: Rechnungen, Empfänger und Dokumente je fünf Einträge per Leiste und Tastatur durchgehen, je eine Aktion aus der Leiste, alter Rechnungslink, Handy-Ansicht. Danach `/opsx:archive`.
