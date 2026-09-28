"""Tests für den SevDesk-Client.

Schwerpunkt ist der ``saveVoucher``-Payload: SevDesk lehnt unvollständige Belege mit
HTTP 422 ab, ohne dass httpx den Grund sichtbar macht. Die Tests halten deshalb sowohl
die Pflichtfelder als auch die Weitergabe der Server-Fehlermeldung fest.
"""

from datetime import datetime

import httpx
import pytest

from app.sevdesk import SevdeskClient


def _client(handler) -> SevdeskClient:
    return SevdeskClient(
        "https://my.sevdesk.de/api/v1", "token", transport=httpx.MockTransport(handler)
    )


async def test_save_voucher_sendet_alle_pflichtfelder():
    """Der Beleg-Entwurf trägt die Felder, die SevDesk für jeden Beleg verlangt.

    Referenz sind die real existierenden Belege des Mandanten: dort sind voucherDate,
    deliveryDate, currency, taxRule und ein Lieferant ausnahmslos gesetzt.
    """
    gesehen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        gesehen.update(json.loads(request.content))
        return httpx.Response(201, json={"objects": {"voucher": {"id": "4711"}}})

    async with _client(handler) as sev:
        result = await sev.save_voucher_from_temp(
            "tmp-datei.pdf",
            description="Anthropic Rechnung",
            voucher_date=datetime(2026, 9, 21, 14, 25),
            supplier_name="Anthropic",
            currency="EUR",
        )

    voucher = gesehen["voucher"]
    assert voucher["voucherDate"] == "2026-09-21"
    assert voucher["deliveryDate"] == "2026-09-21"
    assert voucher["currency"] == "EUR"
    assert voucher["supplierName"] == "Anthropic"
    assert voucher["taxRule"] == {"id": "10", "objectName": "TaxRule"}
    assert voucher["creditDebit"] == "C"
    assert voucher["voucherType"] == "VOU"
    assert voucher["status"] == 50
    # "type" gehört nicht zum Voucher-Modell und wurde von SevDesk nie akzeptiert.
    assert "type" not in voucher
    assert gesehen["filename"] == "tmp-datei.pdf"
    assert result.voucher_id == "4711"


async def test_ohne_datum_faellt_auf_heute_zurueck():
    """Ein Beleg ohne Datum wird abgelehnt — fehlt es in Paperless, zählt der Exporttag."""
    gesehen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        gesehen.update(json.loads(request.content))
        return httpx.Response(201, json={"objects": {"voucher": {"id": "1"}}})

    async with _client(handler) as sev:
        await sev.save_voucher_from_temp("tmp.pdf", voucher_date=None)

    assert gesehen["voucher"]["voucherDate"] == datetime.now().date().isoformat()


async def test_422_meldung_von_sevdesk_bleibt_erhalten():
    """Der eigentliche Ablehnungsgrund darf nicht verloren gehen.

    httpx' raise_for_status() nennt nur Status und URL — die Ursache steht im Body.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            422,
            json={
                "error": {
                    "message": "Das Feld voucherDate fehlt.",
                    "code": 422,
                    "exceptionUUID": "abc-123",
                }
            },
        )

    async with _client(handler) as sev:
        with pytest.raises(httpx.HTTPStatusError) as exc:
            await sev.save_voucher_from_temp("tmp.pdf")

    meldung = str(exc.value)
    assert "Das Feld voucherDate fehlt." in meldung
    assert "422" in meldung
    # Der Typ muss httpx.HTTPStatusError bleiben: PaperlessSync unterscheidet daran
    # retrybare 4xx von mehrdeutigen 5xx.
    assert exc.value.response.status_code == 422


async def test_upload_fehler_nennt_ebenfalls_den_grund():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(413, text="Datei zu gross")

    async with _client(handler) as sev:
        with pytest.raises(httpx.HTTPStatusError) as exc:
            await sev.upload_temp_file(b"%PDF-", "x.pdf")

    assert "Datei zu gross" in str(exc.value)
