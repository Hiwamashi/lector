# Robuster Batch-Lauf für KI-Empfänger-Vorschläge — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Der Batch-Lauf für KI-Empfänger-Vorschläge verkraftet den realen Bestand von ~1500 Dokumenten: Menge pro Lauf wählbar, Throttling der Anthropic-API wird abgefedert, Fortschritt sichtbar und Abbruch jederzeit möglich.

**Architecture:** Drei voneinander unabhängige Eingriffe in bestehende Module. Der Retry liegt im HTTP-Client (`recipient_llm.py`), weil dort das Wissen über Statuscodes sitzt und der Einzelvorschlag mitprofitiert. Das Mengen-Limit wandert von einer Modulkonstante in die Settings und wird als Parameter durchgereicht. Der Laufzustand wird von einem Bool zu einem `BatchProgress`-Dataclass, das über den vorhandenen SSE-Bus gedrosselt gemeldet und als eigenes HTML-Fragment gerendert wird.

**Tech Stack:** Python 3.12+, FastAPI, httpx (inkl. `MockTransport` für Tests), Jinja2, Vanilla-JS/SSE, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-09-18-recipient-batch-robustness-design.md`

## Global Constraints

- Code-Kommentare, Docstrings, Log- und UI-Texte auf **Deutsch**, passend zum Bestand.
- ruff: `line-length = 100`, Regeln `E,F,I,UP,B`, `target-version = py312`. Nach jeder Task `.venv/bin/python -m ruff check .` grün.
- Tests laufen **ohne Netz**. Anthropic-Aufrufe ausschließlich über `httpx.MockTransport`, Wartezeiten über gepatchtes `asyncio.sleep`.
- Kein Node-Buildchain, kein HTMX/Tailwind zur Laufzeit. UI bleibt serverseitiges Jinja2 + Vanilla-JS.
- Routen unter `/empfaenger/` mit statischem Pfad müssen **vor** `POST /empfaenger/{paperless_id}` registriert werden (Starlette matcht in Registrierungsreihenfolge).
- SSE-Token-Konvention `<typ>:<kennung>` — der Batch nutzt `batch:recipient`.
- Kein Persistieren des Laufzustands, keine Parallelisierung, keine Wiederaufnahme nach Neustart (siehe Spec, „Nicht-Ziele").
- Testkommando: `.venv/bin/python -m pytest -q`. Vollständige Suite muss nach jeder Task grün sein (Stand vor Beginn: 99 Tests).

---

## File Structure

| Datei | Verantwortung |
|---|---|
| `app/recipient_llm.py` (ändern) | Retry mit Backoff um den Anthropic-Aufruf. Kennt HTTP-Statuscodes, kennt keine Dokumente. |
| `app/config.py` (ändern) | `recipient_batch_max` als Einstellung (ENV `RECIPIENT_BATCH_MAX`, Default 1000). |
| `app/paperless_sync.py` (ändern) | `BatchProgress`, Limit-Parameter, Stopp-Flag, Fehlerserien-Abbruch, gedrosseltes Publish. |
| `app/repository.py` (ändern) | `notify_batch()` neben `notify_recipient` — einziger öffentlicher Zugang zum Event-Bus. |
| `app/main.py` (ändern) | `limit` im Batch-Endpoint, Stopp-Route, Status-Fragment, Kontext für die Toolbar. |
| `app/templates/partials/batch_status.html` (neu) | Bestand, Mengenfeld, Fortschritt, Stopp-Button. Einziger Ort der Batch-Darstellung. |
| `app/templates/recipients.html` (ändern, Z. 29-41) | Toolbar durch Include des neuen Partials ersetzen. |
| `app/static/app.js` (ändern, Z. 7-23) | Dritter Fragment-Block für `#batch-status`. |
| `tests/test_recipients.py` (ändern) | Retry, Limit, Abbruch, Fehlerserie, Fortschritt, Drossel. |
| `tests/test_web.py` (ändern) | Neue Endpoints, generischer Shadowing-Test über alle Routen. |
| `.env.example` (ändern) | `RECIPIENT_BATCH_MAX` dokumentieren. |
| `feature-documentation/paperless-integration/empfaenger-zuordnung.md` (ändern) | Fallstricke und Betrieb nachziehen. |
| `prd/PROGRESS.md` (ändern) | Fortschrittseintrag. |

**Task-Reihenfolge:** Task 1 (Retry) ist unabhängig und kommt zuerst, weil er allein schon Dokumente rettet. Task 2 (Limit) und Task 3 (Zustand) bauen aufeinander auf. Task 4 (Endpoints) braucht Task 3, Task 5 (UI) braucht Task 4. Task 6 (Doku) zuletzt, damit sie belegte Aussagen trifft.

---

### Task 1: Retry mit Backoff im LLM-Client

**Files:**
- Modify: `app/recipient_llm.py:22-27` (Konstanten), `:43-56` (`__init__`), `:117-119` (Aufruf)
- Test: `tests/test_recipients.py`

**Interfaces:**
- Consumes: nichts aus früheren Tasks.
- Produces: `RecipientSuggester.__init__(api_key, model, *, timeout=30.0, transport=None)` — der neue Keyword-Parameter `transport: httpx.AsyncBaseTransport | None` dient ausschließlich dem Test. `RecipientSuggester._retry_delay(attempt: int, resp: httpx.Response | None) -> float` (statisch). `RecipientSuggester._post_with_retry(payload: dict) -> httpx.Response`. Verhalten unverändert nach außen: `suggest(...)` liefert `RecipientSuggestion` oder wirft `RecipientSuggesterError`.

- [ ] **Step 1: Transport-Parameter ergänzen, damit Tests ohne Netz auskommen**

In `app/recipient_llm.py`, `__init__` (ab Z. 43):

```python
    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
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
            transport=transport,
        )
```

- [ ] **Step 2: Die failing Tests schreiben**

Ans Ende von `tests/test_recipients.py` anfügen:

