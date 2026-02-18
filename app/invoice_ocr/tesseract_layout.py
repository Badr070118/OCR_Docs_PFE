from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Any

import cv2
import numpy as np

try:
    import pytesseract
except ImportError:  # pragma: no cover - runtime dependency
    pytesseract = None


@dataclass
class _PassResult:
    psm: int
    tokens: list[dict[str, Any]]
    ocr_text_raw: str
    mean_conf: float
    low_conf_ratio: float
    empty_ratio: float
    token_count: int
    score: float


def _parse_conf(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return -1.0


def _normalize_token_text(value: Any) -> str:
    return str(value or "").strip()


def _tokens_from_tesseract_data(data: dict[str, list[Any]]) -> tuple[list[dict[str, Any]], int]:
    line_id_map: dict[tuple[int, int, int], int] = {}
    next_line_id = 1
    tokens: list[dict[str, Any]] = []
    empty_entries = 0

    total = len(data.get("text", []))
    for index in range(total):
        text = _normalize_token_text(data["text"][index])
        conf = _parse_conf(data["conf"][index])
        if not text:
            empty_entries += 1
            continue

        left = int(data["left"][index])
        top = int(data["top"][index])
        width = int(data["width"][index])
        height = int(data["height"][index])
        block_num = int(data["block_num"][index])
        par_num = int(data["par_num"][index])
        line_num = int(data["line_num"][index])

        key = (block_num, par_num, line_num)
        if key not in line_id_map:
            line_id_map[key] = next_line_id
            next_line_id += 1

        tokens.append(
            {
                "text": text,
                "conf": int(round(conf if conf >= 0 else 0)),
                "bbox": [left, top, left + width, top + height],
                "line_id": line_id_map[key],
                "block_num": block_num,
                "par_num": par_num,
                "line_num": line_num,
            }
        )

    tokens.sort(key=lambda item: (item["bbox"][1], item["bbox"][0]))
    return tokens, empty_entries


def _build_raw_text(tokens: list[dict[str, Any]]) -> str:
    by_line: dict[int, list[dict[str, Any]]] = {}
    for token in tokens:
        by_line.setdefault(int(token["line_id"]), []).append(token)

    lines: list[str] = []
    for line_id in sorted(by_line):
        line_tokens = sorted(by_line[line_id], key=lambda item: item["bbox"][0])
        line_text = " ".join(token["text"] for token in line_tokens).strip()
        if line_text:
            lines.append(line_text)
    return "\n".join(lines)


def _run_tesseract_pass(image: np.ndarray, lang: str, psm: int) -> _PassResult:
    if pytesseract is None:
        raise RuntimeError("pytesseract is not available.")

    config = f"--oem 3 --psm {psm}"
    data = pytesseract.image_to_data(
        image,
        lang=lang,
        config=config,
        output_type=pytesseract.Output.DICT,
    )

    tokens, empty_entries = _tokens_from_tesseract_data(data)
    confidences = [token["conf"] for token in tokens if token["conf"] >= 0]
    mean_conf = float(mean(confidences)) if confidences else 0.0
    low_conf_ratio = (
        float(sum(1 for value in confidences if value < 50) / len(confidences))
        if confidences
        else 1.0
    )

    total_entries = len(data.get("text", []))
    empty_ratio = float(empty_entries / max(1, total_entries))
    token_count = len(tokens)
    score = mean_conf - (empty_ratio * 25.0) - (low_conf_ratio * 10.0)
    raw_text = _build_raw_text(tokens)

    return _PassResult(
        psm=psm,
        tokens=tokens,
        ocr_text_raw=raw_text,
        mean_conf=mean_conf,
        low_conf_ratio=low_conf_ratio,
        empty_ratio=empty_ratio,
        token_count=token_count,
        score=score,
    )


def layout_ocr(
    image: np.ndarray,
    lang: str = "fra+eng",
) -> dict[str, Any]:
    if image.ndim == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image.copy()

    warnings: list[str] = []
    candidates: list[_PassResult] = []
    for psm in (6, 4):
        try:
            candidates.append(_run_tesseract_pass(gray, lang=lang, psm=psm))
        except Exception as exc:
            warnings.append(f"Tesseract pass psm={psm} failed: {exc}")

    if not candidates:
        raise RuntimeError("All Tesseract layout passes failed.")

    selected = max(candidates, key=lambda item: item.score)

    return {
        "ocr_text_raw": selected.ocr_text_raw,
        "ocr_tokens": selected.tokens,
        "warnings": warnings,
        "quality_metrics": {
            "mean_conf": round(selected.mean_conf, 3),
            "low_conf_ratio": round(selected.low_conf_ratio, 4),
            "token_count": selected.token_count,
            "selected_psm": selected.psm,
            "psm_candidates": [
                {
                    "psm": candidate.psm,
                    "mean_conf": round(candidate.mean_conf, 3),
                    "low_conf_ratio": round(candidate.low_conf_ratio, 4),
                    "token_count": candidate.token_count,
                    "score": round(candidate.score, 3),
                }
                for candidate in candidates
            ],
        },
    }
