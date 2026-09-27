import io
import threading
from pathlib import Path

import pytest

from app.fileops import sanitize_upload_filename, store_upload

# --- sanitize_upload_filename -------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "..",
        ".",
        "...",
        "",
        "   ",
    ],
)
def test_sanitize_upload_filename_liefert_leeren_string_fuer_unbrauchbare_namen(raw):
    assert sanitize_upload_filename(raw) == ""


def test_sanitize_upload_filename_behaelt_nur_letzten_bestandteil_bei_slash():
    # Nur der letzte Pfadbestandteil zählt — Traversal-Anteile davor werden
    # verworfen, nicht als "unbrauchbar" gewertet, da am Ende ein gewöhnlicher
    # Dateiname übrig bleibt.
    assert sanitize_upload_filename("a/b/c.pdf") == "c.pdf"
    assert sanitize_upload_filename("../../data/lector.db") == "lector.db"


def test_sanitize_upload_filename_behaelt_nur_letzten_bestandteil_bei_backslash():
    assert sanitize_upload_filename("..\\..\\x.pdf") == "x.pdf"


def test_sanitize_upload_filename_laesst_gewoehnlichen_namen_unveraendert():
    assert sanitize_upload_filename("Rechnung Mai.pdf") == "Rechnung Mai.pdf"


def test_sanitize_upload_filename_laesst_umlaute_unveraendert():
    assert sanitize_upload_filename("Angebot_Müller.pdf") == "Angebot_Müller.pdf"


# --- store_upload --------------------------------------------------------------


def test_store_upload_schreibt_zieldatei_ohne_teil_suffix(tmp_path):
    content = b"hallo welt" * 1000
    source = io.BytesIO(content)

    result = store_upload(source, tmp_path, "beleg.pdf", partial_suffix=".part", chunk_size=16)

    assert result == tmp_path / "beleg.pdf"
    assert result.read_bytes() == content
    reste = [p.name for p in tmp_path.iterdir() if p.name != "beleg.pdf"]
    assert reste == []


class _VerzeichnisPruefendeQuelle:
    """Simuliert einen Upload-Stream, dessen erster read()-Aufruf prüft, dass
    unter dem Zielnamen noch keine Datei existiert."""

    def __init__(self, directory, target_name, chunks):
        self._directory = directory
        self._target_name = target_name
        self._chunks = list(chunks)
        self._checked = False

    def read(self, size=-1):
        if not self._checked:
            self._checked = True
            assert not (self._directory / self._target_name).exists()
        if self._chunks:
            return self._chunks.pop(0)
        return b""


def test_store_upload_zieldatei_existiert_erst_nach_abschluss(tmp_path):
    source = _VerzeichnisPruefendeQuelle(tmp_path, "beleg.pdf", [b"abc", b"def"])

    result = store_upload(source, tmp_path, "beleg.pdf", partial_suffix=".part")

    assert result.read_bytes() == b"abcdef"


class _FehlerhafteQuelle:
    def read(self, size=-1):
        raise OSError("Verbindung abgebrochen")


def test_store_upload_raeumt_bei_oserror_auf_und_reicht_ihn_weiter(tmp_path):
    source = _FehlerhafteQuelle()

    with pytest.raises(OSError, match="Verbindung abgebrochen"):
        store_upload(source, tmp_path, "beleg.pdf", partial_suffix=".part")

    assert list(tmp_path.iterdir()) == []


def test_store_upload_weicht_bei_belegter_teildatei_aus(tmp_path):
    # Leiche eines abgebrochenen früheren Uploads.
    (tmp_path / "beleg.pdf.part").write_bytes(b"alter rest")

    source = io.BytesIO(b"neuer inhalt")
    result = store_upload(source, tmp_path, "beleg.pdf", partial_suffix=".part")

    assert result == tmp_path / "beleg.pdf"
    assert result.read_bytes() == b"neuer inhalt"
    # Die Leiche bleibt unangetastet liegen.
    assert (tmp_path / "beleg.pdf.part").read_bytes() == b"alter rest"


def test_store_upload_keine_kollision_bestehende_datei_bleibt_unveraendert(tmp_path):
    (tmp_path / "beleg.pdf").write_bytes(b"vorhandener inhalt")

    source = io.BytesIO(b"neuer inhalt")
    result = store_upload(source, tmp_path, "beleg.pdf", partial_suffix=".part")

    assert result == tmp_path / "beleg_1.pdf"
    assert (tmp_path / "beleg.pdf").read_bytes() == b"vorhandener inhalt"
    assert result.read_bytes() == b"neuer inhalt"


class _BlockierendeQuelle:
    """Liefert genau einen Datenblock, blockiert davor aber bis `release_event`
    gesetzt wird, und meldet über `entered_event` den Eintritt in die Blockade.
    Damit lassen sich zwei Threads deterministisch so anhalten, dass sich ihre
    Schreibphasen nachweislich überlappen, statt auf echtes Timing zu hoffen."""

    def __init__(self, data: bytes, entered_event: threading.Event, release_event: threading.Event):
        self._data = data
        self._served = False
        self._entered_event = entered_event
        self._release_event = release_event

    def read(self, size=-1):
        if not self._served:
            self._served = True
            self._entered_event.set()
            assert self._release_event.wait(timeout=5), "release_event kam nicht rechtzeitig"
            return self._data
        return b""


