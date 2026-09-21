# Konfiguration (ENV)

**Modul:** `app/config.py` · **Klasse:** `Settings` (pydantic-settings)

Sämtliche Einstellungen kommen ausschließlich aus Umgebungsvariablen (PRD §4.5). Für lokale
Entwicklung wird optional eine `.env` gelesen (`.env.example` als Vorlage).

## Wichtige Felder

| ENV | Default | Bedeutung |
|---|---|---|
| `OCR_PROVIDER` | `documentai` | Wahl des OCR-Adapters |
| `GCP_PROJECT_ID` / `DOCAI_PROCESSOR_ID` | — | Document-AI-Identität |
| `DOCAI_LOCATION` | `eu` | Region (Endpoint `<loc>-documentai.googleapis.com`) |
| `GOOGLE_APPLICATION_CREDENTIALS` | — | Pfad zur Service-Account-JSON |
| `WATCH_DIR`/`CONSUME_DIR`/`PROCESSED_DIR`/`ERROR_DIR`/`DB_PATH` | `/scan-in` … | Ordner & DB |
| `PROCESSED_RETENTION_DAYS` | 30 | Retention im processed-Ordner |
| `RETRY_DELAY_MINUTES` / `RETRY_MAX` | 15 / 3 | Auto-Retry |
| `CHUNK_SIZE_PAGES` | 15 | Obergrenze Block-Seiten (deckelt das Engine-Limit) |
| `MAX_PAGES_PER_DOCUMENT` | 100 | Obergrenze Seiten je Dokument vor dem OCR-Aufruf; darüber wird angehalten statt verarbeitet. 0 = aus. Siehe [seitenobergrenze.md](seitenobergrenze.md) |
| `CHUNK_CACHE_RETENTION_DAYS` | 7 | Verfallsfrist bewahrter OCR-Teilergebnisse; 0 = kein Verfallen (abgeschlossene Vorgaenge werden trotzdem geraeumt). Siehe [chunk-teilergebnisse.md](chunk-teilergebnisse.md) |
| `PREPROCESS_DESKEW`/`_CONTRAST` | true | Vorverarbeitungs-Flags (Orientierung übernimmt Document AI, kein Auto-Rotate) |
| `POLL_INTERVAL_SECONDS` | 2.0 | Scan-Frequenz des Watch-Folders |
| `STABILITY_WINDOW_SECONDS` | 6.0 | Größenstabilitäts-Fenster |
| `PARTIAL_SUFFIXES` | `.tmp,.part,.crdownload` | nie-fertig-Suffixe |
| `DOCAI_MAX_PAGES_PER_MINUTE` | 120 | Throttling gegen Quota |
| `PUID`/`PGID` | 1000 | Eigentümerschaft der Ausgabe in `consume` |

## Hinweise

- `get_settings()` ist `lru_cache`-gecached; in Tests `get_settings.cache_clear()` aufrufen,
  wenn ENV zur Laufzeit geändert wird.
- `Settings.ensure_dirs()` legt alle Arbeitsordner und das DB-Verzeichnis an.
- `partial_suffix_list` parst `PARTIAL_SUFFIXES` zu einer normalisierten Liste.

## Startvalidierung: was beim Start Pflicht ist

`validate_settings(settings) -> list[str]` (`app/config.py`) prüft ein bereits aufgebautes
`Settings`-Objekt und gibt alle Beanstandungen zurück (leere Liste = gültig). Sie wirft
selbst nicht und bricht nicht beim ersten Fund ab — Details zum Ablauf, zur Begründung und
zum Health-Endpunkt stehen in
[startvalidierung-und-healthcheck.md](startvalidierung-und-healthcheck.md); hier nur die
Tabelle, welche Angabe unter welcher Bedingung Pflicht ist.

| Prüfung | Bedingung |
|---|---|
| `OCR_PROVIDER` ist ein bekannter Wert | immer |
| `GCP_PROJECT_ID`, `DOCAI_PROCESSOR_ID`, `DOCAI_LOCATION` nicht leer | wenn die gewählte Engine sie braucht (deklariert in `_ENGINE_REQUIRED_FIELDS`) |
| `GOOGLE_APPLICATION_CREDENTIALS` gesetzt **und** lesbare Datei | wenn die gewählte Engine sie braucht |
| `RETRY_DELAY_MINUTES` mindestens 1 | immer |
| `PAPERLESS_URL`, `PAPERLESS_TOKEN` nicht leer | wenn `FEATURE_PAPERLESS_SYNC` gesetzt |
| `SEVDESK_API_TOKEN` nicht leer | wenn `FEATURE_SEVDESK_EXPORT` gesetzt |
| `ANTHROPIC_API_KEY` nicht leer | wenn `FEATURE_RECIPIENT_LLM` gesetzt |
| Arbeitsordner (`WATCH_DIR`, `CONSUME_DIR`, `PROCESSED_DIR`, `ERROR_DIR`) und Verzeichnis von `DB_PATH` beschreibbar | immer (eigene Schreibprobe, siehe unten) |

Der Provider-Vergleich ist **case-insensitiv**, konsistent zu `get_adapter()`
(`app/ocr/__init__.py`), das `OCR_PROVIDER` ebenfalls über `.lower()` auflöst.

### Was bewusst nicht geprüft wird

- **`CHUNK_SIZE_PAGES`:** `DocumentAiAdapter.page_limit` (`app/ocr/documentai.py:94-98`)
  klemmt den Wert per `min()` auf das Engine-Limit (`DOCAI_ONLINE_PAGE_LIMIT = 15`) und
  behandelt jeden Wert **≤ 0** als „nimm das Engine-Limit". Ein Wert von `0` heißt also
  **nicht** „kein Block wird verarbeitet", und ein Wert über 15 wird **nicht** von der
  Engine abgelehnt — es gibt nichts abzuwenden, deshalb keine Startprüfung dafür.
- **`MAX_PAGES_PER_DOCUMENT`, `PROCESSED_RETENTION_DAYS`, `CHUNK_CACHE_RETENTION_DAYS`,
  `DOCAI_MAX_PAGES_PER_MINUTE`:** Für alle vier bedeutet **≤ 0** vereinbart „abgeschaltet",
  kein Fehler.
- **`RETRY_MAX` ≤ 0** heißt faktisch „kein Wiederholversuch" — eine zulässige Einstellung.
- **Keine Gültigkeitsprüfung.** Kein Netzwerkzugriff, kein Parsen der Credentials-Datei.
  Geprüft wird Vorhandensein, Typ, Wertebereich, Lesbarkeit — nicht, ob ein Token gilt.

`RETRY_DELAY_MINUTES` ist der einzige geprüfte Zähler: Bei ≤ 0 liegt `retry_at`
(`app/repository.py`) im Jetzt oder in der Vergangenheit, die Pause zwischen den Versuchen
entfällt vollständig, und ein dauerhaft scheiterndes Dokument verbraucht alle Versuche in
Sekunden — jeden mit einem vollen, bezahlten OCR-Aufruf.
