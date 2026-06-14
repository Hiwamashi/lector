"""OCR-Adapter-Paket. `get_adapter` wählt anhand der Settings die konkrete Engine."""

from __future__ import annotations

from ..config import Settings
from .base import OcrAdapter, ProgressCallback


def get_adapter(settings: Settings) -> OcrAdapter:
    provider = settings.ocr_provider.lower()
    if provider == "documentai":
        from .documentai import DocumentAiAdapter

        return DocumentAiAdapter(settings)
    raise ValueError(f"Unbekannter OCR_PROVIDER: {settings.ocr_provider!r}")


__all__ = ["OcrAdapter", "ProgressCallback", "get_adapter"]
