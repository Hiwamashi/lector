import numpy as np
from PIL import Image, ImageDraw

from app.config import Settings
from app.preprocessing import (
    autorotate,
    deskew,
    enhance_contrast,
    estimate_skew_angle,
    preprocess_page,
)


def _text_page(width=600, height=800) -> Image.Image:
    """Erzeugt eine weiße Seite mit mehreren horizontalen schwarzen 'Textzeilen'."""
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    for y in range(80, height - 80, 60):
        draw.rectangle([60, y, width - 60, y + 18], fill="black")
    return img


def test_estimate_skew_on_straight_page():
    page = _text_page()
    gray = np.array(page.convert("L"))
    assert abs(estimate_skew_angle(gray)) < 1.0


def test_deskew_corrects_rotation():
    page = _text_page()
    skewed = page.rotate(-7, expand=False, fillcolor="white")
    corrected = deskew(skewed)
    residual = estimate_skew_angle(np.array(corrected.convert("L")))
    assert abs(residual) < 2.0


def test_autorotate_fixes_landscape():
    page = _text_page()  # Hochformat mit horizontalen Zeilen
    rotated = page.rotate(90, expand=True)  # jetzt Querformat
    fixed = autorotate(rotated)
    # nach Korrektur sollte es wieder höher als breit sein (Hochformat)
    assert fixed.height > fixed.width


def test_enhance_contrast_returns_grayscale():
    page = _text_page()
    out = enhance_contrast(page)
    assert out.mode == "L"


def test_preprocess_page_respects_flags():
    page = _text_page()
    settings = Settings(
        PREPROCESS_DESKEW="false", PREPROCESS_AUTOROTATE="false", PREPROCESS_CONTRAST="false"
    )
    out = preprocess_page(page, settings)
    # Ohne aktive Schritte bleibt das Bild unverändert (gleiche Größe, RGB)
    assert out.size == page.size
    assert out.mode == "RGB"
