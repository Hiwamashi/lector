"""Asynchroner Client für die SevDesk-API (https://api.sevdesk.de/).

Bewusst leichtgewichtig: Das Dokument (PDF/E-Rechnung) wird als Beleg (Voucher) im Status
„Entwurf" nach SevDesk übertragen — die eigentliche Verbuchung (Kategorie, Kontakt) erfolgt
anschließend in SevDesk. Ablauf laut API:

1. ``POST /Voucher/Factory/uploadTempFile`` lädt die Datei temporär hoch und liefert einen
   Dateinamen zurück.
2. ``POST /Voucher/Factory/saveVoucher`` legt den Beleg an und referenziert die Temp-Datei.

Authentifizierung per API-Token im ``Authorization``-Header (ohne Schema-Präfix).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

log = logging.getLogger("lector.sevdesk")


class SevdeskError(RuntimeError):
    pass


@dataclass
class VoucherResult:
    voucher_id: str
    link: str | None = None


class SevdeskClient:
    def __init__(self, base_url: str, token: str, *, timeout: float = 60.0) -> None:
        if not base_url or not token:
            raise SevdeskError("SEVDESK_BASE_URL und SEVDESK_API_TOKEN müssen gesetzt sein")
        self._base = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base,
            headers={"Authorization": token, "Accept": "application/json"},
            timeout=timeout,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> SevdeskClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def upload_temp_file(
        self, content: bytes, filename: str, mime: str = "application/pdf"
    ) -> str:
        resp = await self._client.post(
            "/Voucher/Factory/uploadTempFile",
            files={"file": (filename, content, mime)},
        )
        resp.raise_for_status()
        objects = resp.json().get("objects") or {}
        temp_name = objects.get("filename") if isinstance(objects, dict) else None
        if not temp_name:
            raise SevdeskError(f"uploadTempFile lieferte keinen Dateinamen: {resp.text[:200]}")
        return temp_name

    async def save_voucher_from_temp(
        self, temp_filename: str, *, description: str | None = None
    ) -> VoucherResult:
        """Legt aus der hochgeladenen Temp-Datei einen Beleg im Status „Entwurf" (50) an."""
        payload = {
            "voucher": {
                "objectName": "Voucher",
                "mapAll": True,
                "type": "VOU",
                "status": 50,
                "creditDebit": "C",
                "voucherType": "VOU",
                "description": description or "",
            },
            "voucherPosSave": None,
            "voucherPosDelete": None,
            "filename": temp_filename,
        }
        resp = await self._client.post("/Voucher/Factory/saveVoucher", json=payload)
        resp.raise_for_status()
        objects = resp.json().get("objects") or {}
        voucher = objects.get("voucher") if isinstance(objects, dict) else None
        voucher_id = None
        if isinstance(voucher, dict) and voucher.get("id"):
            voucher_id = str(voucher["id"])
        if not voucher_id:
            raise SevdeskError(f"saveVoucher lieferte keine Beleg-ID: {resp.text[:200]}")
        link = f"https://my.sevdesk.de/fi/edit/type/VOU/id/{voucher_id}"
        return VoucherResult(voucher_id=voucher_id, link=link)

    async def export_document(
        self,
        content: bytes,
        filename: str,
        *,
        mime: str = "application/pdf",
        description: str | None = None,
    ) -> VoucherResult:
        """Komfort-Methode: lädt die Datei hoch und legt direkt den Beleg an."""
        temp_name = await self.upload_temp_file(content, filename, mime)
        return await self.save_voucher_from_temp(temp_name, description=description)