```python
# ---- Retry / Backoff im LLM-Client --------------------------------------

import asyncio

import httpx

from app import recipient_llm as rl


def _ok_payload():
    return {
        "content": [
            {
                "type": "tool_use",
                "name": "set_recipient",
                "input": {"recipient": "Sascha", "confidence": 0.9, "reasoning": "r"},
            }
        ]
    }


def _suggester_with(responses, monkeypatch):
    """Baut einen Suggester, dessen Transport die übergebenen Antworten der Reihe nach liefert.

    Ein Eintrag ist entweder ein httpx.Response oder eine Exception, die geworfen wird.
    Wartezeiten werden aufgezeichnet statt real abzuwarten.
    """
    slept: list[float] = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(rl.asyncio, "sleep", fake_sleep)

    calls = {"n": 0}

    def handler(request):
        item = responses[calls["n"]]
        calls["n"] += 1
        if isinstance(item, Exception):
            raise item
        return item

    suggester = rl.RecipientSuggester(
        "key", "model", transport=httpx.MockTransport(handler)
    )
    return suggester, slept, calls


async def test_retry_recovers_after_429(monkeypatch):
    suggester, slept, calls = _suggester_with(
        [httpx.Response(429), httpx.Response(200, json=_ok_payload())], monkeypatch
    )
    async with suggester:
        result = await suggester.suggest(
            title="t", correspondent=None, content="c", options=["Sascha"]
        )
    assert result.label == "Sascha"
    assert calls["n"] == 2
    assert slept == [1.0]


async def test_retry_honours_retry_after_header(monkeypatch):
    suggester, slept, _ = _suggester_with(
        [
            httpx.Response(429, headers={"retry-after": "7"}),
            httpx.Response(200, json=_ok_payload()),
        ],
        monkeypatch,
    )
    async with suggester:
        await suggester.suggest(
            title="t", correspondent=None, content="c", options=["Sascha"]
        )
    assert slept == [7.0]


async def test_retry_skips_client_errors(monkeypatch):
    # 400 wird durch Warten nicht besser — genau ein Versuch, keine Wartezeit.
    suggester, slept, calls = _suggester_with([httpx.Response(400)], monkeypatch)
    async with suggester:
        with pytest.raises(RecipientSuggesterError):
            await suggester.suggest(
                title="t", correspondent=None, content="c", options=["Sascha"]
            )
    assert calls["n"] == 1
    assert slept == []


async def test_retry_gives_up_after_three_attempts(monkeypatch):
    suggester, slept, calls = _suggester_with(
        [httpx.Response(529), httpx.Response(529), httpx.Response(529)], monkeypatch
    )
    async with suggester:
        with pytest.raises(RecipientSuggesterError):
            await suggester.suggest(
                title="t", correspondent=None, content="c", options=["Sascha"]
            )
    assert calls["n"] == 3
    assert slept == [1.0, 2.0]


async def test_retry_covers_timeouts(monkeypatch):
    suggester, slept, calls = _suggester_with(
        [httpx.TimeoutException("zu langsam"), httpx.Response(200, json=_ok_payload())],
        monkeypatch,
    )
    async with suggester:
        result = await suggester.suggest(
            title="t", correspondent=None, content="c", options=["Sascha"]
        )
    assert result.label == "Sascha"
    assert calls["n"] == 2
```

- [ ] **Step 3: Tests laufen lassen, Fehlschlag bestätigen**

Run: `.venv/bin/python -m pytest tests/test_recipients.py -q -k retry`
Expected: FAIL — ohne Retry wird beim ersten 429 sofort `HTTPStatusError` geworfen, `calls["n"] == 1`.

- [ ] **Step 4: Retry implementieren**

Konstanten in `app/recipient_llm.py` neben `_MAX_CONTENT_CHARS` (Z. 26) ergänzen:

```python
# Anthropic drosselt bei Stoßlast (429) und meldet Überlast als 529. Ein Batch über
# hunderte Dokumente läuft ohne Wiederholung sonst reihenweise ins Leere.
_MAX_ATTEMPTS = 3
_BACKOFF_BASE = 1.0
_RETRY_STATUS = frozenset({429, 529})
```

`import asyncio` zu den Imports (Z. 14) hinzufügen.

Neue Methoden in `RecipientSuggester`:

```python
    @staticmethod
    def _retry_delay(attempt: int, resp: httpx.Response | None) -> float:
        """Wartezeit vor dem nächsten Versuch; ein retry-after des Servers hat Vorrang."""
        if resp is not None:
            header = resp.headers.get("retry-after")
            if header:
                try:
                    return max(0.0, float(header))
                except ValueError:
                    pass
        return _BACKOFF_BASE * (2**attempt)

    async def _post_with_retry(self, payload: dict) -> httpx.Response:
        """Sendet die Anfrage und wiederholt sie bei Drosselung, Überlast oder Timeout."""
        detail = "unbekannt"
        for attempt in range(_MAX_ATTEMPTS):
            resp: httpx.Response | None = None
            try:
                resp = await self._client.post("/v1/messages", json=payload)
            except httpx.TimeoutException as exc:
                detail = f"Zeitüberschreitung ({exc})"
            else:
                if resp.status_code < 400:
                    return resp
                retryable = resp.status_code in _RETRY_STATUS or resp.status_code >= 500
                if not retryable:
                    raise RecipientSuggesterError(
                        f"Anthropic-API antwortete mit {resp.status_code}"
                    )
                detail = f"Status {resp.status_code}"
            if attempt < _MAX_ATTEMPTS - 1:
                delay = self._retry_delay(attempt, resp)
                log.warning(
                    "Anthropic-Aufruf fehlgeschlagen (%s), neuer Versuch in %.1f s", detail, delay
                )
                await asyncio.sleep(delay)
        raise RecipientSuggesterError(
            f"Anthropic-API nach {_MAX_ATTEMPTS} Versuchen nicht erreichbar ({detail})"
        )
```

Den bisherigen Aufruf (Z. 117-119) ersetzen:

```python
        resp = await self._post_with_retry(payload)
        return self._parse(resp.json(), options)
```

- [ ] **Step 5: Tests grün, Suite grün, ruff grün**

Run: `.venv/bin/python -m pytest -q && .venv/bin/python -m ruff check .`
Expected: alle Tests PASS (99 bisherige + 5 neue = 104), ruff „All checks passed!"

- [ ] **Step 6: Commit**

