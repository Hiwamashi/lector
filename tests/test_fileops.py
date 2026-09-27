import io

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

