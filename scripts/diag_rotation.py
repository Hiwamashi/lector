"""Diagnose: Wie verhält sich Lectors autorotate() auf echten PDF-Quellen?

Rendert jede Seite exakt wie die Pipeline (pages.render_pdf) und prüft:
 - den /Rotate-Wert der PDF-Seite (pikepdf)
 - ob pypdfium2 beim Rendern bereits aufrecht liefert
 - welche Drehung autorotate() WÄHLEN würde (0/90/180/270)
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pikepdf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pages import render_pdf  # noqa: E402


def _horizontal_band_variance(gray: np.ndarray) -> float:
    """Maß der früheren autorotate-Heuristik (zur Diagnose nachgebildet)."""
    inverted = 255 - gray
    row_sums = inverted.sum(axis=1, dtype=np.float64)
    return float(np.var(row_sums))


def autorotate_choice(img):
    gray = np.array(img.convert("L"))
    candidates = {
        0: gray,
        90: np.rot90(gray, k=-1),
        180: np.rot90(gray, k=2),
        270: np.rot90(gray, k=1),
    }
    scores = {a: _horizontal_band_variance(g) for a, g in candidates.items()}
    best = max(candidates, key=lambda a: scores[a])
    return best, scores


def rotate_values(path: Path) -> list[int]:
    out = []
    with pikepdf.open(str(path)) as pdf:
        for page in pdf.pages:
            out.append(int(page.get("/Rotate", 0)))
    return out


def main(files: list[str]) -> None:
    for f in files:
        p = Path(f)
        try:
            rotates = rotate_values(p)
            imgs = render_pdf(p)
        except Exception as e:  # noqa: BLE001
            print(f"FEHLER {p.name}: {e}")
            continue
        for i, img in enumerate(imgs):
            best, scores = autorotate_choice(img)
            rot = rotates[i] if i < len(rotates) else "?"
            flag = "  <-- autorotate DREHT" if best != 0 else ""
            print(
                f"{p.name} | Seite {i}: /Rotate={rot} | gerendert={img.size} "
                f"| autorotate->{best}{flag}"
            )


if __name__ == "__main__":
    main(sys.argv[1:])