```bash
git add app/recipient_llm.py tests/test_recipients.py
git commit -m "feat: Retry mit Backoff fuer Anthropic-Aufrufe

429/529/5xx und Timeouts werden bis zu dreimal wiederholt, retry-after hat
Vorrang vor dem exponentiellen Wert. 4xx ausser 429 werden nicht wiederholt.
Bisher liess ein einzelner 429 den Empfaenger-Vorschlag ausfallen.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Mengen-Limit als Einstellung und Parameter

**Files:**
- Modify: `app/config.py` (bei den `recipient_*`-Feldern, Z. 104-113), `app/paperless_sync.py:57` (Konstante), `:580-596` (`suggest_recipients_batch`), `:627-654` (`_collect_missing_ids`)
- Test: `tests/test_recipients.py:195-220` (bestehenden Test anpassen)

**Interfaces:**
- Consumes: nichts aus Task 1.
- Produces: `Settings.recipient_batch_max: int`. `PaperlessSync._collect_missing_ids(client, field, limit: int) -> tuple[list[int], int]` — liefert jetzt zusätzlich den **Rest**: Anzahl der Dokumente ohne Empfänger, die wegen des Limits nicht eingeplant wurden. `PaperlessSync.suggest_recipients_batch(limit: int | None = None) -> int`; `None` bedeutet „Obergrenze aus den Settings".

- [ ] **Step 1: Einstellung ergänzen**

In `app/config.py` bei den anderen `recipient_*`-Feldern:

```python
    recipient_batch_max: int = Field(default=1000, alias="RECIPIENT_BATCH_MAX")
```

- [ ] **Step 2: Die failing Tests schreiben**

Der bestehende Test `tests/test_recipients.py:195-220` patcht `ps.RECIPIENT_BATCH_MAX`. Diese Konstante entfällt — den Test auf den neuen Parameter umstellen und die Rest-Meldung mitprüfen. Den Testkörper ab `monkeypatch.setattr(ps, "RECIPIENT_PAGE_SIZE", 2)` ersetzen durch:

```python
    monkeypatch.setattr(ps, "RECIPIENT_PAGE_SIZE", 2)

    repo = Repository(tmp_path / "b.db")
    # Die ersten beiden fehlenden Dokumente haben bereits einen Vorschlag.
    for doc_id in (1, 2):
        repo.set_recipient_cache(
            doc_id,
            suggested_label="Sascha",
            confidence=0.9,
            reasoning=None,
            status=RecipientStatus.SUGGESTED,
        )

    sync = ps.PaperlessSync(Settings(PAPERLESS_URL="http://x", PAPERLESS_TOKEN="t"), repo)
    field = SelectField(field_id=1, label_to_id={"Sascha": "s"}, id_to_label={"s": "Sascha"})
    client = _FakeClient([1, 2, 3, 4, 5], page_size=2)

    ids, remaining = await sync._collect_missing_ids(client, field, limit=2)
    # Trotz Limit=2 dürfen die gecachten 1,2 nicht alles belegen — 3,4 müssen drankommen.
    assert ids == [3, 4]
    # 5 bleibt ungeplant liegen und muss als Rest gemeldet werden.
    assert remaining == 1
```

Zusätzlich ans Ende der Datei:

```python
async def test_collect_reports_no_rest_when_limit_suffices(tmp_path, monkeypatch):
    from app import paperless_sync as ps
    from app.config import Settings

    monkeypatch.setattr(ps, "RECIPIENT_PAGE_SIZE", 2)
    repo = Repository(tmp_path / "c.db")
    sync = ps.PaperlessSync(Settings(PAPERLESS_URL="http://x", PAPERLESS_TOKEN="t"), repo)
    field = SelectField(field_id=1, label_to_id={"Sascha": "s"}, id_to_label={"s": "Sascha"})
    client = _FakeClient([1, 2, 3], page_size=2)

    ids, remaining = await sync._collect_missing_ids(client, field, limit=10)
    assert ids == [1, 2, 3]
    assert remaining == 0
```

- [ ] **Step 3: Tests laufen lassen, Fehlschlag bestätigen**

Run: `.venv/bin/python -m pytest tests/test_recipients.py -q -k collect`
Expected: FAIL — `_collect_missing_ids() got an unexpected keyword argument 'limit'`.

- [ ] **Step 4: Limit durchreichen**

In `app/paperless_sync.py` die Konstante (Z. 57) **löschen**: `RECIPIENT_BATCH_MAX = 1000`.

`_collect_missing_ids` umbauen:

```python
    async def _collect_missing_ids(
        self, client: PaperlessClient, field: SelectField, limit: int
    ) -> tuple[list[int], int]:
        """Sammelt bis zu ``limit`` IDs von Dokumenten ohne Empfänger und ohne Vorschlag.

        Liefert zusätzlich den Rest: wie viele passende Dokumente wegen des Limits
        **nicht** eingeplant wurden. Bereits gecachte Dokumente (Status != ``none``)
        werden übersprungen, damit ein wiederholter Lauf tatsächlich neue Dokumente
        erreicht und nicht an den ersten hängen bleibt.
        """
        ids: list[int] = []
        rest = 0
        page = 1
        while True:
            page_obj = await client.search_documents(
                page=page, page_size=RECIPIENT_PAGE_SIZE, missing_field_id=field.field_id
            )
            if not page_obj.documents:
                break
            page_ids = [d.id for d in page_obj.documents]
            caches = self.repo.get_recipient_caches(page_ids)
            for doc_id in page_ids:
                cache = caches.get(doc_id)
                if cache and cache.status != RecipientStatus.NONE:
                    continue
                if len(ids) < limit:
                    ids.append(doc_id)
                else:
                    rest += 1
            if page >= page_obj.total_pages:
                break
            page += 1
        return ids, rest