def test_store_upload_gleichzeitige_uploads_gleichen_namens_ueberschreiben_sich_nicht(tmp_path):
    entered_a, release_a = threading.Event(), threading.Event()
    entered_b, release_b = threading.Event(), threading.Event()
    quelle_a = _BlockierendeQuelle(b"inhalt a", entered_a, release_a)
    quelle_b = _BlockierendeQuelle(b"inhalt b", entered_b, release_b)
    ergebnisse: dict[str, object] = {}

    def worker(schluessel, quelle):
        ergebnisse[schluessel] = store_upload(quelle, tmp_path, "beleg.pdf", partial_suffix=".part")

    thread_a = threading.Thread(target=worker, args=("a", quelle_a))
    thread_b = threading.Thread(target=worker, args=("b", quelle_b))

    # a schreibt bereits (Zwischendatei liegt, Ziel "beleg.pdf" existiert noch nicht),
    # bevor b startet und ebenfalls "beleg.pdf" als freien Zielnamen sieht — die
    # Überlappung ist damit garantiert, nicht nur wahrscheinlich.
    thread_a.start()
    assert entered_a.wait(timeout=5)
    thread_b.start()
    assert entered_b.wait(timeout=5)

    # b wird zuerst fertig und belegt "beleg.pdf"; a muss danach unter Lock einen
    # neuen freien Namen bekommen, statt bs gerade geschriebene Datei zu überschreiben.
    release_b.set()
    thread_b.join(timeout=5)
    release_a.set()
    thread_a.join(timeout=5)

    assert not thread_a.is_alive()
    assert not thread_b.is_alive()

    namen = {ergebnisse["a"].name, ergebnisse["b"].name}
    assert namen == {"beleg.pdf", "beleg_1.pdf"}
    inhalte = {ergebnisse["a"].read_bytes(), ergebnisse["b"].read_bytes()}
    assert inhalte == {b"inhalt a", b"inhalt b"}


def test_store_upload_gleichzeitiges_anlegen_des_zwischenpfads_vermischt_nicht(
    tmp_path, monkeypatch
):
    """Fund 1 der Schlussreview: Vor der Behebung prüfte `store_upload()` im
    Schleifenkopf nur `partial.exists()` und öffnete die Zwischendatei erst danach mit
    `open("wb")` — ein klassisches TOCTOU-Fenster. Zwei gleichzeitige Uploads desselben
    Namens, deren `exists()`-Prüfung sich überlappt, hätten dieselbe Zwischendatei
    beide mit `"wb"` (nicht-exklusiv, ab Offset 0) geöffnet und ihre Inhalte
    vermischt — nicht nur verzögert wie beim bereits getesteten `_replace_lock`.

    Dieser Test erzwingt das Überlappen nicht über Timing, sondern über eine
    `threading.Barrier`: beide Threads rufen den echten `Path.open("xb", ...)`-Syscall
    für denselben Zwischenpfad exakt gleichzeitig auf. Die Behebung ersetzt den
    Check-dann-Öffnen durch ein exklusives `open(..., "xb")`; das Betriebssystem
    garantiert, dass davon höchstens einer gewinnt — der andere bekommt sofort
    `FileExistsError` und weicht deterministisch auf einen neuen Zwischenpfad aus,
    statt in denselben Dateideskriptor zu schreiben."""
    barrier = threading.Barrier(2, timeout=5)
    original_open = Path.open
    gate_lock = threading.Lock()
    gate_count = 0

    def gate_open(self, mode="r", *args, **kwargs):
        nonlocal gate_count
        anlegen_versuch = mode == "xb" and self.name.startswith("beleg.pdf")
        if anlegen_versuch:
            with gate_lock:
                erste_zwei = gate_count < 2
                gate_count += 1
            if erste_zwei:
                # Nur die jeweils ERSTE Anlegen-Versuch je Thread wird synchronisiert —
                # ein Nachschlag mit ausweichendem Namen (z.B. "beleg.pdf_1.part") nach
                # FileExistsError soll nicht erneut auf einen (nie kommenden) zweiten
                # Partner warten.
                barrier.wait()
        return original_open(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", gate_open)

    ergebnisse: dict[str, Path] = {}

    def worker(schluessel, inhalt):
        quelle = io.BytesIO(inhalt)
        ergebnisse[schluessel] = store_upload(
            quelle, tmp_path, "beleg.pdf", partial_suffix=".part"
        )

    thread_a = threading.Thread(target=worker, args=("a", b"inhalt a"))
    thread_b = threading.Thread(target=worker, args=("b", b"inhalt b"))
    thread_a.start()
    thread_b.start()
    thread_a.join(timeout=5)
    thread_b.join(timeout=5)

    assert not thread_a.is_alive()
    assert not thread_b.is_alive()

    namen = {ergebnisse["a"].name, ergebnisse["b"].name}
    assert namen == {"beleg.pdf", "beleg_1.pdf"}
    inhalte = {ergebnisse["a"].read_bytes(), ergebnisse["b"].read_bytes()}
    assert inhalte == {b"inhalt a", b"inhalt b"}

