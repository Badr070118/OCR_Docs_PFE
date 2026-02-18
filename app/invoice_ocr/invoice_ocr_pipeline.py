from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover - optional runtime dependency
    fitz = None

from app.invoice_ocr.preprocess import preprocess_pipeline
from app.invoice_ocr.table_reconstruct import reconstruct_table
from app.invoice_ocr.tesseract_layout import layout_ocr


def _load_pdf_pages(path: Path) -> list[np.ndarray]:
    if fitz is None:
        raise RuntimeError("PyMuPDF is required to process PDF invoices.")

    pages: list[np.ndarray] = []
    document = fitz.open(path)
    try:
        for page in document:
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            image_bytes = np.frombuffer(pix.tobytes("png"), dtype=np.uint8)
            image = cv2.imdecode(image_bytes, cv2.IMREAD_COLOR)
            if image is not None:
                pages.append(image)
    finally:
        document.close()
    return pages


def _load_images(file_path: str) -> list[np.ndarray]:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {file_path}")

    if path.suffix.lower() == ".pdf":
        pages = _load_pdf_pages(path)
        if not pages:
            raise RuntimeError("No renderable pages found in PDF.")
        return pages

    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError(f"Unable to open image file: {file_path}")
    return [image]


def _merge_quality_metrics(per_page_metrics: list[dict[str, Any]]) -> dict[str, Any]:
    if not per_page_metrics:
        return {"mean_conf": 0.0, "low_conf_ratio": 1.0, "deskew_angle": 0.0}

    weights = [max(1, int(metric.get("token_count", 1))) for metric in per_page_metrics]
    total_weight = float(sum(weights))

    mean_conf = sum(metric.get("mean_conf", 0.0) * weight for metric, weight in zip(per_page_metrics, weights)) / total_weight
    low_conf_ratio = (
        sum(metric.get("low_conf_ratio", 1.0) * weight for metric, weight in zip(per_page_metrics, weights))
        / total_weight
    )
    deskew_angle = float(np.mean([metric.get("deskew_angle", 0.0) for metric in per_page_metrics]))

    return {
        "mean_conf": round(float(mean_conf), 3),
        "low_conf_ratio": round(float(low_conf_ratio), 4),
        "deskew_angle": round(deskew_angle, 3),
    }


def invoice_ocr(
    image_path: str,
    *,
    lang: str = "fra+eng",
    save_debug: bool = True,
    debug_root_dir: str = "results/invoice_table_debug",
) -> dict[str, Any]:
    pages = _load_images(image_path)
    stem = Path(image_path).stem

    full_raw_text: list[str] = []
    all_tokens: list[dict[str, Any]] = []
    all_rows: list[dict[str, Any]] = []
    all_reconstructed_lines: list[str] = []
    all_warnings: list[str] = []
    preprocess_debug_paths: dict[str, Any] = {}
    quality_per_page: list[dict[str, Any]] = []
    line_offset = 0

    for page_idx, page_image in enumerate(pages, start=1):
        page_debug_dir = str(Path(debug_root_dir) / f"{stem}_page_{page_idx}")
        preprocessed, pre_meta = preprocess_pipeline(
            page_image,
            save_debug=save_debug,
            debug_dir=page_debug_dir,
        )
        preprocess_debug_paths[f"page_{page_idx}"] = pre_meta.get("preprocess_debug_paths", {})

        layout = layout_ocr(preprocessed, lang=lang)
        table = reconstruct_table(layout.get("ocr_tokens", []), image_shape=preprocessed.shape)

        page_raw_text = str(layout.get("ocr_text_raw", "")).strip()
        if page_raw_text:
            full_raw_text.append(page_raw_text)

        page_tokens: list[dict[str, Any]] = []
        for token in layout.get("ocr_tokens", []):
            new_token = dict(token)
            new_token["page"] = page_idx
            new_token["line_id"] = int(new_token.get("line_id", 0)) + line_offset
            page_tokens.append(new_token)
        all_tokens.extend(page_tokens)

        if page_tokens:
            max_line = max(int(token.get("line_id", 0)) for token in page_tokens)
            line_offset = max(line_offset, max_line + 1)

        page_rows = table.get("table_rows_structured", [])
        for row in page_rows:
            row_copy = dict(row)
            row_copy["page"] = page_idx
            all_rows.append(row_copy)

        if table.get("table_text_reconstructed"):
            for line in str(table["table_text_reconstructed"]).splitlines():
                all_reconstructed_lines.append(f"[page {page_idx}] {line}")

        for warning in layout.get("warnings", []):
            all_warnings.append(f"page {page_idx}: {warning}")

        page_warnings = list(table.get("warnings", []))
        for warning in page_warnings:
            all_warnings.append(f"page {page_idx}: {warning}")

        page_quality = dict(layout.get("quality_metrics", {}))
        page_quality["deskew_angle"] = float(pre_meta.get("deskew_angle", 0.0))
        quality_per_page.append(page_quality)

    if not all_rows:
        all_warnings.append("Table reconstruction produced no rows; fallback to raw OCR text only.")

    table_text_reconstructed = "\n".join(all_reconstructed_lines).strip()
    if not table_text_reconstructed:
        table_text_reconstructed = "\n".join(full_raw_text).strip()

    return {
        "ocr_text_raw": "\n\n".join(full_raw_text).strip(),
        "ocr_tokens": all_tokens,
        "table_rows_structured": all_rows,
        "table_text_reconstructed": table_text_reconstructed,
        "preprocess_debug_paths": preprocess_debug_paths,
        "quality_metrics": _merge_quality_metrics(quality_per_page),
        "warnings": all_warnings,
    }