```

`suggest_recipients_batch` auf den Parameter umstellen (Kopf und ID-Sammlung):

```python
    async def suggest_recipients_batch(self, limit: int | None = None) -> int:
        """Schlägt für bis zu ``limit`` Dokumente ohne Empfänger einen vor (Hintergrund-Lauf).

        ``None`` bedeutet die in den Einstellungen hinterlegte Obergrenze. Liefert die
        Anzahl verarbeiteter Dokumente. Bereits mit Vorschlag/Empfänger versehene
        Dokumente werden übersprungen, sodass der Lauf gefahrlos wiederholbar ist.
        """
        if not self.recipient_llm_enabled or self._batch_running:
            return 0
        maximum = self.settings.recipient_batch_max
        effective = min(limit or maximum, maximum)
        self._batch_running = True
        processed = 0
        try:
            async with self._paperless() as client:
                field = await self._recipient_field_cached(client)
                if field is None or not field.labels:
                    return 0
                doc_ids, rest = await self._collect_missing_ids(client, field, effective)
                if rest:
                    log.warning("Batch-Lauf auf %s Dokumente begrenzt; %s bleiben offen.",
                                effective, rest)
```

Der Rest des Methodenkörpers (Schleife ab `async with self._suggester() as suggester:`) bleibt in diesem Task unverändert.

`start_batch` reicht das Limit durch:

```python
    def start_batch(self, limit: int | None = None) -> None:
        """Startet den Batch-Lauf im Hintergrund und hält eine Task-Referenz.

        Ohne gehaltene Referenz könnte der Event-Loop den Task verwerfen, da er nur
        schwache Referenzen auf Tasks hält.
        """
        # _batch_task deckt auch das Fenster ab, in dem der Task erstellt, aber noch nicht
        # gelaufen ist (dort ist _batch_running noch False) — verhindert doppelte Läufe.
        if not self.recipient_llm_enabled or self._batch_running or self._batch_task is not None:
            return
        self._batch_task = asyncio.create_task(self.suggest_recipients_batch(limit))
        self._batch_task.add_done_callback(lambda _: setattr(self, "_batch_task", None))
```

`self.settings` ist im Bestand der übliche Zugriff (`paperless_sync.py:71`, `:89`) — kein zusätzlicher Import nötig.

- [ ] **Step 5: Tests grün, Suite grün, ruff grün**

Run: `.venv/bin/python -m pytest -q && .venv/bin/python -m ruff check .`
Expected: 105 Tests PASS, ruff sauber.

- [ ] **Step 6: Commit**

```bash
git add app/config.py app/paperless_sync.py tests/test_recipients.py
git commit -m "feat: Menge pro Batch-Lauf waehlbar statt fester Deckel

RECIPIENT_BATCH_MAX wird zur Einstellung und wirkt nur noch als Obergrenze.
_collect_missing_ids nimmt das Limit als Parameter und meldet zusaetzlich,
wie viele Dokumente deswegen liegen bleiben — bisher verschwand das in einem
log.warning.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Laufzustand, Abbruch und Fehlerserien-Erkennung

**Files:**
- Modify: `app/paperless_sync.py` (Dataclass oben bei den Konstanten, `__init__` Z. 79-82, Property Z. 109-110, `suggest_recipients_batch`)
- Test: `tests/test_recipients.py`

**Interfaces:**
- Consumes: `_collect_missing_ids(client, field, limit) -> tuple[list[int], int]` und `suggest_recipients_batch(limit)` aus Task 2.
- Produces: `BatchProgress` (Dataclass, Felder siehe unten). `PaperlessSync.batch_progress -> BatchProgress`. `PaperlessSync.stop_batch() -> None`. Die Property `batch_running` **entfällt** — Konsumenten lesen `batch_progress.running`.

- [ ] **Step 1: Die failing Tests schreiben**

Ans Ende von `tests/test_recipients.py`:

```python
# ---- Laufzustand, Abbruch, Fehlerserie ----------------------------------


class _FailingSuggester:
    """Stub, der die ersten ``fail_first`` Aufrufe scheitern lässt."""

    def __init__(self, fail_first: int):
        self._left = fail_first

    async def suggest(self, **_):
        from app.models import RecipientSuggestion
        from app.recipient_llm import RecipientSuggesterError

        if self._left > 0:
            self._left -= 1
            raise RecipientSuggesterError("throttled")
        return RecipientSuggestion(label="Sascha", confidence=0.9, reasoning="r")


def _batch_sync(tmp_path, monkeypatch, doc_ids, suggester):
    """Baut einen PaperlessSync, dessen Batch-Lauf gegen Stubs statt gegen das Netz läuft."""
    from contextlib import asynccontextmanager

    from app import paperless_sync as ps
    from app.config import Settings

    repo = Repository(tmp_path / "p.db")
    sync = ps.PaperlessSync(
        Settings(
            PAPERLESS_URL="http://x",
            PAPERLESS_TOKEN="t",
            FEATURE_RECIPIENT_LLM=True,
            ANTHROPIC_API_KEY="k",
        ),
        repo,
    )
    field = SelectField(field_id=1, label_to_id={"Sascha": "s"}, id_to_label={"s": "Sascha"})
    client = _WriteCapturingClient([])

    @asynccontextmanager
    async def fake_paperless():
        yield client

    @asynccontextmanager
    async def fake_suggester():
        yield suggester

    monkeypatch.setattr(sync, "_paperless", fake_paperless)
    monkeypatch.setattr(sync, "_suggester", fake_suggester)
    async def fake_field(_client):
        return field

    async def fake_collect(_client, _field, _limit):
        return list(doc_ids), 0

    monkeypatch.setattr(sync, "_recipient_field_cached", fake_field)
    monkeypatch.setattr(sync, "_collect_missing_ids", fake_collect)
    return sync, repo


async def test_progress_counts_done_and_failed(tmp_path, monkeypatch):
    sync, _ = _batch_sync(tmp_path, monkeypatch, [1, 2, 3], _FailingSuggester(fail_first=1))
    await sync.suggest_recipients_batch(limit=10)
    p = sync.batch_progress
    assert p.running is False
    assert p.total == 3
    assert p.done == 2
    assert p.failed == 1
    assert p.aborted_reason is None


async def test_stop_ends_run_early(tmp_path, monkeypatch):
    sync, _ = _batch_sync(tmp_path, monkeypatch, [1, 2, 3, 4], _StubSuggester("Sascha", 0.9))

    original = sync._suggest_for_doc

    async def stop_after_first(*args, **kwargs):
        result = await original(*args, **kwargs)
        sync.stop_batch()
        return result

    monkeypatch.setattr(sync, "_suggest_for_doc", stop_after_first)

    await sync.suggest_recipients_batch(limit=10)
    p = sync.batch_progress
    assert p.stopped is True
    assert p.done == 1
    assert p.running is False


async def test_error_streak_aborts_run(tmp_path, monkeypatch):
    from app import paperless_sync as ps

    monkeypatch.setattr(ps, "BATCH_ERROR_STREAK", 3)
    sync, _ = _batch_sync(tmp_path, monkeypatch, list(range(1, 21)), _FailingSuggester(99))

    await sync.suggest_recipients_batch(limit=50)
    p = sync.batch_progress
    assert p.failed == 3
    assert p.aborted_reason is not None
    assert p.done == 0


async def test_success_resets_error_streak(tmp_path, monkeypatch):
    from app import paperless_sync as ps

    monkeypatch.setattr(ps, "BATCH_ERROR_STREAK", 3)
    # 2 Fehler, dann Erfolge — die Serie darf den Lauf nicht abbrechen.
    sync, _ = _batch_sync(tmp_path, monkeypatch, [1, 2, 3, 4, 5], _FailingSuggester(fail_first=2))

    await sync.suggest_recipients_batch(limit=50)
    p = sync.batch_progress
    assert p.aborted_reason is None
    assert p.failed == 2
    assert p.done == 3
```

