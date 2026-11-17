import numpy as np
from PIL import Image, ImageDraw

from app.config import Settings
from app.preprocessing import (
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


def test_enhance_contrast_returns_grayscale():
    page = _text_page()
    out = enhance_contrast(page)
    assert out.mode == "L"


def _colored_page() -> Image.Image:
    page = _text_page()
    ImageDraw.Draw(page).rectangle([400, 20, 560, 70], fill=(220, 30, 30))
    return page


def test_preprocess_page_respects_flags():
    page = _text_page()
    settings = Settings(PREPROCESS_DESKEW="false", PREPROCESS_CONTRAST="false")
    out = preprocess_page(page, settings)
    # Ohne aktive Schritte bleiben beide Bilder unverändert (gleiche Größe, RGB)
    for img in (out.visible, out.ocr):
        assert img.size == page.size
        assert img.mode == "RGB"
        assert np.array_equal(np.array(img), np.array(page))


def test_contrast_only_affects_the_ocr_image():
    page = _colored_page()
    settings = Settings(PREPROCESS_DESKEW="false", PREPROCESS_CONTRAST="true")
    out = preprocess_page(page, settings)
    assert out.ocr.mode == "L"
    assert out.visible.mode == "RGB"
    assert out.visible.getpixel((480, 45)) == (220, 30, 30)


def test_visible_layer_ignores_the_contrast_switch():
    page = _colored_page()
    an = preprocess_page(page, Settings(PREPROCESS_CONTRAST="true"))
    aus = preprocess_page(page, Settings(PREPROCESS_CONTRAST="false"))
    assert np.array_equal(np.array(an.visible), np.array(aus.visible))


def test_deskew_applies_identically_to_both_images():
    skewed = _colored_page().rotate(-7, expand=False, fillcolor="white")
    out = preprocess_page(skewed, Settings(PREPROCESS_DESKEW="true", PREPROCESS_CONTRAST="true"))
    assert out.visible.size == out.ocr.size == skewed.size
    assert out.visible.mode == "RGB"
    for img in (out.visible, out.ocr):
        assert abs(estimate_skew_angle(np.array(img.convert("L")))) < 2.0
    # Gleiche Geometrie: Die OCR-Eingabe ist exakt die Graustufen-/CLAHE-Fassung der
    # sichtbaren Ebene.
    assert np.array_equal(np.array(out.ocr), np.array(enhance_contrast(out.visible)))
