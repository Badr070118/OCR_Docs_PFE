from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import cv2
import numpy as np


def to_gray(img: np.ndarray) -> np.ndarray:
    if img.ndim == 2:
        return img.copy()
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def enhance_contrast(img: np.ndarray) -> np.ndarray:
    gray = to_gray(img)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return clahe.apply(gray)


def denoise(img: np.ndarray) -> np.ndarray:
    gray = to_gray(img)
    return cv2.fastNlMeansDenoising(gray, None, h=12, templateWindowSize=7, searchWindowSize=21)


def adaptive_binarize(img: np.ndarray) -> np.ndarray:
    gray = to_gray(img)
    return cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        35,
        11,
    )


def deskew(img: np.ndarray) -> tuple[np.ndarray, float]:
    gray = to_gray(img)
    inv = cv2.bitwise_not(gray)
    _, thresh = cv2.threshold(inv, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    coords = np.column_stack(np.where(thresh > 0))
    if coords.shape[0] < 50:
        return gray, 0.0

    angle = cv2.minAreaRect(coords)[-1]
    if angle < -45:
        angle = -(90 + angle)
    else:
        angle = -angle

    (h, w) = gray.shape[:2]
    center = (w // 2, h // 2)
    matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    rotated = cv2.warpAffine(
        gray,
        matrix,
        (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=255,
    )
    return rotated, float(angle)


def sharpen(img: np.ndarray) -> np.ndarray:
    gray = to_gray(img)
    kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]], dtype=np.float32)
    return cv2.filter2D(gray, -1, kernel)


def _save_debug_image(path: Path, image: np.ndarray) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), image)
    return str(path)


def preprocess_pipeline(
    img: np.ndarray,
    save_debug: bool = True,
    debug_dir: str | os.PathLike[str] | None = None,
) -> tuple[np.ndarray, dict[str, Any]]:
    gray = to_gray(img)
    contrasted = enhance_contrast(gray)
    denoised = denoise(contrasted)
    deskewed, angle = deskew(denoised)
    sharpened = sharpen(deskewed)
    binary = adaptive_binarize(sharpened)

    debug_paths: dict[str, str] = {}
    if save_debug:
        target_dir = Path(debug_dir or "results/invoice_preprocess_debug")
        debug_paths["gray"] = _save_debug_image(target_dir / "01_gray.png", gray)
        debug_paths["contrast"] = _save_debug_image(target_dir / "02_contrast.png", contrasted)
        debug_paths["denoise"] = _save_debug_image(target_dir / "03_denoise.png", denoised)
        debug_paths["deskew"] = _save_debug_image(target_dir / "04_deskew.png", deskewed)
        debug_paths["sharpen"] = _save_debug_image(target_dir / "05_sharpen.png", sharpened)
        debug_paths["final_binary"] = _save_debug_image(target_dir / "06_final_binary.png", binary)

    return binary, {"deskew_angle": angle, "preprocess_debug_paths": debug_paths}