```python
async def test_progress_publishes_are_throttled(tmp_path, monkeypatch):
    # 30 Dokumente duerfen keine 30 SSE-Ereignisse ausloesen: die Drossel laesst
    # nur Start, Ende und hoechstens alle 2 s eines durch.
    sync, repo = _batch_sync(tmp_path, monkeypatch, list(range(1, 31)),
                             _StubSuggester("Sascha", 0.9))
    emitted: list[str] = []
    monkeypatch.setattr(repo, "notify_batch", lambda: emitted.append("batch:recipient"))

    await sync.suggest_recipients_batch(limit=50)
    # Start + Ende sind erzwungen; dazwischen darf im schnellen Testlauf nichts kommen.
    assert len(emitted) <= 4
    assert sync.batch_progress.done == 30
```

- [ ] **Step 2: Tests laufen lassen, Fehlschlag bestätigen**

Run: `.venv/bin/python -m pytest tests/test_recipients.py -q -k "progress or stop or streak or throttled"`
Expected: FAIL — `AttributeError: 'PaperlessSync' object has no attribute 'batch_progress'`.

- [ ] **Step 3: BatchProgress und Laufsteuerung implementieren**

In `app/paperless_sync.py` bei den Konstanten:

```python
# Nach so vielen Fehlschlägen in Folge wird der Lauf beendet: ein dauerhaft gedrosseltes
# oder fehlkonfiguriertes Konto soll nicht wirkungslos durch hunderte Dokumente laufen.
BATCH_ERROR_STREAK = 10
# Der Lauf meldet Fortschritt höchstens so oft — sonst erzeugt ein Lauf über 1500
# Dokumente ebenso viele SSE-Ereignisse für jeden verbundenen Client.
BATCH_PUBLISH_INTERVAL = 2.0
```

Dataclass (bei den anderen Modultypen, `from dataclasses import dataclass, field` sicherstellen):

```python
@dataclass
class BatchProgress:
    """Zustand des KI-Batch-Laufs. Lebt nur im Prozess — ein Neustart verwirft ihn."""

    running: bool = False
    total: int = 0
    done: int = 0
    failed: int = 0
    remaining: int = 0
    stopped: bool = False
    aborted_reason: str | None = None
    finished_at: datetime | None = None
```

`__init__` (Z. 79-82): `self._batch_running = False` ersetzen durch

```python
        self._progress = BatchProgress()
        self._batch_stop = False
```

Property (Z. 109-110) ersetzen:

```python
    @property
    def batch_progress(self) -> BatchProgress:
        return self._progress

    def stop_batch(self) -> None:
        """Bittet den laufenden Batch, nach dem aktuellen Dokument zu enden."""
        if self._progress.running:
            self._batch_stop = True
```

Alle verbliebenen `self._batch_running`-Zugriffe auf `self._progress.running` umstellen.

`suggest_recipients_batch` vollständig:

```python
    async def suggest_recipients_batch(self, limit: int | None = None) -> int:
        """Schlägt für bis zu ``limit`` Dokumente ohne Empfänger einen vor (Hintergrund-Lauf).

        ``None`` bedeutet die in den Einstellungen hinterlegte Obergrenze. Liefert die
        Anzahl verarbeiteter Dokumente. Bereits mit Vorschlag/Empfänger versehene
        Dokumente werden übersprungen, sodass der Lauf gefahrlos wiederholbar ist.
        """
        if not self.recipient_llm_enabled or self._progress.running:
            return 0
        maximum = self.settings.recipient_batch_max
        effective = min(limit or maximum, maximum)
        self._batch_stop = False
        self._progress = BatchProgress(running=True)
        streak = 0
        last_publish = 0.0

        def publish(force: bool = False) -> None:
            nonlocal last_publish
            now = time.monotonic()
            if force or now - last_publish >= BATCH_PUBLISH_INTERVAL:
                last_publish = now
                self.repo.notify_batch()

        try:
            async with self._paperless() as client:
                field = await self._recipient_field_cached(client)
                if field is None or not field.labels:
                    return 0
                doc_ids, rest = await self._collect_missing_ids(client, field, effective)
                self._progress.total = len(doc_ids)
                self._progress.remaining = rest
                publish(force=True)
                async with self._suggester() as suggester:
                    for doc_id in doc_ids:
                        if self._batch_stop:
                            self._progress.stopped = True
                            break
                        # Erneut prüfen: Der Lauf kann lange dauern; in der Zwischenzeit kann
                        # ein Dokument per UI bearbeitet worden sein (manueller Empfänger /
                        # Einzelvorschlag). Dann nicht erneut verarbeiten/überschreiben.
                        cache = self.repo.get_recipient_cache(doc_id)
                        if cache and cache.status != RecipientStatus.NONE:
                            continue
                        try:
                            doc = await client.get_document(doc_id)
                            correspondent = await self._correspondent_name(client, doc)
                            await self._suggest_for_doc(
                                client, suggester, field, doc, correspondent,
                                guard_concurrent=True,
                            )
                            self._progress.done += 1
                            streak = 0
                        except Exception:
                            log.exception(
                                "Empfänger-Vorschlag für Dokument %s fehlgeschlagen", doc_id
                            )
                            self._progress.failed += 1
                            streak += 1
                            if streak >= BATCH_ERROR_STREAK:
                                self._progress.aborted_reason = (
                                    f"{streak} Fehler in Folge — Lauf abgebrochen. "
                                    "Bitte Log und API-Zugang prüfen."
                                )
                                break
                        publish()
        finally:
            self._progress.running = False
            self._progress.finished_at = datetime.now(UTC)
            publish(force=True)
        log.info(
            "Empfänger-Batch beendet: %s verarbeitet, %s Fehler, %s offen",
            self._progress.done, self._progress.failed, self._progress.remaining,
        )
        return self._progress.done
```

