import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WATCH_DIR", str(tmp_path / "scan-in"))
    monkeypatch.setenv("CONSUME_DIR", str(tmp_path / "consume"))
    monkeypatch.setenv("PROCESSED_DIR", str(tmp_path / "processed"))
    monkeypatch.setenv("ERROR_DIR", str(tmp_path / "error"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "data" / "lector.db"))

    import app.config
    import app.main

    app.config.get_settings.cache_clear()
    importlib.reload(app.main)
    with TestClient(app.main.app) as c:
        yield c, app.main.app


def test_healthz(client):
    c, _ = client
    assert c.get("/healthz").json() == {"status": "ok"}


def test_dashboard_empty(client):
    c, _ = client
    resp = c.get("/")
    assert resp.status_code == 200
    assert "Lector" in resp.text
    # Der Leerzustand nennt seit der UI-Politur auch den Grund, nicht nur die Tatsache.
    assert "Noch nichts eingegangen." in resp.text
    assert "überwachten Eingangsordner" in resp.text


def test_dashboard_shows_document_and_detail(client):
    c, application = client
    repo = application.state.repo
    doc_id = repo.create_document(
        original_filename="rechnung.pdf", source_path="/scan-in/rechnung.pdf"
    )

    resp = c.get("/")
    assert "rechnung.pdf" in resp.text

    detail = c.get(f"/documents/{doc_id}")
    assert detail.status_code == 200
    assert "rechnung.pdf" in detail.text
    assert "Verlauf" in detail.text


def test_history_fragment_filter_by_status(client):
    c, application = client
    repo = application.state.repo
    from app.models import DocStatus

    a = repo.create_document(original_filename="a.pdf", source_path="/x/a.pdf")
    repo.create_document(original_filename="b.pdf", source_path="/x/b.pdf")
    repo.set_status(a, DocStatus.DONE)

    frag = c.get("/fragment/history", params={"status": "done"})
    assert "a.pdf" in frag.text
    assert "b.pdf" not in frag.text


def test_laufendes_dokument_zeigt_fortschrittsbalken(client):
    """Der Balken ist das Zeichen, dass gerade etwas passiert. Er haengt deshalb am
    Status ``processing`` und nicht daran, dass Seitenzahlen bekannt sind."""
    c, application = client
    repo = application.state.repo
    from app.models import DocStatus

    laufend = repo.create_document(original_filename="lang.pdf", source_path="/x/lang.pdf")
    repo.update_document(laufend, total_pages=9)
    repo.set_status(laufend, DocStatus.PROCESSING)
    repo.set_progress(laufend, 4)

    fertig = repo.create_document(original_filename="kurz.pdf", source_path="/x/kurz.pdf")
    repo.update_document(fertig, total_pages=2)
    repo.set_status(fertig, DocStatus.DONE)
    repo.set_progress(fertig, 2)

    text = c.get("/fragment/history").text
    assert 'class="progress-inline"' in text
    assert "width: 44%" in text          # 4 von 9, abgerundet
    assert text.count('class="progress-inline"') == 1   # nur das laufende
    assert "4/9" in text and "2/2" in text


def test_zeilen_tragen_signatur_fuer_den_abgleich(client):
    """app.js vergleicht data-rev vor und nach einem Live-Abgleich, um nur geaenderte
    Zeilen aufleuchten zu lassen. Fehlt die Signatur, leuchtet jede Zeile bei jedem
    Takt — und sagt damit nichts mehr aus."""
    c, application = client
    repo = application.state.repo
    doc_id = repo.create_document(original_filename="a.pdf", source_path="/x/a.pdf")

    text = c.get("/fragment/history").text
    assert f'data-row-id="{doc_id}"' in text
    assert "data-rev=" in text


def test_detailseite_rendert_mit_ereignissen(client):
    """Regression: Die Detailansicht lief in einen 500, weil ``list_events`` den
    Zeitstempel als SQLite-Text durchreichte und ``fmt_dt`` ein datetime erwartet.
    Der vorhandene Detail-Test deckte das nicht ab — ein frisch angelegtes Dokument
    hat null Ereignisse, die Schleife im Template lief nie durch."""
    c, application = client
    repo = application.state.repo
    from app.models import EventType

    doc_id = repo.create_document(original_filename="a.pdf", source_path="/x/a.pdf")
    repo.add_event(doc_id, EventType.DETECTED, "Format erkannt")
    repo.add_event(doc_id, EventType.DONE, "fertig")

    resp = c.get(f"/documents/{doc_id}")
    assert resp.status_code == 200
    assert "Format erkannt" in resp.text
    # Das Fragment rendert dasselbe Partial und war genauso betroffen.
    assert c.get(f"/fragment/documents/{doc_id}").status_code == 200


