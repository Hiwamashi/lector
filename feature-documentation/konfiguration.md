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
| `PREPROCESS_DESKEW`/`_AUTOROTATE`/`_CONTRAST` | true | Vorverarbeitungs-Flags |
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
