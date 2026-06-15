"""Zentrale Konfiguration — ausschließlich über Umgebungsvariablen (siehe PRD §4.5)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # OCR-Engine
    ocr_provider: str = Field(default="documentai", alias="OCR_PROVIDER")
    gcp_project_id: str = Field(default="", alias="GCP_PROJECT_ID")
    docai_location: str = Field(default="eu", alias="DOCAI_LOCATION")
    docai_processor_id: str = Field(default="", alias="DOCAI_PROCESSOR_ID")
    google_application_credentials: str = Field(
        default="", alias="GOOGLE_APPLICATION_CREDENTIALS"
    )

    # Ordnerpfade
    watch_dir: Path = Field(default=Path("/scan-in"), alias="WATCH_DIR")
    consume_dir: Path = Field(default=Path("/consume"), alias="CONSUME_DIR")
    processed_dir: Path = Field(default=Path("/processed"), alias="PROCESSED_DIR")
    error_dir: Path = Field(default=Path("/error"), alias="ERROR_DIR")
    db_path: Path = Field(default=Path("/data/lector.db"), alias="DB_PATH")

    # Lifecycle / Retry / Retention
    processed_retention_days: int = Field(default=30, alias="PROCESSED_RETENTION_DAYS")
    retry_delay_minutes: int = Field(default=15, alias="RETRY_DELAY_MINUTES")
    retry_max: int = Field(default=3, alias="RETRY_MAX")
    chunk_size_pages: int = Field(default=15, alias="CHUNK_SIZE_PAGES")

    # Vorverarbeitung (Orientierung übernimmt Document AI, kein lokales Auto-Rotate)
    preprocess_deskew: bool = Field(default=True, alias="PREPROCESS_DESKEW")
    preprocess_contrast: bool = Field(default=True, alias="PREPROCESS_CONTRAST")

    # Watch-Folder-Vollständigkeitsprüfung
    poll_interval_seconds: float = Field(default=2.0, alias="POLL_INTERVAL_SECONDS")
    stability_window_seconds: float = Field(default=6.0, alias="STABILITY_WINDOW_SECONDS")
    partial_suffixes: str = Field(default=".tmp,.part,.crdownload", alias="PARTIAL_SUFFIXES")

    # Throttling gegen Document-AI-Quota
    docai_max_pages_per_minute: int = Field(default=120, alias="DOCAI_MAX_PAGES_PER_MINUTE")

    # Ausgabe-Eigentümerschaft (geteilter consume-Ordner mit Paperless)
    puid: int = Field(default=1000, alias="PUID")
    pgid: int = Field(default=1000, alias="PGID")

    # Sonstiges
    tz: str = Field(default="Europe/Berlin", alias="TZ")
    host: str = Field(default="0.0.0.0", alias="HOST")
    port: int = Field(default=8001, alias="PORT")

    # ---- Paperless-Integration (entkoppeltes Feature-Set: GiroCode + SevDesk) ----
    # Schaltet den periodischen Abgleich gegen die Paperless-API frei.
    feature_paperless_sync: bool = Field(default=False, alias="FEATURE_PAPERLESS_SYNC")
    paperless_url: str = Field(default="", alias="PAPERLESS_URL")
    paperless_token: str = Field(default="", alias="PAPERLESS_TOKEN")
    # Öffentliche, im Browser erreichbare Paperless-URL für den "In Paperless öffnen"-Link.
    # Im Compose-Stack ist PAPERLESS_URL die container-interne Adresse (http://webserver:8000),
    # die im Browser nicht auflösbar ist — daher hier die externe URL setzen.
    # Leer = Fallback auf paperless_url.
    paperless_public_url: str = Field(default="", alias="PAPERLESS_PUBLIC_URL")
    # Name des Paperless-Dokumententyps, der Rechnungen kennzeichnet.
    paperless_invoice_doctype: str = Field(default="Rechnung", alias="PAPERLESS_INVOICE_DOCTYPE")
    paperless_sync_interval_seconds: float = Field(
        default=300.0, alias="PAPERLESS_SYNC_INTERVAL_SECONDS"
    )
    # Wenn Custom Fields / Tags in Paperless fehlen, legt Lector sie automatisch an.
    paperless_auto_create_fields: bool = Field(
        default=True, alias="PAPERLESS_AUTO_CREATE_FIELDS"
    )

    # GiroCode: Gläubigername aus dem Paperless-Korrespondenten ableiten, falls nicht im Beleg.
    girocode_creditor_from_correspondent: bool = Field(
        default=True, alias="GIROCODE_CREDITOR_FROM_CORRESPONDENT"
    )

    # SevDesk-Export
    feature_sevdesk_export: bool = Field(default=False, alias="FEATURE_SEVDESK_EXPORT")
    sevdesk_api_token: str = Field(default="", alias="SEVDESK_API_TOKEN")
    sevdesk_base_url: str = Field(default="https://my.sevdesk.de/api/v1", alias="SEVDESK_BASE_URL")
    # Paperless-Tag, der den Export nach SevDesk auslöst.
    sevdesk_tag: str = Field(default="sevdesk", alias="SEVDESK_TAG")
    # true = automatischer Export beim Sync, false = nur Vormerken (manuelle Bestätigung im UI).
    sevdesk_auto_export: bool = Field(default=False, alias="SEVDESK_AUTO_EXPORT")

    # Namen der Paperless-Custom-Fields / -Tags für den Rückschrieb.
    cf_giro_iban: str = Field(default="Zahlung IBAN", alias="CF_GIRO_IBAN")
    cf_giro_amount: str = Field(default="Zahlbetrag", alias="CF_GIRO_AMOUNT")
    cf_sevdesk_id: str = Field(default="SevDesk-Beleg", alias="CF_SEVDESK_ID")
    cf_exported_at: str = Field(default="SevDesk-Export am", alias="CF_EXPORTED_AT")
    cf_paid: str = Field(default="Überwiesen", alias="CF_PAID")
    tag_sevdesk_done: str = Field(default="sevdesk-exportiert", alias="TAG_SEVDESK_DONE")
    tag_paid: str = Field(default="überwiesen", alias="TAG_PAID")

    # ---- Empfänger-Zuordnung (Paperless-Custom-Field "Empfänger", Typ select) ----
    # Name des kuratierten select-Custom-Fields in Paperless. Wird NICHT automatisch
    # angelegt — die Auswahloptionen (Familienmitglieder) pflegst du in Paperless.
    cf_recipient: str = Field(default="Empfänger", alias="CF_RECIPIENT")
    # KI-gestützter Empfänger-Vorschlag (reaktiviert die paperless-gpt-Anthropic-Anbindung).
    feature_recipient_llm: bool = Field(default=False, alias="FEATURE_RECIPIENT_LLM")
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    recipient_llm_model: str = Field(default="claude-sonnet-4-6", alias="RECIPIENT_LLM_MODEL")
    # true = Vorschlag ab der Konfidenz-Schwelle direkt ins Paperless-Feld schreiben.
    recipient_llm_auto_apply: bool = Field(default=True, alias="RECIPIENT_LLM_AUTO_APPLY")
    # Mindest-Konfidenz (0..1) für das automatische Setzen; darunter nur vorschlagen.
    recipient_llm_min_confidence: float = Field(
        default=0.75, alias="RECIPIENT_LLM_MIN_CONFIDENCE"
    )

    @property
    def partial_suffix_list(self) -> list[str]:
        return [s.strip().lower() for s in self.partial_suffixes.split(",") if s.strip()]

    def ensure_dirs(self) -> None:
        for d in (self.watch_dir, self.consume_dir, self.processed_dir, self.error_dir):
            d.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