def test_detail_404(client):
    c, _ = client
    assert c.get("/documents/99999").status_code == 404


def test_invoices_list_shows_date_and_sort_headers(client):
    c, application = client
    repo = application.state.repo
    repo.upsert_invoice(
        paperless_id=1, title="Strom", correspondent="Stadtwerke", document_date="2026-06-06"
    )

    resp = c.get("/invoices")
    assert resp.status_code == 200
    assert "Datum" in resp.text
    assert "sort-arrow" in resp.text
    assert "06.06.2026" in resp.text


def test_invoices_sorting_changes_order(client):
    c, application = client
    repo = application.state.repo
    repo.upsert_invoice(
        paperless_id=1, title="Beta", correspondent=None, document_date="2026-03-01"
    )
    repo.upsert_invoice(
        paperless_id=2, title="Alpha", correspondent=None, document_date="2026-01-01"
    )

    frag = c.get("/fragment/invoices", params={"sort": "title", "dir": "asc"})
    assert frag.text.index("Alpha") < frag.text.index("Beta")


def test_rechnungsdetail_zeigt_ereigniszeit_formatiert(client):
    """Die Ereigniszeiten der Rechnungen standen roh und in UTC da, waehrend die
    uebrige App Ortszeit im Format TT.MM.JJJJ HH:MM zeigt."""
    import re

    c, application = client
    repo = application.state.repo
    from app.models import InvoiceEventType

    inv_id = repo.upsert_invoice(paperless_id=42, title="Strom", correspondent="Stadtwerke")
    repo.add_invoice_event(inv_id, InvoiceEventType.SYNCED, "eingelesen")

    resp = c.get(f"/invoices/{inv_id}")
    assert resp.status_code == 200
    zeit = re.search(r'<span class="event-time">([^<]*)</span>', resp.text)
    assert zeit is not None, "keine Ereigniszeit gerendert"
    assert re.fullmatch(r"\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}", zeit.group(1).strip()), (
        f"Ereigniszeit nicht im App-Format: {zeit.group(1)!r}"
    )


def test_sort_links_url_encode_filters(client):
    c, _ = client
    # Suchbegriff mit Sonderzeichen, die einen Query-String zerstören würden.
    resp = c.get("/invoices", params={"q": "Müller & Co=1"})
    assert resp.status_code == 200
    # Roh eingesetzt würde "&" einen zusätzlichen Parameter erzeugen → muss kodiert sein.
    assert "q=M%C3%BCller%20%26%20Co%3D1" in resp.text or "q=M%C3%BCller+%26+Co%3D1" in resp.text
    assert "&q=Müller & Co=1" not in resp.text


def test_invoice_detail_shows_document_date(client):
    c, application = client
    repo = application.state.repo
    inv_id = repo.upsert_invoice(
        paperless_id=7, title="Miete", correspondent=None, document_date="2026-06-06"
    )

    detail = c.get(f"/invoices/{inv_id}")
    assert detail.status_code == 200
    assert "Dokumentdatum" in detail.text
    assert "06.06.2026" in detail.text


def test_recipients_page_without_paperless_shows_hint(client):
    # Ohne PAPERLESS_URL/TOKEN ist das Feature deaktiviert → Hinweis statt Fehler.
    c, _ = client
    resp = c.get("/empfaenger")
    assert resp.status_code == 200
    assert "Paperless-Anbindung fehlt" in resp.text


