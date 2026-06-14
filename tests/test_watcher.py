from pathlib import Path

from app.watcher import StabilityTracker, scan_dir


def tracker(window=6.0):
    return StabilityTracker(partial_suffixes=[".tmp", ".part"], stability_window_seconds=window)


def test_file_ready_after_stable_window():
    t = tracker(window=6.0)
    p = Path("/scan-in/a.pdf")
    assert t.poll([(p, 100)], now=0.0) == []  # erstmals gesehen
    assert t.poll([(p, 100)], now=3.0) == []  # noch im Fenster
    assert t.poll([(p, 100)], now=6.0) == [p]  # Fenster erreicht -> bereit


def test_growing_file_resets_window():
    t = tracker(window=6.0)
    p = Path("/scan-in/big.pdf")
    assert t.poll([(p, 100)], now=0.0) == []
    assert t.poll([(p, 200)], now=5.0) == []  # Größe geändert -> Fenster neu
    assert t.poll([(p, 200)], now=10.0) == []
    assert t.poll([(p, 200)], now=11.0) == [p]


def test_partial_suffix_never_ready():
    t = tracker()
    p = Path("/scan-in/a.pdf.part")
    for ts in (0.0, 10.0, 20.0):
        assert t.poll([(p, 100)], now=ts) == []


def test_zero_size_not_ready():
    t = tracker()
    p = Path("/scan-in/empty.pdf")
    assert t.poll([(p, 0)], now=0.0) == []
    assert t.poll([(p, 0)], now=10.0) == []


def test_rename_from_tmp_to_target():
    t = tracker(window=6.0)
    tmp = Path("/scan-in/a.pdf.tmp")
    final = Path("/scan-in/a.pdf")
    t.poll([(tmp, 100)], now=0.0)
    assert t.poll([(final, 100)], now=1.0) == []  # Zielname erstmals gesehen
    assert t.poll([(final, 100)], now=7.0) == [final]


def test_emitted_only_once():
    t = tracker(window=2.0)
    p = Path("/scan-in/a.pdf")
    t.poll([(p, 100)], now=0.0)
    assert t.poll([(p, 100)], now=5.0) == [p]
    assert t.poll([(p, 100)], now=10.0) == []


def test_scan_dir(tmp_path):
    (tmp_path / "a.pdf").write_bytes(b"hello")
    (tmp_path / "sub").mkdir()
    found = scan_dir(tmp_path)
    assert (tmp_path / "a.pdf", 5) in found
    assert all(p.is_file() for p, _ in found)