`import time` ergänzen (`datetime`/`UTC` sind bereits importiert, `paperless_sync.py:19`).

Der Event-Bus ist von aussen nur über das Repository erreichbar — `_emit` ist privat.
Daher in `app/repository.py` neben `notify_recipient` (Z. 140) eine öffentliche Methode
ergänzen, dem vorhandenen Muster folgend:

```python
    def notify_batch(self) -> None:
        """Signalisiert der UI den Fortschritt des KI-Batch-Laufs (SSE-Token)."""
        self._emit("batch:recipient")
```

- [ ] **Step 4: Tests grün, Suite grün, ruff grün**

Run: `.venv/bin/python -m pytest -q && .venv/bin/python -m ruff check .`
Expected: 110 Tests PASS, ruff sauber.

- [ ] **Step 5: Commit**

```bash
git add app/paperless_sync.py app/repository.py tests/test_recipients.py
git commit -m "feat: Fortschritt, Abbruch und Fehlerserien-Erkennung im Batch-Lauf

Das blosse _batch_running wird zu BatchProgress (total/done/failed/remaining/
stopped/aborted_reason). stop_batch() beendet den Lauf nach dem laufenden
Dokument, zehn Fehler in Folge brechen ihn ab. Fortschritt geht gedrosselt
(max. alle 2 s) als batch:recipient ueber den SSE-Bus.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Endpoints und generischer Shadowing-Test

**Files:**
- Modify: `app/main.py` (Batch-Route, neue Stopp-Route, neues Status-Fragment, `_recipient_context` Z. 397-416)
- Test: `tests/test_web.py`

**Interfaces:**
- Consumes: `batch_progress`, `stop_batch()`, `start_batch(limit)` aus Task 3.
- Produces: `POST /empfaenger/suggest-batch` (Formularfeld `limit`), `POST /empfaenger/suggest-batch/stop`, `GET /fragment/empfaenger/batch-status`. Template-Kontext für das Status-Fragment: `progress` (`BatchProgress`), `missing_total` (int), `default_limit` (int), `batch_max` (int), `feature_llm` (bool).

- [ ] **Step 1: Die failing Tests schreiben**

Ans Ende von `tests/test_web.py`:

```python
def test_recipients_stop_route_reachable(client):
    c, _ = client
    resp = c.post("/empfaenger/suggest-batch/stop", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/empfaenger")


def test_batch_status_fragment_without_paperless(client):
    c, _ = client
    resp = c.get("/fragment/empfaenger/batch-status")
    assert resp.status_code == 200


def test_batch_limit_is_clamped(client, monkeypatch):
    # Ein absurd hohes Limit darf die Obergrenze aus den Settings nicht überschreiten.
    c, application = client
    seen = {}
    monkeypatch.setattr(
        application.state.sync, "start_batch", lambda limit=None: seen.update(limit=limit)
    )
    c.post("/empfaenger/suggest-batch", data={"limit": "999999"}, follow_redirects=False)
    assert seen["limit"] == application.state.sync.settings.recipient_batch_max

    c.post("/empfaenger/suggest-batch", data={"limit": "keine-zahl"}, follow_redirects=False)
    assert seen["limit"] >= 1


def test_no_route_is_shadowed_by_a_parametrised_one():
    """Generischer Schutz gegen die 422-Falle aus dem suggest-batch-Fehler.

    Starlette matcht Routen in Registrierungsreihenfolge. Steht eine parametrisierte
    Route vor einer statischen gleicher Segmentzahl, verschluckt sie diese.
    """
    import app.main as m

    routes = []
    for r in m.app.routes:
        for method in sorted(getattr(r, "methods", []) or []):
            if method in ("HEAD", "OPTIONS"):
                continue
            routes.append((method, r.path))

    def segments(path):
        return [("*" if s.startswith("{") else s) for s in path.strip("/").split("/")]

    shadowed = []
    for i, (m1, p1) in enumerate(routes):
        for m2, p2 in routes[i + 1 :]:
            if m1 != m2:
                continue
            a, b = segments(p1), segments(p2)
            if len(a) != len(b) or a == b:
                continue
            if all(x == "*" or x == y for x, y in zip(a, b)):
                shadowed.append(f"{m1} {p1} verdeckt {m2} {p2}")

    assert shadowed == []
```

- [ ] **Step 2: Tests laufen lassen, Fehlschlag bestätigen**

Run: `.venv/bin/python -m pytest tests/test_web.py -q -k "stop_route or batch_status or clamped or shadowed"`
Expected: FAIL — Stopp-Route und Status-Fragment liefern 404; der Shadowing-Test ist bereits grün und bleibt es.

- [ ] **Step 3: Endpoints implementieren**

In `app/main.py` den Batch-Endpoint um `limit` erweitern und die Stopp-Route **direkt daneben, weiterhin vor** `POST /empfaenger/{paperless_id}` einfügen:

```python
# Muss VOR /empfaenger/{paperless_id} stehen: Starlette matcht Routen in
# Registrierungsreihenfolge, sonst faengt die parametrisierte Route "suggest-batch"
# als paperless_id ab und die Anfrage scheitert mit 422 (int_parsing).
@app.post("/empfaenger/suggest-batch")
async def recipient_suggest_batch(
    request: Request,
    limit: str = Form(""),
    page: int = Form(1),
    q: str = Form(""),
    missing: str = Form(""),
):
    sync: PaperlessSync = request.app.state.sync
    sync.start_batch(_clamp_batch_limit(limit, sync.settings.recipient_batch_max))
    return RedirectResponse(_recipient_redirect(page, q or None, bool(missing)), status_code=303)


@app.post("/empfaenger/suggest-batch/stop")
async def recipient_suggest_batch_stop(
    request: Request,
    page: int = Form(1),
    q: str = Form(""),
    missing: str = Form(""),
):
    sync: PaperlessSync = request.app.state.sync
    sync.stop_batch()
    return RedirectResponse(_recipient_redirect(page, q or None, bool(missing)), status_code=303)
```

Hilfsfunktion neben `_recipient_redirect` (Z. 388):

```python
def _clamp_batch_limit(raw: str, maximum: int) -> int:
    """Hält die gewünschte Menge in 1..maximum; Unsinn fällt auf die Obergrenze zurück."""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return maximum
    return max(1, min(value, maximum))
```

Status-Fragment (bei den anderen `/fragment/`-Routen):

```python
@app.get("/fragment/empfaenger/batch-status", response_class=HTMLResponse)
async def recipients_batch_status(request: Request):
    sync: PaperlessSync = request.app.state.sync
    return templates.TemplateResponse(
        request, "partials/batch_status.html", await _batch_status_context(request)
    )
```

Kontext-Helfer neben `_recipient_context`:

```python
async def _batch_status_context(request: Request) -> dict:
    """Kontext der Batch-Toolbar.

    ``missing_total`` wird getrennt ermittelt: Das ``count`` der Listenansicht ist der
    Treffer-Zähler der aktuellen Suche und bei inaktivem Filter **nicht** die Zahl der
    Dokumente ohne Empfänger — der Batch arbeitet aber immer nur über diese.
    """
    sync: PaperlessSync = request.app.state.sync
    settings = sync.settings
    missing_total = 0
    if sync.recipient_enabled:
        try:
            missing_total = await sync.count_missing_recipients()
        except Exception:
            log.exception("Bestand ohne Empfänger konnte nicht ermittelt werden")
    return {
        "progress": sync.batch_progress,
        "missing_total": missing_total,
        "default_limit": min(missing_total, 100) or 1,
        "batch_max": settings.recipient_batch_max,
        "feature_llm": sync.recipient_llm_enabled,
        "recipient_enabled": sync.recipient_enabled,
    }
```

In `app/paperless_sync.py` die dazu nötige Zählmethode ergänzen:

```python
    async def count_missing_recipients(self) -> int:
        """Zählt Dokumente ohne gesetzten Empfänger (nur der Zähler, keine Seiteninhalte)."""
        async with self._paperless() as client:
            field = await self._recipient_field_cached(client)
            if field is None:
                return 0
            page = await client.search_documents(
                page=1, page_size=1, missing_field_id=field.field_id
            )
            return page.count
```

`_recipient_context` (Z. 397-416) erweitern: `"batch_running": sync.batch_running` entfernen und stattdessen den Batch-Kontext einmischen:

```python
    ctx.update(await _batch_status_context(request))
```

- [ ] **Step 4: Tests grün, Suite grün, ruff grün**

Run: `.venv/bin/python -m pytest -q && .venv/bin/python -m ruff check .`
Expected: 114 Tests PASS, ruff sauber.

- [ ] **Step 5: Commit**

```bash
git add app/main.py app/paperless_sync.py tests/test_web.py
git commit -m "feat: Endpoints fuer Mengenwahl, Abbruch und Batch-Status

POST /empfaenger/suggest-batch nimmt eine Menge entgegen (auf 1..Obergrenze
geklemmt), /empfaenger/suggest-batch/stop bricht ab, /fragment/empfaenger/
batch-status liefert die Toolbar. Dazu ein generischer Test, der ALLE Routen
paarweise auf Verdeckung prueft statt nur den bekannten Einzelfall.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Oberfläche — Bestand, Mengenfeld, Fortschritt, Stopp

**Files:**
- Create: `app/templates/partials/batch_status.html`
- Modify: `app/templates/recipients.html:29-41`, `app/static/app.js:7-23`
- Test: `tests/test_web.py`

**Interfaces:**
- Consumes: Kontext aus Task 4 (`progress`, `missing_total`, `default_limit`, `batch_max`, `feature_llm`).
- Produces: Element `#batch-status` mit `data-fragment="/fragment/empfaenger/batch-status"`.

- [ ] **Step 1: Den failing Test schreiben**

Ans Ende von `tests/test_web.py`:

```python
def test_recipients_page_shows_batch_toolbar_container(client):
    # Ohne Paperless bleibt die Toolbar leer, der Container mit data-fragment
    # muss aber da sein — sonst kann das Live-Update nicht greifen.
    c, _ = client
    resp = c.get("/empfaenger")
    assert 'id="batch-status"' in resp.text
    assert 'data-fragment="/fragment/empfaenger/batch-status"' in resp.text
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag bestätigen**

Run: `.venv/bin/python -m pytest tests/test_web.py -q -k toolbar_container`
Expected: FAIL — `assert 'id="batch-status"' in resp.text`.

- [ ] **Step 3: Partial anlegen**

`app/templates/partials/batch_status.html`:

```html
{% if feature_llm %}
  {% if progress.running %}
    <span class="muted">
      KI-Lauf: {{ progress.done }} / {{ progress.total }}
      {%- if progress.failed %} · {{ progress.failed }} Fehler{% endif %}
    </span>
    <form method="post" action="/empfaenger/suggest-batch/stop">
      <button type="submit">Lauf stoppen</button>
    </form>
  {% else %}
    <form method="post" action="/empfaenger/suggest-batch">
      <label>
        Menge
        <input type="number" name="limit" min="1" max="{{ batch_max }}"
               value="{{ default_limit }}" size="5" />
      </label>
      <button type="submit" {% if not missing_total %}disabled{% endif %}>
        KI-Vorschlag starten
      </button>
      <span class="muted">{{ missing_total }} ohne Empfänger</span>
    </form>
    {% if progress.finished_at %}
      <span class="muted">
        Zuletzt: {{ progress.done }} verarbeitet
        {%- if progress.failed %}, {{ progress.failed }} Fehler{% endif %}
        {%- if progress.stopped %} (abgebrochen){% endif %}
        {%- if progress.remaining %} — {{ progress.remaining }} offen, erneut starten{% endif %}
      </span>
      {% if progress.aborted_reason %}
        <span class="error">{{ progress.aborted_reason }}</span>
      {% endif %}
    {% endif %}
  {% endif %}
{% endif %}
```

- [ ] **Step 4: Toolbar in `recipients.html` ersetzen**

Den Block Z. 29-41 (`<div class="recipient-toolbar">` … `</div>`) ersetzen durch:

```html
<div class="recipient-toolbar" id="batch-status"
     data-fragment="/fragment/empfaenger/batch-status">
  {% include "partials/batch_status.html" %}
</div>
```

Das bisherige `{{ count }} Dokument(e)` entfällt hier nicht ersatzlos — es bleibt als eigener Zähler der Liste erhalten, jetzt außerhalb des Fragment-Containers:

```html
<p class="muted">{{ count }} Dokument(e){% if filters.missing %} ohne Empfänger{% endif %}</p>
```

- [ ] **Step 5: `app.js` um den dritten Block erweitern**

In `refreshFragment()` (nach dem `#detail`-Block, Z. 22):

```javascript
    var batch = document.getElementById("batch-status");
    if (batch && batch.getAttribute("data-fragment")) {
      fetch(batch.getAttribute("data-fragment"))
        .then(function (r) { return r.text(); })
        .then(function (html) { batch.innerHTML = html; })
        .catch(function () {});
    }
```

Den Kommentar am Dateikopf (Z. 1-3) um den neuen Token ergänzen: `"batch:recipient"` für den Fortschritt des KI-Laufs.

- [ ] **Step 6: Tests grün, Suite grün, ruff grün**

Run: `.venv/bin/python -m pytest -q && .venv/bin/python -m ruff check .`
Expected: 115 Tests PASS, ruff sauber.

- [ ] **Step 7: Commit**

```bash
git add app/templates/partials/batch_status.html app/templates/recipients.html app/static/app.js tests/test_web.py
git commit -m "feat: Batch-Toolbar mit Bestand, Mengenfeld, Fortschritt und Stopp

Die Toolbar wird ein eigenes Fragment und aktualisiert sich ueber den
bestehenden SSE-Kanal. Sichtbar sind jetzt Bestand ohne Empfaenger, Menge
fuer diesen Lauf, laufender Fortschritt, Fehlerzahl und ein offener Rest.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Dokumentation nachziehen

**Files:**
- Modify: `.env.example`, `feature-documentation/paperless-integration/empfaenger-zuordnung.md`, `prd/PROGRESS.md`

**Interfaces:**
- Consumes: das fertige Verhalten aus Task 1-5.
- Produces: nichts, worauf Code zugreift.

- [ ] **Step 1: ENV dokumentieren**

In `.env.example` bei den anderen `RECIPIENT_*`-Variablen:

```bash
# Obergrenze fuer einen KI-Batch-Lauf. Die tatsaechliche Menge waehlt man pro Lauf
# in der Oberflaeche; dieser Wert deckelt sie nach oben.
RECIPIENT_BATCH_MAX=1000
```

- [ ] **Step 2: Feature-Doku aktualisieren**

In `feature-documentation/paperless-integration/empfaenger-zuordnung.md`:

Unter „Übersicht & Routen": die beiden neuen Routen ergänzen (`POST /empfaenger/suggest-batch/stop`, `GET /fragment/empfaenger/batch-status`) und beim Batch-Eintrag die wählbare Menge erwähnen.

Unter „Fallstricke" den Eintrag zum fehlenden Rate-Limit-Handling **ersetzen** — er ist mit Task 1 überholt:

```markdown
- **Retry im LLM-Client:** `recipient_llm.py` wiederholt 429/529/5xx und Timeouts bis zu
  dreimal mit exponentiellem Backoff; ein `retry-after` des Servers hat Vorrang. 4xx außer
  429 werden nicht wiederholt. Erst danach zählt der Batch ein Dokument als Fehler.
- **Fehlerserie beendet den Lauf:** Zehn Fehlschläge in Folge (`BATCH_ERROR_STREAK`) brechen
  den Batch ab und setzen `aborted_reason`, sichtbar in der Toolbar.
- **Fortschritt ist nicht persistent:** `BatchProgress` lebt im Prozess. Ein Neustart
  verwirft ihn; geschriebene Vorschläge und gesetzte Empfänger bleiben erhalten.
```

Der Eintrag zur Routen-Reihenfolge bleibt, ergänzt um den Hinweis auf den generischen Test
`tests/test_web.py::test_no_route_is_shadowed_by_a_parametrised_one`.

- [ ] **Step 3: PROGRESS.md fortschreiben**

Im Abschnitt zur Paperless-Integration eine Zeile ergänzen:

```markdown
| Batch-Lauf: Menge wählbar, Retry mit Backoff, Fortschritt + Abbruch | ✅ |
```

Und die Testzahl auf den dann aktuellen Stand bringen.

- [ ] **Step 4: Graph aktualisieren und committen**

```bash
.venv/bin/python -m pytest -q && .venv/bin/python -m ruff check .
graphify update .
git add -A
git commit -m "docs: Batch-Lauf-Robustheit dokumentiert

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Verifikation am Ende

- [ ] Vollständige Suite grün, ruff sauber.
- [ ] `graphify update .` gelaufen.
- [ ] Manuell nicht prüfbar und daher dem Anwender zu melden: Verhalten gegen die echte
      Paperless-Instanz und ein echtes Anthropic-Konto (Throttling lässt sich lokal nur
      simulieren). Dazu Image bauen, pushen (`scripts/push-image.sh`) und auf dem NAS
      ausrollen.
