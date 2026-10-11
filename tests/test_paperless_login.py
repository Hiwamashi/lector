"""Tests für ``obtain_token`` (Anmeldeprüfung gegen Paperless) mit httpx.MockTransport."""

from __future__ import annotations

import json
import logging

import httpx
import pytest

from app.paperless import LoginResult, _is_mfa_required, obtain_token


def _transport(handler):
    return httpx.MockTransport(handler)


async def _call(handler, code=None):
    return await obtain_token(
        "http://webserver:8000/", "anna", "geheim", code, transport=_transport(handler)
    )


async def test_ok():
    def handler(request):
        return httpx.Response(200, json={"token": "abc"})

    assert await _call(handler) == LoginResult.OK


async def test_mfa_erforderlich():
    def handler(request):
        return httpx.Response(400, json={"code": ["This field is required."]})

    assert await _call(handler) == LoginResult.MFA_REQUIRED


async def test_ungueltig():
    def handler(request):
        return httpx.Response(
            400, json={"non_field_errors": ["Unable to log in with provided credentials."]}
        )

    assert await _call(handler) == LoginResult.INVALID


async def test_401_403_ungueltig():
    for status in (401, 403):
        assert await _call(lambda r, s=status: httpx.Response(s)) == LoginResult.INVALID


async def test_server_fehler():
    assert await _call(lambda r: httpx.Response(500)) == LoginResult.UNAVAILABLE


async def test_connect_error():
    def handler(request):
        raise httpx.ConnectError("boom")

    assert await _call(handler) == LoginResult.UNAVAILABLE


async def test_timeout():
    def handler(request):
        raise httpx.ReadTimeout("zu langsam")

    assert await _call(handler) == LoginResult.UNAVAILABLE


async def test_200_ohne_token_oder_kaputtes_json():
    assert await _call(lambda r: httpx.Response(200, json={})) == LoginResult.UNAVAILABLE
    assert await _call(lambda r: httpx.Response(200, content=b"<html>")) == LoginResult.UNAVAILABLE


async def test_code_nur_wenn_gesetzt_und_kein_auth_header():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"token": "abc"})

    await _call(handler)
    await _call(handler, code="123456")
    await _call(handler, code="")
    bodies = [json.loads(r.content) for r in seen]
    assert bodies[0] == {"username": "anna", "password": "geheim"}
    assert bodies[1]["code"] == "123456"
    assert "code" not in bodies[2]
    assert all("authorization" not in r.headers for r in seen)
    assert str(seen[0].url) == "http://webserver:8000/api/token/"


async def test_falscher_mfa_code_ist_ungueltig_nicht_mfa_erforderlich():
    """Wurde ein Code gesendet und lehnt Paperless ab, zählt das als Fehlversuch."""
    for body in (
        {"code": ["Invalid code."]},
        {"non_field_errors": ["Invalid two-factor code"]},
        {"detail": "MFA failed"},
    ):
        result = await _call(lambda r, b=body: httpx.Response(400, json=b), code="000000")
        assert result == LoginResult.INVALID


async def test_mfa_erforderlich_nur_ohne_code():
    def handler(request):
        return httpx.Response(400, json={"non_field_errors": ["MFA code required"]})

    assert await _call(handler) == LoginResult.MFA_REQUIRED
    assert await _call(handler, code="   ".strip()) == LoginResult.MFA_REQUIRED


@pytest.mark.parametrize(
    ("body", "erwartet"),
    [
        ({"code": ["This field is required."]}, True),
        ({"detail": "Two-Factor authentication required"}, True),
        ({"detail": "2FA required"}, True),
        ({"detail": "Enter your one-time password"}, True),
        ({"detail": "TOTP missing"}, True),
        ({"non_field_errors": ["MFA required"]}, True),
        # das bloße Wort "code" in einem Text oder verschachtelt zählt nicht
        ({"non_field_errors": ["Invalid country code"]}, False),
        ({"detail": "Unable to log in with provided credentials. Code 7"}, False),
        ({"errors": {"code": ["x"]}}, False),
        ("zip code unknown", False),
        ({"non_field_errors": ["Unable to log in with provided credentials."]}, False),
        (None, False),
    ],
)
def test_is_mfa_required(body, erwartet):
    assert _is_mfa_required(body) is erwartet


async def test_umleitung_ist_nicht_erreichbar_und_wird_nicht_verfolgt(caplog):
    gesehen = []

    def handler(request):
        gesehen.append(str(request.url))
        return httpx.Response(302, headers={"Location": "https://evil.example/api/token/"})

    with caplog.at_level(logging.WARNING, logger="lector.paperless"):
        assert await _call(handler) == LoginResult.UNAVAILABLE
    assert gesehen == ["http://webserver:8000/api/token/"]  # Passwort ging nicht weiter
    text = caplog.text
    assert "302" in text and "evil.example" in text
    assert "geheim" not in text
