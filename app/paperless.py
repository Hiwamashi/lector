"""Asynchroner Client für die Paperless-ngx-REST-API (https://docs.paperless-ngx.com/api/).

Dieses Modul kapselt ausschließlich die HTTP-Aufrufe, die das entkoppelte GiroCode-/SevDesk-
Feature benötigt: Rechnungen über Dokumententyp + Tag finden, Inhalt/Korrespondent/Originaldatei
lesen sowie Custom Fields, Tags und Notizen zurückschreiben. Authentifizierung per API-Token
(``Authorization: Token <token>``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

log = logging.getLogger("lector.paperless")

# Paperless-Datentyp je Rückschrieb-Feld.
CF_TYPE_STRING = "string"
CF_TYPE_DATE = "date"
CF_TYPE_BOOLEAN = "boolean"


@dataclass
class PaperlessDocument:
    id: int
    title: str
    content: str
    correspondent_id: int | None
    document_type_id: int | None
    tag_ids: list[int]
    custom_fields: list[dict]
    original_file_name: str | None


class PaperlessError(RuntimeError):
    pass


class PaperlessClient:
    def __init__(self, base_url: str, token: str, *, timeout: float = 30.0) -> None:
        if not base_url or not token:
            raise PaperlessError("PAPERLESS_URL und PAPERLESS_TOKEN müssen gesetzt sein")
        self._base = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base,
            headers={"Authorization": f"Token {token}", "Accept": "application/json"},
            timeout=timeout,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> PaperlessClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    # ---- Lesen -----------------------------------------------------------

    async def _paged(self, path: str, params: dict | None = None) -> list[dict]:
        """Liest alle Seiten einer paginierten Listen-Antwort ein."""
        results: list[dict] = []
        url: str | None = path
        first = True
        while url:
            resp = await self._client.get(url, params=params if first else None)
            resp.raise_for_status()
            data = resp.json()
            results.extend(data.get("results", []))
            url = data.get("next")
            first = False
        return results

    async def resolve_document_type_id(self, name: str) -> int | None:
        items = await self._paged("/api/document_types/", {"name__iexact": name})
        for item in items:
            if item.get("name", "").lower() == name.lower():
                return int(item["id"])
        return int(items[0]["id"]) if items else None

    async def list_documents(
        self, *, document_type_id: int | None = None, tag_ids: list[int] | None = None
    ) -> list[PaperlessDocument]:
        params: dict[str, object] = {"page_size": 100, "ordering": "-created"}
        if document_type_id is not None:
            params["document_type__id"] = document_type_id
        if tag_ids:
            params["tags__id__all"] = ",".join(str(t) for t in tag_ids)
        raw = await self._paged("/api/documents/", params)
        return [self._to_document(item) for item in raw]

    async def get_document(self, doc_id: int) -> PaperlessDocument:
        resp = await self._client.get(f"/api/documents/{doc_id}/")
        resp.raise_for_status()
        return self._to_document(resp.json())

    async def get_correspondent_name(self, correspondent_id: int) -> str | None:
        resp = await self._client.get(f"/api/correspondents/{correspondent_id}/")
        resp.raise_for_status()
        return resp.json().get("name")

    async def download_original(self, doc_id: int) -> tuple[bytes, str]:
        resp = await self._client.get(
            f"/api/documents/{doc_id}/download/", params={"original": "true"}
        )
        resp.raise_for_status()
        filename = f"{doc_id}.bin"
        disposition = resp.headers.get("Content-Disposition", "")
        if "filename=" in disposition:
            filename = disposition.split("filename=", 1)[1].strip('"; ')
        return resp.content, filename

    @staticmethod
    def _to_document(item: dict) -> PaperlessDocument:
        return PaperlessDocument(
            id=int(item["id"]),
            title=item.get("title") or "",
            content=item.get("content") or "",
            correspondent_id=item.get("correspondent"),
            document_type_id=item.get("document_type"),
            tag_ids=list(item.get("tags") or []),
            custom_fields=list(item.get("custom_fields") or []),
            original_file_name=item.get("original_file_name"),
        )

    # ---- Custom Fields ---------------------------------------------------

    async def list_custom_fields(self) -> list[dict]:
        return await self._paged("/api/custom_fields/")

    async def ensure_custom_field(self, name: str, data_type: str) -> int:
        """Gibt die ID des Custom Fields zurück; legt es bei Bedarf an."""
        for field in await self.list_custom_fields():
            if field.get("name", "").lower() == name.lower():
                return int(field["id"])
        resp = await self._client.post(
            "/api/custom_fields/", json={"name": name, "data_type": data_type}
        )
        resp.raise_for_status()
        log.info("Custom Field '%s' (%s) in Paperless angelegt", name, data_type)
        return int(resp.json()["id"])

    async def set_custom_fields(self, doc_id: int, values: dict[int, object]) -> None:
        """Setzt/aktualisiert Custom-Field-Werte, ohne bestehende Felder zu verlieren."""
        current = await self.get_document(doc_id)
        merged: dict[int, object] = {
            int(cf["field"]): cf.get("value") for cf in current.custom_fields
        }
        merged.update(values)
        payload = {"custom_fields": [{"field": fid, "value": val} for fid, val in merged.items()]}
        resp = await self._client.patch(f"/api/documents/{doc_id}/", json=payload)
        resp.raise_for_status()

    # ---- Tags ------------------------------------------------------------

    async def list_tags(self) -> list[dict]:
        return await self._paged("/api/tags/")

    async def ensure_tag(self, name: str) -> int:
        for tag in await self.list_tags():
            if tag.get("name", "").lower() == name.lower():
                return int(tag["id"])
        resp = await self._client.post("/api/tags/", json={"name": name})
        resp.raise_for_status()
        log.info("Tag '%s' in Paperless angelegt", name)
        return int(resp.json()["id"])

    async def add_tags(self, doc_id: int, tag_ids: list[int]) -> None:
        current = await self.get_document(doc_id)
        merged = sorted(set(current.tag_ids) | set(tag_ids))
        if merged == sorted(current.tag_ids):
            return
        resp = await self._client.patch(f"/api/documents/{doc_id}/", json={"tags": merged})
        resp.raise_for_status()

    async def has_tag(self, doc: PaperlessDocument, tag_id: int) -> bool:
        return tag_id in doc.tag_ids

    # ---- Notizen ---------------------------------------------------------

    async def add_note(self, doc_id: int, note: str) -> None:
        resp = await self._client.post(f"/api/documents/{doc_id}/notes/", json={"note": note})
        resp.raise_for_status()
