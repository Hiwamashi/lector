"""Google Document AI Adapter (Enterprise Document OCR, Region `eu`).

Sendet Seitenblöcke (≤ Seitenlimit) als mehrseitiges TIFF an die Online-Process-API und
wandelt die Antwort in das engine-unabhängige `OcrResult` mit normalisierten Bounding-Boxes.
"""

from __future__ import annotations

import io

from PIL import Image

from ..config import Settings
from ..models import OcrPage, OcrResult, OcrToken
from .base import OcrAdapter, ProgressCallback, RateLimiter, chunked

# Online-Process-Limit der Document-AI-Engine (siehe PRD: ≤ 15 Seiten pro Block).
DOCAI_ONLINE_PAGE_LIMIT = 15


def _pages_to_tiff(pages: list[Image.Image]) -> bytes:
    buf = io.BytesIO()
    first, rest = pages[0], pages[1:]
    first.save(buf, format="TIFF", save_all=True, append_images=rest, compression="tiff_deflate")
    return buf.getvalue()


def _text_from_anchor(anchor, full_text: str) -> str:
    if anchor is None or not getattr(anchor, "text_segments", None):
        return ""
    parts: list[str] = []
    for seg in anchor.text_segments:
        start = int(getattr(seg, "start_index", 0) or 0)
        end = int(getattr(seg, "end_index", 0) or 0)
        parts.append(full_text[start:end])
    return "".join(parts)


def _box_from_vertices(vertices) -> tuple[float, float, float, float]:
    xs = [float(v.x) for v in vertices]
    ys = [float(v.y) for v in vertices]
    return min(xs), min(ys), max(xs), max(ys)


def document_to_pages(document, page_offset: int) -> list[OcrPage]:
    """Wandelt ein Document-AI-`Document` in OcrPages. `page_offset` = globaler Index des
    ersten Blocks. Reine Funktion (duck-typed), damit sie ohne echte API testbar bleibt."""
    full_text = getattr(document, "text", "") or ""
    result: list[OcrPage] = []
    for local_idx, page in enumerate(document.pages):
        dim = page.dimension
        ocr_page = OcrPage(
            page_index=page_offset + local_idx,
            width=float(dim.width),
            height=float(dim.height),
        )
        for token in getattr(page, "tokens", []):
            layout = token.layout
            text = _text_from_anchor(layout.text_anchor, full_text)
            vertices = layout.bounding_poly.normalized_vertices
            if not vertices:
                continue
            x0, y0, x1, y1 = _box_from_vertices(vertices)
            ocr_page.tokens.append(
                OcrToken(
                    text=text,
                    x0=x0,
                    y0=y0,
                    x1=x1,
                    y1=y1,
                    confidence=float(getattr(layout, "confidence", 1.0) or 1.0),
                )
            )
        result.append(ocr_page)
    return result


class DocumentAiAdapter(OcrAdapter):
    name = "documentai"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._rate_limiter = RateLimiter(settings.docai_max_pages_per_minute)
        self._client = None
        self._processor_name: str | None = None

    @property
    def page_limit(self) -> int:
        configured = self._settings.chunk_size_pages
        if configured > 0:
            return min(configured, DOCAI_ONLINE_PAGE_LIMIT)
        return DOCAI_ONLINE_PAGE_LIMIT

    def _ensure_client(self):
        if self._client is not None:
            return
        from google.api_core.client_options import ClientOptions
        from google.cloud import documentai

        location = self._settings.docai_location
        opts = ClientOptions(api_endpoint=f"{location}-documentai.googleapis.com")
        self._client = documentai.DocumentProcessorServiceClient(client_options=opts)
        self._processor_name = self._client.processor_path(
            self._settings.gcp_project_id, location, self._settings.docai_processor_id
        )

    def _process_chunk(self, pages: list[Image.Image]):
        from google.cloud import documentai

        self._ensure_client()
        raw = documentai.RawDocument(content=_pages_to_tiff(pages), mime_type="image/tiff")
        request = documentai.ProcessRequest(name=self._processor_name, raw_document=raw)
        response = self._client.process_document(request=request)
        return response.document

    def process(
        self, pages: list[Image.Image], progress: ProgressCallback | None = None
    ) -> OcrResult:
        result = OcrResult()
        processed = 0
        offset = 0
        for chunk in chunked(pages, self.page_limit):
            self._rate_limiter.acquire(len(chunk))
            document = self._process_chunk(chunk)
            result.pages.extend(document_to_pages(document, offset))
            offset += len(chunk)
            processed += len(chunk)
            if progress:
                progress(processed)
        return result
