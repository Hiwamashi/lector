"""Bildvorverarbeitung pro Seite vor der OCR (siehe PRD §3.1):
Deskew (Schieflagenkorrektur), Auto-Rotate (Orientierung), Kontrast/Graustufen.

Alle Schritte sind über die Settings-Flags einzeln schaltbar. Funktionen arbeiten auf
PIL-Bildern; intern wird für OpenCV nach numpy konvertiert.

Hinweis zu Auto-Rotate: Die Orientierung wird heuristisch über das horizontale
Projektionsprofil bestimmt (Textzeilen erzeugen starke horizontale Bänderung). Das
korrigiert zuverlässig Hoch-/Querformat-Verdrehungen (90°/270°); eine 180°-Drehung lässt
sich ohne semantische Texterkennung nicht unterscheiden und bleibt unverändert.
"""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

from .config import Settings


def _pil_to_gray(img: Image.Image) -> np.ndarray:
    arr = np.array(img.convert("L"))
    return arr


def estimate_skew_angle(gray: np.ndarray) -> float:
    """Schätzt den Schieflagenwinkel in Grad über die minimale umschließende Box der
    Textpixel. Rückgabe im Bereich (-45, 45]."""
    inverted = cv2.bitwise_not(gray)
    thresh = cv2.threshold(inverted, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
    coords = np.column_stack(np.where(thresh > 0))
    if coords.shape[0] < 50:
        return 0.0
    angle = cv2.minAreaRect(coords.astype(np.float32))[-1]
    if angle < -45:
        angle = 90 + angle
    elif angle > 45:
        angle = angle - 90
    return float(angle)


def deskew(img: Image.Image) -> Image.Image:
    gray = _pil_to_gray(img)
    angle = estimate_skew_angle(gray)
    if abs(angle) < 0.1:
        return img
    arr = np.array(img)
    h, w = arr.shape[:2]
    center = (w / 2, h / 2)
    # np.where liefert (row, col); minAreaRect interpretiert sie als (x, y), wodurch der
    # Winkel gespiegelt ist. Zur Korrektur wird daher mit negativem Winkel zurückgedreht.
    matrix = cv2.getRotationMatrix2D(center, -angle, 1.0)
    rotated = cv2.warpAffine(
        arr, matrix, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
    )
    return Image.fromarray(rotated)


def _horizontal_band_variance(gray: np.ndarray) -> float:
    """Varianz des zeilenweisen Tintenanteils. Hoch, wenn Textzeilen horizontal liegen."""
    inverted = 255 - gray
    row_sums = inverted.sum(axis=1, dtype=np.float64)
    return float(np.var(row_sums))


def autorotate(img: Image.Image) -> Image.Image:
    """Wählt aus 0°/90°/180°/270° die Drehung mit der stärksten horizontalen Bänderung."""
    gray = _pil_to_gray(img)
    candidates = {
        0: gray,
        90: np.rot90(gray, k=-1),
        180: np.rot90(gray, k=2),
        270: np.rot90(gray, k=1),
    }
    best_angle = max(candidates, key=lambda a: _horizontal_band_variance(candidates[a]))
    if best_angle == 0:
        return img
    # PIL.rotate dreht gegen den Uhrzeigersinn; expand=True erhält den Inhalt.
    return img.rotate(-best_angle, expand=True)


def enhance_contrast(img: Image.Image) -> Image.Image:
    """Graustufen-Umwandlung mit CLAHE (lokaler Kontrastausgleich)."""
    gray = _pil_to_gray(img)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    out = clahe.apply(gray)
    return Image.fromarray(out)


def preprocess_page(img: Image.Image, settings: Settings) -> Image.Image:
    result = img
    if settings.preprocess_autorotate:
        result = autorotate(result)
    if settings.preprocess_deskew:
        result = deskew(result)
    if settings.preprocess_contrast:
        result = enhance_contrast(result)
    return result
