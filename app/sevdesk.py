"""Asynchroner Client für die SevDesk-API (https://api.sevdesk.de/).

Bewusst leichtgewichtig: Das Dokument (PDF/E-Rechnung) wird als Beleg (Voucher) im Status
„Entwurf" nach SevDesk übertragen — die eigentliche Verbuchung (Kategorie, Kontakt, Betrag)
erfolgt anschließend in SevDesk. Ablauf laut API:

1. ``POST /Voucher/Factory/uploadTempFile`` lädt die Datei temporär hoch und liefert einen
   Dateinamen zurück.
2. ``POST /Voucher/Factory/saveVoucher`` legt den Beleg an und referenziert die Temp-Datei.

Authentifizierung per API-Token im ``Authorization``-Header (ohne Schema-Präfix).

Auch ein Entwurf muss für SevDesk buchhalterisch vollständig sein: Datum, Währung,
Steuerregel und ein Lieferantenname sind Pflicht, sonst antwortet ``saveVoucher`` mit
HTTP 422. Der Grund steht ausschließlich im Antwortkörper — deshalb reichern wir jeden
HTTP-Fehler damit an, statt ``raise_for_status()`` zu verwenden.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime

import httpx

log = logging.getLogger("lector.sevdesk")

# „Nicht vorsteuerabziehbare Aufwendungen" — entspricht der Steuerregel, mit der die
# bestehenden Belege des Mandanten geführt werden. Lector bucht bewusst nicht vor; die
# endgültige Zuordnung erfolgt in SevDesk am Entwurf.
TAX_RULE_ID = "10"


class SevdeskError(RuntimeError):
    pass


@dataclass
class VoucherResult:
    voucher_id: str
    link: str | None = None


def _error_detail(resp: httpx.Response) -> str:
    """Zieht die Klartext-Begründung aus einer SevDesk-Fehlerantwort.

    SevDesk antwortet auf Validierungsfehler mit ``{"error": {"message": …}}``. Genau diese
    Meldung nennt das fehlende oder ungültige Feld und wird bis in die UI durchgereicht.
    """
    try:
        body = resp.json()
    except ValueError:
        return resp.text.strip()[:500]
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict) and error.get("message"):
            detail = str(error["message"])
            uuid = error.get("exceptionUUID")
            return f"{detail} (exceptionUUID {uuid})" if uuid else detail
        if isinstance(error, str) and error:
            return error
    return resp.text.strip()[:500]


def _raise_for_status(resp: httpx.Response, step: str) -> None:
    """Wie ``raise_for_status()``, nur mit der Begründung aus dem Antwortkörper.

    Der Ausnahmetyp bleibt ``httpx.HTTPStatusError``: ``PaperlessSync.export_invoice``
    unterscheidet daran retrybare Ablehnungen (4xx) von mehrdeutigen Serverfehlern (5xx).
    """
    if not resp.is_error:
        return
    detail = _error_detail(resp)
    raise httpx.HTTPStatusError(
        f"{step} fehlgeschlagen (HTTP {resp.status_code}): {detail}",
        request=resp.request,
        response=resp,
    )


def _as_iso_date(value: datetime | date | None) -> str:
    """Datumsformat der API (``YYYY-MM-DD``); ohne Vorgabe zählt der Exporttag."""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return date.today().isoformat()


class SevdeskClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not base_url or not token:
            raise SevdeskError("SEVDESK_BASE_URL und SEVDESK_API_TOKEN müssen gesetzt sein")
        self._base = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base,
            headers={"Authorization": token, "Accept": "application/json"},
            timeout=timeout,
            transport=transport,
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
        _raise_for_status(resp, "uploadTempFile")
        objects = resp.json().get("objects") or {}
        temp_name = objects.get("filename") if isinstance(objects, dict) else None
        if not temp_name:
            raise SevdeskError(f"uploadTempFile lieferte keinen Dateinamen: {resp.text[:200]}")
        return temp_name

    async def save_voucher_from_temp(
        self,
        temp_filename: str,
        *,
        description: str | None = None,
        voucher_date: datetime | date | None = None,
        supplier_name: str | None = None,
        currency: str = "EUR",
    ) -> VoucherResult:
        """Legt aus der hochgeladenen Temp-Datei einen Beleg im Status „Entwurf" (50) an.

        ``voucher_date``, ``currency``, ``taxRule`` und ein Lieferantenname sind für SevDesk
        auch am Entwurf Pflicht; fehlt eines davon, kommt HTTP 422 zurück.
        """
        belegdatum = _as_iso_date(voucher_date)
        payload = {
            "voucher": {
                "objectName": "Voucher",
                "mapAll": True,
                "voucherType": "VOU",
                "status": 50,
                "creditDebit": "C",
                "taxRule": {"id": TAX_RULE_ID, "objectName": "TaxRule"},
                "voucherDate": belegdatum,
                # SevDesk führt beide Daten an jedem Beleg; ohne eigene Leistungsangabe
                # entspricht das Lieferdatum dem Belegdatum.
                "deliveryDate": belegdatum,
                "currency": currency or "EUR",
                "supplierName": supplier_name or "",
                "description": description or "",
            },
            "voucherPosSave": None,
            "voucherPosDelete": None,
            "filename": temp_filename,
        }
        resp = await self._client.post("/Voucher/Factory/saveVoucher", json=payload)
        _raise_for_status(resp, "saveVoucher")
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
        voucher_date: datetime | date | None = None,
        supplier_name: str | None = None,
        currency: str = "EUR",
    ) -> VoucherResult:
        """Komfort-Methode: lädt die Datei hoch und legt direkt den Beleg an."""
        temp_name = await self.upload_temp_file(content, filename, mime)
        return await self.save_voucher_from_temp(
            temp_name,
            description=description,
            voucher_date=voucher_date,
            supplier_name=supplier_name,
            currency=currency,
        )
