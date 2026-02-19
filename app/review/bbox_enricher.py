from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any

import cv2
import numpy as np

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover - optional runtime dependency
    fitz = None

from app.invoice_ocr.preprocess import preprocess_pipeline
from app.invoice_ocr.tesseract_layout import layout_ocr

OCR_LANGS = (os.getenv("OCR_LANGS") or "fra+eng").strip() or "fra+eng"


@dataclass
class LineCandidate:
    page: int
    text: str
    normalized_text: str
    bbox: list[int]
    confidence: float


def _normalize_text(value: str) -> str:
    ascii_text = (
        unicodedata.normalize("NFKD", str(value or ""))
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    lowered = ascii_text.lower().strip()
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    lowered = re.sub(r"\s+", " ", lowered)
    return lowered.strip()


def _value_variants(value: str) -> list[str]:
    normalized = _normalize_text(value)
    if not normalized:
        return []

    variants = [normalized]
    for chunk in re.split(r"[,;|]", normalized):
        part = chunk.strip()
        if len(part) >= 4 and part not in variants:
            variants.append(part)
    return variants


def _merge_bbox(tokens: list[dict[str, Any]]) -> list[int]:
    x1 = min(int(token["bbox"][0]) for token in tokens)
    y1 = min(int(token["bbox"][1]) for token in tokens)
    x2 = max(int(token["bbox"][2]) for token in tokens)
    y2 = max(int(token["bbox"][3]) for token in tokens)
    return [x1, y1, x2, y2]


def _pdf_to_images(file_path: Path) -> list[np.ndarray]:
    if fitz is None:
        raise RuntimeError("PyMuPDF is required to process PDF files for bbox enrichment.")

    pages: list[np.ndarray] = []
    with fitz.open(file_path) as document:
        for page in document:
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            image_bytes = np.frombuffer(pix.tobytes("png"), dtype=np.uint8)
            image = cv2.imdecode(image_bytes, cv2.IMREAD_COLOR)
            if image is not None:
                pages.append(image)
    return pages


def _load_pages(file_path: Path) -> list[np.ndarray]:
    if not file_path.exists():
        return []

    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        return _pdf_to_images(file_path)

    image = cv2.imread(str(file_path), cv2.IMREAD_COLOR)
    if image is None:
        return []
    return [image]


def _extract_candidates(file_path: Path, lang: str = OCR_LANGS) -> list[LineCandidate]:
    pages = _load_pages(file_path)
    candidates: list[LineCandidate] = []

    for page_idx, image in enumerate(pages, start=1):
        preprocessed, _ = preprocess_pipeline(image, save_debug=False)
        layout = layout_ocr(preprocessed, lang=lang)
        tokens = layout.get("ocr_tokens", [])

        by_line: dict[int, list[dict[str, Any]]] = {}
        for token in tokens:
            line_id = int(token.get("line_id", 0))
            by_line.setdefault(line_id, []).append(token)

        for line_tokens in by_line.values():
            ordered = sorted(line_tokens, key=lambda token: int(token["bbox"][0]))
            text = " ".join(str(token.get("text") or "").strip() for token in ordered).strip()
            normalized_text = _normalize_text(text)
            if not normalized_text:
                continue
            confidences = [int(token.get("conf", 0)) for token in ordered]
            candidates.append(
                LineCandidate(
                    page=page_idx,
                    text=text,
                    normalized_text=normalized_text,
                    bbox=_merge_bbox(ordered),
                    confidence=float(mean(confidences)) / 100.0 if confidences else 0.0,
                )
            )

    return candidates


def _score_variant_to_candidate(variant: str, candidate: LineCandidate) -> float:
    if not variant or not candidate.normalized_text:
        return 0.0

    variant_words = set(variant.split())
    candidate_words = set(candidate.normalized_text.split())
    overlap_ratio = 0.0
    if variant_words:
        overlap_ratio = len(variant_words & candidate_words) / float(len(variant_words))

    if variant in candidate.normalized_text:
        containment_bonus = 0.25
    elif candidate.normalized_text in variant:
        containment_bonus = 0.2
    else:
        containment_bonus = 0.0

    char_match = 0.0
    max_len = max(len(variant), len(candidate.normalized_text), 1)
    min_len = min(len(variant), len(candidate.normalized_text), 1)
    if min_len > 0:
        char_match = min_len / max_len

    score = (overlap_ratio * 0.6) + (containment_bonus) + (char_match * 0.2)
    return min(score * 100.0, 100.0)


def enrich_fields_with_bboxes(
    file_path: Path,
    field_values: dict[str, Any],
    *,
    min_score: float = 55.0,
) -> dict[str, dict[str, Any]]:
    candidates = _extract_candidates(file_path)
    if not candidates:
        return {}

    results: dict[str, dict[str, Any]] = {}

    for field_key, raw_value in field_values.items():
        value = "" if raw_value is None else str(raw_value)
        variants = _value_variants(value)
        if not variants:
            continue

        best_candidate: LineCandidate | None = None
        best_score = 0.0

        for candidate in candidates:
            local_best = max(
                (_score_variant_to_candidate(variant, candidate) for variant in variants),
                default=0.0,
            )
            if local_best > best_score:
                best_score = local_best
                best_candidate = candidate

        if best_candidate is None or best_score < min_score:
            continue

        results[field_key] = {
            "bbox": best_candidate.bbox,
            "page": best_candidate.page,
            "bbox_relative": False,
            "confidence": round(best_candidate.confidence, 4),
            "bbox_score": round(best_score, 2),
        }

    return results
