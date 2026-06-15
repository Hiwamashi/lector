"""KI-gestützter Empfänger-Vorschlag über die Anthropic-Messages-API.

Reaktiviert die ohnehin im Stack vorhandene Anthropic-Anbindung (vgl. paperless-gpt), um zu
einem Dokument das passende Familienmitglied aus dem kuratierten Paperless-Custom-Field
„Empfänger" vorzuschlagen. Bewusst httpx-basiert (konsistent zu ``paperless.py`` / ``sevdesk.py``,
keine zusätzliche Abhängigkeit).

Kernprinzip: Die Modell-Antwort wird per Tool-Use **streng** auf eine der erlaubten Optionen
(oder „unbekannt") beschränkt — die KI kann keine neuen Empfängernamen erfinden.
"""

from __future__ import annotations

import logging

import httpx

from .models import RecipientSuggestion

log = logging.getLogger("lector.recipient_llm")

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
_UNKNOWN = "unbekannt"
# OCR-Text kann sehr lang sein; für die Zuordnung genügt der Anfang (Adressblock/Anrede).
_MAX_CONTENT_CHARS = 6000

_SYSTEM = (
    "Du ordnest eingescannte Haushaltsdokumente dem richtigen Empfänger innerhalb einer "
    "Familie zu. Der Empfänger ist die Person, AN die das Dokument gerichtet ist (Adressat / "
    "Anrede / Vertragsnehmer), NICHT der Absender. Wähle ausschließlich aus den vorgegebenen "
    "Optionen. Wenn sich der Empfänger nicht eindeutig bestimmen lässt, wähle 'unbekannt' und "
    "setze eine niedrige Konfidenz. Betrifft das Dokument den ganzen Haushalt (z.B. "
    "Nebenkosten, Versicherung der Wohnung), wähle 'Familie', sofern vorhanden."
)


class RecipientSuggesterError(RuntimeError):
    pass


class RecipientSuggester:
    def __init__(self, api_key: str, model: str, *, timeout: float = 30.0) -> None:
        if not api_key:
            raise RecipientSuggesterError("ANTHROPIC_API_KEY ist nicht gesetzt")
        self._model = model
        self._client = httpx.AsyncClient(
            base_url="https://api.anthropic.com",
            headers={
                "x-api-key": api_key,
                "anthropic-version": ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
            timeout=timeout,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> RecipientSuggester:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def suggest(
        self,
        *,
        title: str | None,
        correspondent: str | None,
        content: str | None,
        options: list[str],
    ) -> RecipientSuggestion:
        if not options:
            raise RecipientSuggesterError("Keine Empfänger-Optionen übergeben")
        enum = [*options, _UNKNOWN]
        tool = {
            "name": "set_recipient",
            "description": "Ordnet das Dokument genau einem Empfänger zu.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "recipient": {
                        "type": "string",
                        "enum": enum,
                        "description": "Der Empfänger oder 'unbekannt'.",
                    },
                    "confidence": {
                        "type": "number",
                        "description": "Sicherheit der Zuordnung zwischen 0 und 1.",
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "Kurze Begründung (ein Satz).",
                    },
                },
                "required": ["recipient", "confidence"],
            },
        }
        # Statischer System-Block wird zwischengespeichert (Prompt-Caching) — die
        # Optionenliste gehört zur dynamischen User-Nachricht.
        payload = {
            "model": self._model,
            "max_tokens": 256,
            "system": [
                {"type": "text", "text": _SYSTEM, "cache_control": {"type": "ephemeral"}}
            ],
            "tools": [tool],
            "tool_choice": {"type": "tool", "name": "set_recipient"},
            "messages": [
                {
                    "role": "user",
                    "content": self._build_prompt(title, correspondent, content, options),
                }
            ],
        }
        resp = await self._client.post("/v1/messages", json=payload)
        resp.raise_for_status()
        return self._parse(resp.json(), options)

    @staticmethod
    def _build_prompt(
        title: str | None, correspondent: str | None, content: str | None, options: list[str]
    ) -> str:
        text = (content or "").strip()[:_MAX_CONTENT_CHARS]
        return (
            f"Mögliche Empfänger: {', '.join(options)}\n\n"
            f"Titel: {title or '—'}\n"
            f"Absender/Korrespondent: {correspondent or '—'}\n\n"
            f"Dokumenttext (Auszug):\n{text or '—'}"
        )

    @staticmethod
    def _parse(data: dict, options: list[str]) -> RecipientSuggestion:
        tool_input: dict | None = None
        for block in data.get("content", []):
            if block.get("type") == "tool_use" and block.get("name") == "set_recipient":
                tool_input = block.get("input") or {}
                break
        if tool_input is None:
            raise RecipientSuggesterError("Modellantwort enthielt keinen set_recipient-Aufruf")
        recipient = (tool_input.get("recipient") or "").strip()
        try:
            confidence = float(tool_input.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))
        reasoning = tool_input.get("reasoning") or None
        # Schutz: Nur exakt erlaubte Labels durchlassen, sonst als "unbekannt" behandeln.
        label = recipient if recipient in options else None
        return RecipientSuggestion(label=label, confidence=confidence, reasoning=reasoning)
