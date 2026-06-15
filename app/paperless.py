"""Asynchroner Client für die Paperless-ngx-REST-API (https://docs.paperless-ngx.com/api/).

Dieses Modul kapselt ausschließlich die HTTP-Aufrufe, die das entkoppelte GiroCode-/SevDesk-
Feature benötigt: Rechnungen über Dokumententyp + Tag finden, Inhalt/Korrespondent/Originaldatei
lesen sowie Custom Fields, Tags und Notizen zurückschreiben. Authentifizierung per API-Token
(``Authorization: Token <token>``).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from dataclasses import field as dc_field

import httpx

log = logging.getLogger("lector.paperless")

# Paperless-Datentyp je Rückschrieb-Feld.
CF_TYPE_STRING = "string"
CF_TYPE_DATE = "date"
CF_TYPE_BOOLEAN = "boolean"
CF_TYPE_SELECT = "select"


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
    # Dokumentdatum aus Paperless (ISO-8601, Feld ``created``).
    created: str | None = None


@dataclass
class SelectField:
    """Ein Paperless-Custom-Field vom Typ ``select`` inkl. Optionen-Mapping.

    Bei select-Feldern ist der gespeicherte Wert die Options-ID (z.B. ``a4B0i4oDHTPB9g2M``),
    nicht das sichtbare Label. ``label_to_id`` / ``id_to_label`` übersetzen zwischen beidem.
    """

    field_id: int
    label_to_id: dict[str, str] = dc_field(default_factory=dict)
    id_to_label: dict[str, str] = dc_field(default_factory=dict)

    @property
    def labels(self) -> list[str]:
        return list(self.label_to_id.keys())


@dataclass
class DocumentPage:
    """Eine Seite der paginierten Dokumentliste."""

    documents: list[PaperlessDocument]
    count: int
    page: int
    page_size: int

    @property
    def total_pages(self) -> int:
        if self.page_size <= 0:
            return 1
        return max(1, (self.count + self.page_size - 1) // self.page_size)


class PaperlessError(RuntimeError):
    pass


class PaperlessClient:
    def __init__(self, base_url: str, token: str, *, timeout: float = 30.0) -> None:
        if not base_url or not token:
            raise PaperlessError("PAPERLESS_URL und PAPERLESS_TOKEN müssen gesetzt sein")
        self._base = base_url.rstrip("/")
        # follow_redirects: Paperless liefert paginierte ``next``-URLs teils mit http-Schema,
        # was hinter einem HTTPS-Proxy einen 308-Redirect auslöst — der muss verfolgt werden.
        self._client = httpx.AsyncClient(
            base_url=self._base,
            headers={"Authorization": f"Token {token}", "Accept": "application/json"},
            timeout=timeout,
            follow_redirects=True,
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

    async def search_documents(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        query: str | None = None,
        ordering: str = "-created",
        missing_field_id: int | None = None,
    ) -> DocumentPage:
        """Liefert eine einzelne, paginierte Seite der Dokumentliste.

        ``missing_field_id`` filtert über ``custom_field_query`` auf Dokumente, bei denen das
        angegebene Custom Field NICHT gesetzt ist (Operator ``exists=false``).
        """
        params: dict[str, object] = {
            "page": page,
            "page_size": page_size,
            "ordering": ordering,
        }
        if query:
            params["query"] = query
        if missing_field_id is not None:
            params["custom_field_query"] = json.dumps(
                ["AND", [[missing_field_id, "exists", False]]]
            )
        resp = await self._client.get("/api/documents/", params=params)
        resp.raise_for_status()
        data = resp.json()
        docs = [self._to_document(item) for item in data.get("results", [])]
        return DocumentPage(
            documents=docs, count=int(data.get("count", 0)), page=page, page_size=page_size
        )

    async def get_document(self, doc_id: int) -> PaperlessDocument:
        resp = await self._client.get(f"/api/documents/{doc_id}/")
        resp.raise_for_status()
        return self._to_document(resp.json())

    async def get_correspondent_name(self, correspondent_id: int) -> str | None:
        resp = await self._client.get(f"/api/correspondents/{correspondent_id}/")
        resp.raise_for_status()
        return resp.json().get("name")

    async def correspondent_map(self) -> dict[int, str]:
        """Liefert ``{id: name}`` aller Korrespondenten (eine paginierte Abfrage)."""
        items = await self._paged("/api/correspondents/")
        return {int(c["id"]): c.get("name", "") for c in items if c.get("id") is not None}

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

    async def download_preview(self, doc_id: int) -> tuple[bytes, str]:
        """Lädt die Vorschau (durchsuchbares PDF) eines Dokuments inkl. Content-Type.

        Wird vom Lector-Backend an die UI weitergereicht, damit die Vorschau über
        Lectors eigene Origin läuft (Token-Auth serverseitig, kein X-Frame-Options-/
        CORS-Problem).
        """
        resp = await self._client.get(f"/api/documents/{doc_id}/preview/")
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "application/pdf")
        return resp.content, content_type

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
            created=item.get("created"),
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

    async def resolve_select_field(self, name: str) -> SelectField | None:
        """Sucht ein ``select``-Custom-Field nach Namen und liest seine Optionen ein.

        Legt NICHTS an — das Feld und seine Optionen werden in Paperless gepflegt.
        """
        for fld in await self.list_custom_fields():
            if fld.get("name", "").lower() != name.lower():
                continue
            if fld.get("data_type") != CF_TYPE_SELECT:
                log.warning(
                    "Custom Field '%s' ist kein select-Feld (Typ %s)", name, fld.get("data_type")
                )
                return None
            options = (fld.get("extra_data") or {}).get("select_options") or []
            label_to_id: dict[str, str] = {}
            id_to_label: dict[str, str] = {}
            for opt in options:
                opt_id, label = opt.get("id"), opt.get("label")
                if opt_id and label:
                    label_to_id[label] = opt_id
                    id_to_label[opt_id] = label
            return SelectField(
                field_id=int(fld["id"]), label_to_id=label_to_id, id_to_label=id_to_label
            )
        log.warning("Select-Custom-Field '%s' in Paperless nicht gefunden", name)
        return None

    @staticmethod
    def select_value(doc: PaperlessDocument, field_id: int) -> str | None:
        """Liest den gesetzten Options-ID-Wert eines select-Feldes aus einem Dokument."""
        for cf in doc.custom_fields:
            if int(cf.get("field")) == field_id:
                value = cf.get("value")
                return str(value) if value else None
        return None

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