def test_recipients_set_without_paperless_redirects(client):
    c, _ = client
    resp = c.post("/empfaenger/5", data={"recipient": "Sascha"}, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/empfaenger")


def test_recipients_suggest_batch_route_not_shadowed(client):
    # Regression: Die parametrisierte Route /empfaenger/{paperless_id} darf die statische
    # Batch-Route nicht verschlucken. Starlette matcht in Registrierungsreihenfolge —
    # stand die parametrisierte zuerst, lief der Batch-Klick in einen 422
    # (int_parsing, input="suggest-batch") statt den Lauf zu starten.
    c, _ = client
    resp = c.post("/empfaenger/suggest-batch", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/empfaenger")


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

    # BLOCKER-Regression: Ein unlesbarer Wert darf NIEMALS auf die Obergrenze (hier
    # Default 1000) zurückfallen — das würde einen versehentlichen Maximallauf auslösen.
    # Der Rückfall ist die konservative Vorbelegung (höchstens 100).
    c.post("/empfaenger/suggest-batch", data={"limit": "keine-zahl"}, follow_redirects=False)
    assert seen["limit"] == 100

    # BLOCKER: Ein leeres Formularfeld (bei <input type="number"> ohne "required" per
    # HTML5 nicht verhindert) ist der eigentliche Praxisfall — ein Nutzer löscht den
    # Inhalt und klickt "Starten". Auch das darf keinen 1000er-Lauf auslösen.
    c.post("/empfaenger/suggest-batch", data={"limit": ""}, follow_redirects=False)
    assert seen["limit"] == 100


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
            if all(x == "*" or x == y for x, y in zip(a, b, strict=True)):
                shadowed.append(f"{m1} {p1} verdeckt {m2} {p2}")

    assert shadowed == []


async def test_recipient_row_fragment_skips_batch_status_count(client, monkeypatch):
    """Regression (Review-Befund J): /fragment/empfaenger rendert nur die Zeilentabelle
    (partials/recipient_rows.html) und nutzt weder missing_total noch progress — der
    Bestand-Zählaufruf aus _batch_status_context darf hier nicht mitlaufen."""
    from app.paperless import DocumentPage

    c, application = client
    sync = application.state.sync
    monkeypatch.setattr(type(sync), "recipient_enabled", property(lambda self: True))
    monkeypatch.setattr(type(sync), "recipient_llm_enabled", property(lambda self: True))

    async def fake_list(*_a, **_kw):
        return [], DocumentPage(documents=[], count=0, page=1, page_size=50), None

    monkeypatch.setattr(sync, "list_recipient_documents", fake_list)

    calls = 0

    async def spy(*_a, **_kw):
        nonlocal calls
        calls += 1
        return 42

    monkeypatch.setattr(sync, "count_missing_recipients", spy)

    resp = c.get("/fragment/empfaenger")
    assert resp.status_code == 200
    assert calls == 0


async def test_batch_status_skips_missing_count_without_llm_feature(client, monkeypatch):
    """Regression (Review-Befund A): Ist Paperless verbunden, aber das KI-Feature aus,
    darf der teure Netzwerk-Zählaufruf nicht laufen — ``batch_status.html`` blendet den
    Block dann ohnehin per ``recipient_enabled and feature_llm`` aus."""
    c, application = client
    sync = application.state.sync
    monkeypatch.setattr(type(sync), "recipient_enabled", property(lambda self: True))
    monkeypatch.setattr(type(sync), "recipient_llm_enabled", property(lambda self: False))
    calls = 0

    async def spy(*_a, **_kw):
        nonlocal calls
        calls += 1
        return 42

    monkeypatch.setattr(sync, "count_missing_recipients", spy)

    resp = c.get("/fragment/empfaenger/batch-status")
    assert resp.status_code == 200
    assert calls == 0


async def test_batch_status_default_limit_never_exceeds_batch_max(client, monkeypatch):
    """Regression (Review-Befund B): Bei kleinem ``RECIPIENT_BATCH_MAX`` darf die
    Vorbelegung des Mengenfelds nicht über sein eigenes ``max`` hinausgehen — sonst
    blockiert die HTML5-Constraint-Validierung das Absenden des Formulars."""
    import app.main as m

    c, application = client
    sync = application.state.sync
    monkeypatch.setattr(type(sync), "recipient_enabled", property(lambda self: True))
    monkeypatch.setattr(type(sync), "recipient_llm_enabled", property(lambda self: True))
    monkeypatch.setattr(sync.settings, "recipient_batch_max", 50)

    async def spy(*_a, **_kw):
        return 500

    monkeypatch.setattr(sync, "count_missing_recipients", spy)

    resp = c.get("/fragment/empfaenger/batch-status")
    assert resp.status_code == 200

    class _FakeRequest:
        app = application

    ctx = await m._batch_status_context(_FakeRequest())
    assert ctx["batch_max"] == 50
    assert ctx["default_limit"] <= ctx["batch_max"]


async def test_batch_status_start_button_stays_enabled_when_count_fails(client, monkeypatch):
    """BLOCKER-Regression: Wirft ``count_missing_recipients`` (z.B. Paperless-Aussetzer),
    darf die Oberfläche NICHT "0 Dokument(e) ohne Empfänger" mit deaktiviertem
    Start-Button zeigen — das friert den Button dauerhaft ein, bis die Seite manuell
    neu geladen wird (kommen ja keine weiteren SSE-Ereignisse mehr). Stattdessen muss
    der Bestand als unbekannt ausgewiesen werden und der Button nutzbar bleiben."""
    c, application = client
    sync = application.state.sync
    monkeypatch.setattr(type(sync), "recipient_enabled", property(lambda self: True))
    monkeypatch.setattr(type(sync), "recipient_llm_enabled", property(lambda self: True))

    async def boom(*_a, **_kw):
        raise RuntimeError("Paperless nicht erreichbar")

    monkeypatch.setattr(sync, "count_missing_recipients", boom)

    resp = c.get("/fragment/empfaenger/batch-status")
    assert resp.status_code == 200
    assert "disabled" not in resp.text
    assert "0 Dokument(e)" not in resp.text
    assert "kann gerade nicht ermittelt werden" in resp.text


def test_recipients_page_shows_batch_toolbar_container(client):
    # Ohne Paperless bleibt die Toolbar leer, der Container mit data-fragment
    # muss aber da sein — sonst kann das Live-Update nicht greifen.
    c, _ = client
    resp = c.get("/empfaenger")
    assert 'id="batch-status"' in resp.text
    # Query-Parameter (page/q/missing) haengen an der Fragment-URL, damit die Route
    # dieselben Filter kennt wie die aktuelle Seite (siehe Fix-Runde 1) — daher Prefix-
    # statt Exact-Match.
    assert 'data-fragment="/fragment/empfaenger/batch-status?' in resp.text


async def test_batch_status_forms_carry_current_filters_as_hidden_fields(client, monkeypatch):
    """Fix-Runde 1 (Important-Befund): Ohne Hidden-Felder fuer page/q/missing wirft der
    Redirect nach Start/Stopp den Anwender auf Seite 1 ohne Filter zurueck, selbst wenn
    er auf Seite 3 mit aktivem Filter stand. Beide Formulare muessen die *aktuellen*
    Werte tragen — nicht nur irgendeine Hidden-Feld-Struktur."""
    c, application = client
    sync = application.state.sync
    monkeypatch.setattr(type(sync), "recipient_enabled", property(lambda self: True))
    monkeypatch.setattr(type(sync), "recipient_llm_enabled", property(lambda self: True))

    async def spy(*_a, **_kw):
        return 5

    monkeypatch.setattr(sync, "count_missing_recipients", spy)

    # Formular "KI-Vorschlag starten" (Lauf steht, progress.running ist False).
    resp = c.get("/fragment/empfaenger/batch-status?page=3&q=rechnung&missing=1")
    assert resp.status_code == 200
    assert '<input type="hidden" name="page" value="3" />' in resp.text
    assert '<input type="hidden" name="q" value="rechnung" />' in resp.text
    assert '<input type="hidden" name="missing" value="1" />' in resp.text

    # Formular "Abbrechen" (Lauf laeuft, progress.running ist True).
    sync.batch_progress.running = True
    resp = c.get("/fragment/empfaenger/batch-status?page=3&q=rechnung&missing=1")
    assert resp.status_code == 200
    assert '<input type="hidden" name="page" value="3" />' in resp.text
    assert '<input type="hidden" name="q" value="rechnung" />' in resp.text
    assert '<input type="hidden" name="missing" value="1" />' in resp.text


async def test_recipient_row_fragment_renders_with_paperless(client, monkeypatch):
    """Regression: /fragment/empfaenger muss tatsächlich rendern, nicht nur früh aussteigen.

    Ohne Paperless-Anbindung antwortet die Route mit 404 — dadurch wurde
    ``partials/recipient_rows.html`` in der gesamten Suite nie gerendert, und ein
    fehlender Kontext-Schlüssel (``filters``) fiel erst im Betrieb als 500 auf.
    """
    from app.models import RecipientRow
    from app.paperless import DocumentPage, SelectField

    c, application = client
    sync = application.state.sync
    monkeypatch.setattr(type(sync), "recipient_enabled", property(lambda self: True))
    monkeypatch.setattr(type(sync), "recipient_llm_enabled", property(lambda self: True))

    row = RecipientRow(
        paperless_id=7,
        title="Rechnung",
        correspondent=None,
        document_date=None,
        current_recipient=None,
    )
    field = SelectField(field_id=1, label_to_id={"Sascha": "s"}, id_to_label={"s": "Sascha"})

    async def fake_list(*_a, **_kw):
        page = DocumentPage(documents=[], count=1, page=1, page_size=50)
        return [row], page, field

    monkeypatch.setattr(sync, "list_recipient_documents", fake_list)

    resp = c.get("/fragment/empfaenger?q=rechnung&missing=1&page=1")
    assert resp.status_code == 200
    # Die Hidden-Felder des Zeilen-Fragments tragen die aktuellen Filterwerte.
    assert 'name="q" value="rechnung"' in resp.text


def test_paperless_unavailable_shows_hint_instead_of_500(client, monkeypatch):
    """Regression: Ist Paperless (noch) nicht erreichbar, darf die Seite keinen
    Internal Server Error werfen, sondern muss den Zustand verständlich benennen."""
    import httpx

    c, application = client
    sync = application.state.sync
    monkeypatch.setattr(type(sync), "recipient_enabled", property(lambda self: True))

    async def boom(*_a, **_kw):
        raise httpx.ConnectError("All connection attempts failed")

    monkeypatch.setattr(sync, "list_recipient_documents", boom)

    resp = c.get("/empfaenger")
    assert resp.status_code == 503
    assert "Paperless" in resp.text
    # Kein durchgereichter Stacktrace.
    assert "Traceback" not in resp.text
    assert "ConnectError" not in resp.text


def test_paperless_unavailable_keeps_fragment_short(client, monkeypatch):
    """Fragmente werden per fetch in die Seite gesetzt — im Fehlerfall darf dort
    keine komplette Fehlerseite landen."""
    import httpx

    c, application = client
    sync = application.state.sync
    monkeypatch.setattr(type(sync), "recipient_enabled", property(lambda self: True))

    async def boom(*_a, **_kw):
        raise httpx.ConnectError("All connection attempts failed")

    monkeypatch.setattr(sync, "list_recipient_documents", boom)

    resp = c.get("/fragment/empfaenger")
    assert resp.status_code == 503
    assert "<html" not in resp.text.lower()


def test_batch_status_running_keeps_count_outside_the_bar(client, monkeypatch):
    """Der Zähltext gehört neben den Fortschrittsbalken, nicht hinein.

    Im Balken war er auf weißer Schrift über einer noch leeren Füllung unlesbar und
    wurde bei längeren Texten ("… übersprungen, … fehlgeschlagen") abgeschnitten.
    """
    from app.paperless_sync import BatchProgress

    c, application = client
    sync = application.state.sync
    monkeypatch.setattr(type(sync), "recipient_enabled", property(lambda self: True))
    monkeypatch.setattr(type(sync), "recipient_llm_enabled", property(lambda self: True))
    monkeypatch.setattr(
        type(sync),
        "batch_progress",
        property(
            lambda self: BatchProgress(
                running=True, total=100, done=12, failed=1, skipped=2
            )
        ),
    )

    resp = c.get("/fragment/empfaenger/batch-status")
    assert resp.status_code == 200
    assert "12" in resp.text and "von 100 verarbeitet" in resp.text
    # Der Balken trägt nur Segmente, keinen Text ...
    assert "progress-label" not in resp.text
    # ... und meldet seinen Stand an Hilfstechnik.
    assert 'role="progressbar"' in resp.text
    assert 'aria-valuenow="15"' in resp.text
    assert 'aria-valuetext="12 von 100 verarbeitet"' in resp.text


def test_batch_bar_zeigt_die_drei_ausgaenge_als_segmente(client, monkeypatch):
    """Ein Lauf hat drei Ausgänge — der Balken zeigt sie getrennt statt als eine Füllung.

    Sonst erzählt der Balken, 15 % seien erledigt, obwohl nur 12 von 15 tatsächlich
    verarbeitet wurden und einer fehlgeschlagen ist.
    """
    from app.paperless_sync import BatchProgress

    c, application = client
    sync = application.state.sync
    monkeypatch.setattr(type(sync), "recipient_enabled", property(lambda self: True))
    monkeypatch.setattr(type(sync), "recipient_llm_enabled", property(lambda self: True))
    monkeypatch.setattr(
        type(sync),
        "batch_progress",
        property(
            lambda self: BatchProgress(
                running=True, total=100, done=12, failed=1, skipped=2
            )
        ),
    )

    text = c.get("/fragment/empfaenger/batch-status").text
    assert "batch-seg--done" in text and "flex-basis: 12.0%" in text
    assert "batch-seg--skipped" in text and "flex-basis: 2.0%" in text
    assert "batch-seg--failed" in text and "flex-basis: 1.0%" in text
    # Legende nennt nur, was tatsächlich angefallen ist, plus den Rest der Runde.
    assert "2 übersprungen" in text
    assert "1 fehlgeschlagen" in text
    assert "85 in dieser Runde offen" in text


def test_batch_ohne_uebersprungene_zeigt_kein_leeres_segment(client, monkeypatch):
    """Nullwerte gehören weder in den Balken noch in die Legende."""
    from app.paperless_sync import BatchProgress

    c, application = client
    sync = application.state.sync
    monkeypatch.setattr(type(sync), "recipient_enabled", property(lambda self: True))
    monkeypatch.setattr(type(sync), "recipient_llm_enabled", property(lambda self: True))
    monkeypatch.setattr(
        type(sync),
        "batch_progress",
        property(lambda self: BatchProgress(running=True, total=50, done=2)),
    )

    text = c.get("/fragment/empfaenger/batch-status").text
    assert "batch-seg--skipped" not in text
    assert "batch-seg--failed" not in text
    assert "übersprungen" not in text
    assert "fehlgeschlagen" not in text


def test_laufender_batch_ist_fuer_app_js_erkennbar(client, monkeypatch):
    """app.js pollt nur während eines Laufs — dafür braucht es die Markierung im Fragment.

    Ohne sie hinge der Fortschritt wieder allein am SSE-Strom, und ein gepufferter
    Reverse Proxy ließe die Zahl stillstehen, ohne dass etwas nach einem Fehler aussieht.
    """
    from app.paperless_sync import BatchProgress

    c, application = client
    sync = application.state.sync
    monkeypatch.setattr(type(sync), "recipient_enabled", property(lambda self: True))
    monkeypatch.setattr(type(sync), "recipient_llm_enabled", property(lambda self: True))
    monkeypatch.setattr(
        type(sync),
        "batch_progress",
        property(lambda self: BatchProgress(running=True, total=50, done=2)),
    )
    assert "data-batch-running" in c.get("/fragment/empfaenger/batch-status").text

    monkeypatch.setattr(
        type(sync),
        "batch_progress",
        property(lambda self: BatchProgress(running=False)),
    )
    assert "data-batch-running" not in c.get("/fragment/empfaenger/batch-status").text


def test_statische_dateien_tragen_einen_fingerabdruck(client):
    """Ohne Versionsangabe liefert der Browser nach einem Deploy altes CSS/JS aus.

    Starlette setzt für /static kein ``Cache-Control``; Browser cachen dann heuristisch
    und revalidieren stundenlang nicht. Genau daran sind frühere Fixes an app.js
    unsichtbar geblieben: frisches HTML, altes Skript.
    """
    import re

    c, _ = client
    html = c.get("/").text
    treffer = re.findall(r'/static/(app\.css|app\.js)\?v=([0-9a-f]{10})', html)
    assert {name for name, _ in treffer} == {"app.css", "app.js"}
    # Gleicher Inhalt, gleiche URL — sonst waere jeder Seitenaufruf ein Cache-Miss.
    assert c.get("/").text == html


def test_pages_carry_live_status_hint(client):
    """Ein gescheiterter Fragment-Refresh darf nicht stumm bleiben.

    app.js blendet diesen Hinweis ein, wenn ein Refresh fehlschlägt oder die
    SSE-Verbindung abreißt — sonst steht die Seite unbemerkt auf veralteten Daten.
    """
    c, _ = client
    resp = c.get("/")
    assert 'id="live-status"' in resp.text
    assert "hidden" in resp.text
    assert "veraltet" in resp.text
