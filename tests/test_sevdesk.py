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


def _voucher_obj(i: int, **extra) -> dict:
    obj = {
        "id": str(i),
        "voucherDate": "2026-10-03T00:00:00+02:00",
        "supplierName": f"Lieferant {i}",
        "sumGross": "39.27",
        "currency": "EUR",
        "description": f"Beleg {i}",
        "status": "50",
    }
    obj.update(extra)
    return obj


async def test_list_vouchers_blaettert_ueber_zwei_seiten():
    aufrufe = []

    def handler(request: httpx.Request) -> httpx.Response:
        aufrufe.append(dict(request.url.params))
        offset = int(request.url.params["offset"])
        seiten = {0: [_voucher_obj(1), _voucher_obj(2)], 2: [_voucher_obj(3)]}
        return httpx.Response(200, json={"objects": seiten.get(offset, [])})

    async with _client(handler) as sev:
        vouchers = await sev.list_vouchers(page_size=2)

    assert [v.voucher_id for v in vouchers] == ["1", "2", "3"]
    assert [(a["limit"], a["offset"]) for a in aufrufe] == [("2", "0"), ("2", "2")]


async def test_list_vouchers_volle_letzte_seite_fragt_noch_einmal():
    def handler(request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params["offset"])
        objs = [_voucher_obj(1), _voucher_obj(2)] if offset == 0 else []
        return httpx.Response(200, json={"objects": objs})

    async with _client(handler) as sev:
        assert len(await sev.list_vouchers(page_size=2)) == 2


async def test_list_vouchers_standard_limit_1000():
    gesehen = []

    def handler(request: httpx.Request) -> httpx.Response:
        gesehen.append(request.url.params["limit"])
        offset = int(request.url.params["offset"])
        objs = (
            [_voucher_obj(i) for i in range(offset, offset + 1000)]
            if offset == 0
            else [_voucher_obj(5000)]
        )
        return httpx.Response(200, json={"objects": objs})

    async with _client(handler) as sev:
        vouchers = await sev.list_vouchers()

    assert len(vouchers) == 1001
    assert set(gesehen) == {"1000"}


async def test_list_vouchers_mapping_string_zahlen_und_zeitzonen_datum():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"objects": [_voucher_obj(7, sumGross="112.00")]})

    async with _client(handler) as sev:
        (v,) = await sev.list_vouchers()

    assert v.voucher_id == "7"
    assert v.voucher_date == "2026-10-03"
    assert v.sum_gross == 112.0
    assert v.currency == "EUR"
    assert v.status == "50"
    assert v.supplier_name == "Lieferant 7"
    assert v.description == "Beleg 7"


async def test_list_vouchers_lieferant_rueckfall_und_fehlende_werte():
    objs = [
        {"id": "1", "supplierName": None, "supplier": {"name": "Eingebettet GmbH"}},
        {"id": "2", "sumGross": "kaputt", "voucherDate": "kein Datum"},
        {"id": 3, "sumGross": 0, "voucherDate": None},
        {"supplierName": "ohne id"},
        "kein objekt",
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"objects": objs})

    async with _client(handler) as sev:
        vouchers = await sev.list_vouchers()

    assert [v.voucher_id for v in vouchers] == ["1", "2", "3"]
    assert vouchers[0].supplier_name == "Eingebettet GmbH"
    assert vouchers[0].sum_gross is None
    assert vouchers[1].supplier_name is None
    assert vouchers[1].sum_gross is None
    assert vouchers[1].voucher_date is None
    assert vouchers[2].sum_gross == 0.0


async def test_list_vouchers_fehler_nutzt_raise_for_status():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "Token ungültig"}})

    async with _client(handler) as sev:
        with pytest.raises(httpx.HTTPStatusError, match="Token ungültig"):
            await sev.list_vouchers()


# ---- Belegposition mit Betrag (Design 9, Befund 1.1(b)) ----------------------


async def _gesendeter_payload(**kwargs) -> dict:
    import json

    gesehen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        gesehen.update(json.loads(request.content))
        return httpx.Response(201, json={"objects": {"voucher": {"id": "4711"}}})

    async with _client(handler) as sev:
        await sev.save_voucher_from_temp("tmp.pdf", description="Lizenz", **kwargs)
    return gesehen


async def test_position_nur_mit_betrag_und_konto():
    payload = await _gesendeter_payload(amount=112.5, account_datev_id="4279")
    assert payload["voucherPosSave"] == [
        {
            "objectName": "VoucherPos",
            "mapAll": True,
            "accountDatev": {"id": "4279", "objectName": "AccountDatev"},
            "taxRate": 0,
            "net": False,
            "sumGross": 112.5,
            "comment": "Lizenz",
        }
    ]


async def test_position_kommentar_wird_gekuerzt():
    import json

    gesehen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        gesehen.update(json.loads(request.content))
        return httpx.Response(201, json={"objects": {"voucher": {"id": "1"}}})

    async with _client(handler) as sev:
        await sev.save_voucher_from_temp(
            "t.pdf", description="x" * 500, amount=1.0, account_datev_id="1"
        )
    assert len(gesehen["voucherPosSave"][0]["comment"]) <= 100


@pytest.mark.parametrize(
    "kwargs",
    [{}, {"amount": 10.0}, {"account_datev_id": "4279"}, {"amount": None, "account_datev_id": ""}],
)
async def test_ohne_betrag_oder_konto_bleibt_position_none(kwargs):
    payload = await _gesendeter_payload(**kwargs)
    assert payload["voucherPosSave"] is None


async def test_export_document_reicht_betrag_und_konto_durch():
    import json

    gesehen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("uploadTempFile"):
            return httpx.Response(200, json={"objects": {"filename": "tmp.pdf"}})
        gesehen.append(json.loads(request.content))
        return httpx.Response(201, json={"objects": {"voucher": {"id": "9"}}})

    async with _client(handler) as sev:
        await sev.export_document(
            b"%PDF", "a.pdf", description="d", amount=5.0, account_datev_id="4279"
        )
        await sev.export_document(b"%PDF", "a.pdf", description="d")
    assert gesehen[0]["voucherPosSave"][0]["sumGross"] == 5.0
    assert gesehen[1]["voucherPosSave"] is None
