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

    # Vorverarbeitung
    preprocess_deskew: bool = Field(default=True, alias="PREPROCESS_DESKEW")
    preprocess_autorotate: bool = Field(default=True, alias="PREPROCESS_AUTOROTATE")
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
