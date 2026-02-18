from __future__ import annotations

import re
import unicodedata
from statistics import median
from typing import Any

import numpy as np

MIN_TOKEN_CONFIDENCE = 35


def _normalize_text_for_match(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", "", ascii_text).lower()


def _token_center_x(token: dict[str, Any]) -> float:
    x1, _, x2, _ = token["bbox"]
    return (float(x1) + float(x2)) / 2.0


def _token_center_y(token: dict[str, Any]) -> float:
    _, y1, _, y2 = token["bbox"]
    return (float(y1) + float(y2)) / 2.0


def _line_bbox(tokens: list[dict[str, Any]]) -> list[int]:
    x1 = min(token["bbox"][0] for token in tokens)
    y1 = min(token["bbox"][1] for token in tokens)
    x2 = max(token["bbox"][2] for token in tokens)
    y2 = max(token["bbox"][3] for token in tokens)
    return [int(x1), int(y1), int(x2), int(y2)]


def _cluster_lines_by_y(tokens: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not tokens:
        return []

    heights = [token["bbox"][3] - token["bbox"][1] for token in tokens]
    y_tol = max(10, min(24, int(median(heights) * 0.8)))

    ordered = sorted(tokens, key=lambda token: _token_center_y(token))
    clusters: list[dict[str, Any]] = []
    for token in ordered:
        center_y = _token_center_y(token)
        placed = False
        for cluster in clusters:
            if abs(center_y - cluster["y_center"]) <= y_tol:
                cluster["tokens"].append(token)
                cluster["y_center"] = float(np.mean([_token_center_y(item) for item in cluster["tokens"]]))
                placed = True
                break
        if not placed:
            clusters.append({"line_id": len(clusters) + 1, "y_center": center_y, "tokens": [token]})

    lines: list[dict[str, Any]] = []
    for cluster in clusters:
        line_tokens = sorted(cluster["tokens"], key=lambda token: token["bbox"][0])
        lines.append(
            {
                "line_id": int(cluster["line_id"]),
                "y_center": float(np.mean([_token_center_y(item) for item in line_tokens])),
                "tokens": line_tokens,
                "bbox": _line_bbox(line_tokens),
            }
        )

    lines.sort(key=lambda item: item["y_center"])
    return lines


def _group_tokens_by_line(tokens: list[dict[str, Any]]) -> list[dict[str, Any]]:
    with_line_id = [token for token in tokens if int(token.get("line_id", 0)) > 0]
    unique_line_ids = {int(token["line_id"]) for token in with_line_id}
    if with_line_id and len(unique_line_ids) >= 2:
        groups: dict[int, list[dict[str, Any]]] = {}
        for token in with_line_id:
            groups.setdefault(int(token["line_id"]), []).append(token)
        lines = []
        for line_id, line_tokens in groups.items():
            ordered = sorted(line_tokens, key=lambda token: token["bbox"][0])
            lines.append(
                {
                    "line_id": int(line_id),
                    "y_center": float(np.mean([_token_center_y(item) for item in ordered])),
                    "tokens": ordered,
                    "bbox": _line_bbox(ordered),
                }
            )
        lines.sort(key=lambda item: item["y_center"])
        return lines
    return _cluster_lines_by_y(tokens)


def _match_header_slot(text: str) -> str | None:
    value = _normalize_text_for_match(text)
    if not value:
        return None
    if any(token in value for token in ("description", "designation", "libelle", "article")):
        return "description"
    if any(token in value for token in ("quantite", "qte", "qty", "quant")):
        return "quantity"
    if any(token in value for token in ("prix", "pu", "unitaire", "unit")):
        return "unit_price"
    if any(token in value for token in ("total", "montant", "ttc")):
        return "line_total"
    return None


def _detect_header_and_anchors(lines: list[dict[str, Any]]) -> tuple[int | None, dict[str, float]]:
    best_index: int | None = None
    best_hits = 0
    best_anchors: dict[str, float] = {}

    for index, line in enumerate(lines):
        anchors: dict[str, float] = {}
        for token in line["tokens"]:
            slot = _match_header_slot(token["text"])
            if slot is None or slot in anchors:
                continue
            anchors[slot] = _token_center_x(token)
        if len(anchors) > best_hits:
            best_hits = len(anchors)
            best_index = index
            best_anchors = anchors

    if best_hits < 2:
        return None, {}
    return best_index, best_anchors


def _kmeans_1d(values: list[float], k: int = 4, max_iter: int = 40) -> list[float]:
    if not values:
        return []
    unique_values = sorted(set(values))
    if len(unique_values) <= k:
        return unique_values

    quantiles = np.linspace(0, 1, k + 2)[1:-1]
    centers = [float(np.quantile(values, q)) for q in quantiles]

    for _ in range(max_iter):
        groups: list[list[float]] = [[] for _ in range(k)]
        for value in values:
            best_idx = min(range(k), key=lambda idx: abs(value - centers[idx]))
            groups[best_idx].append(value)
        updated = []
        for idx, bucket in enumerate(groups):
            updated.append(float(np.mean(bucket)) if bucket else centers[idx])
        if np.allclose(updated, centers, atol=0.1):
            centers = updated
            break
        centers = updated
    return sorted(centers)


def _build_column_ranges(
    lines: list[dict[str, Any]],
    header_index: int | None,
    anchors: dict[str, float],
) -> tuple[list[tuple[float, float]], str, list[str]]:
    warnings: list[str] = []
    all_x = [_token_center_x(token) for line in lines for token in line["tokens"]]
    if not all_x:
        return [(-float("inf"), float("inf"))] * 4, "fallback", ["No tokens for column detection."]

    if header_index is not None and anchors:
        q20, q45, q70, q90 = np.quantile(all_x, [0.2, 0.45, 0.7, 0.9])
        ordered = [
            float(anchors.get("description", q20)),
            float(anchors.get("quantity", q45)),
            float(anchors.get("unit_price", q70)),
            float(anchors.get("line_total", q90)),
        ]
        for idx in range(1, len(ordered)):
            if ordered[idx] <= ordered[idx - 1]:
                ordered[idx] = ordered[idx - 1] + 20.0
        centers = ordered
        method = "header"
    else:
        centers = _kmeans_1d(all_x, k=4)
        if len(centers) < 4:
            q20, q45, q70, q90 = np.quantile(all_x, [0.2, 0.45, 0.7, 0.9])
            centers = [float(q20), float(q45), float(q70), float(q90)]
            method = "quantile"
        else:
            method = "kmeans"
        warnings.append("Header not found; column detection fallback used.")

    boundaries = [(centers[idx] + centers[idx + 1]) / 2.0 for idx in range(3)]
    ranges = [
        (-float("inf"), boundaries[0]),
        (boundaries[0], boundaries[1]),
        (boundaries[1], boundaries[2]),
        (boundaries[2], float("inf")),
    ]

    widths = [right - left for left, right in ranges[1:3]]
    if any(width < 20 for width in widths):
        warnings.append("Column ranges may be unstable.")
    return ranges, method, warnings


def _assign_column(token: dict[str, Any], ranges: list[tuple[float, float]]) -> int:
    center_x = _token_center_x(token)
    for index, (left, right) in enumerate(ranges):
        if left <= center_x < right:
            return index
    return len(ranges) - 1


def _fix_numeric_ocr(text: str, quantity_mode: bool = False) -> str:
    value = (text or "").strip()
    if not value:
        return ""
    if re.search(r"\d", value):
        value = value.replace("O", "0").replace("o", "0")
    if quantity_mode or re.fullmatch(r"[0-9Iil|.,\- ]+", value):
        value = re.sub(r"[Iil|]", "1", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _parse_quantity(value: str) -> str:
    cleaned = _fix_numeric_ocr(value, quantity_mode=True)
    match = re.search(r"-?\d+", cleaned.replace(" ", ""))
    if not match:
        return cleaned
    return str(int(match.group(0)))


def _parse_money(value: str) -> str:
    cleaned = _fix_numeric_ocr(value, quantity_mode=False)
    if not cleaned:
        return ""

    number = re.sub(r"[^0-9,.\-]", "", cleaned)
    if not number:
        return cleaned
    if "," in number and "." not in number:
        number = number.replace(",", ".")
    elif "," in number and "." in number:
        if number.rfind(",") > number.rfind("."):
            number = number.replace(".", "").replace(",", ".")
        else:
            number = number.replace(",", "")
    else:
        if number.count(".") > 1:
            parts = number.split(".")
            number = "".join(parts[:-1]) + "." + parts[-1]

    try:
        parsed = float(number)
    except ValueError:
        return cleaned
    return f"{parsed:.2f}"


def _line_to_row(line: dict[str, Any], column_ranges: list[tuple[float, float]]) -> dict[str, Any] | None:
    per_column: dict[int, list[dict[str, Any]]] = {0: [], 1: [], 2: [], 3: []}
    for token in line["tokens"]:
        per_column[_assign_column(token, column_ranges)].append(token)

    description = " ".join(token["text"] for token in sorted(per_column[0], key=lambda item: item["bbox"][0])).strip()
    quantity_raw = " ".join(token["text"] for token in sorted(per_column[1], key=lambda item: item["bbox"][0])).strip()
    unit_raw = " ".join(token["text"] for token in sorted(per_column[2], key=lambda item: item["bbox"][0])).strip()
    total_raw = " ".join(token["text"] for token in sorted(per_column[3], key=lambda item: item["bbox"][0])).strip()

    quantity = _parse_quantity(quantity_raw)
    unit_price = _parse_money(unit_raw)
    line_total = _parse_money(total_raw)

    if not description and not quantity and not unit_price and not line_total:
        return None

    if _match_header_slot(description) in {"description", "quantity", "unit_price", "line_total"}:
        return None

    evidence = {
        "line_id": int(line["line_id"]),
        "bbox": line["bbox"],
        "tokens_by_column": {
            "description": [{"text": token["text"], "bbox": token["bbox"], "conf": token["conf"]} for token in per_column[0]],
            "quantity": [{"text": token["text"], "bbox": token["bbox"], "conf": token["conf"]} for token in per_column[1]],
            "unit_price": [{"text": token["text"], "bbox": token["bbox"], "conf": token["conf"]} for token in per_column[2]],
            "line_total": [{"text": token["text"], "bbox": token["bbox"], "conf": token["conf"]} for token in per_column[3]],
        },
    }

    return {
        "description": description,
        "quantity": quantity,
        "unit_price": unit_price,
        "line_total": line_total,
        "evidence": evidence,
    }


def reconstruct_table(tokens: list[dict[str, Any]], image_shape: tuple[int, ...] | None = None) -> dict[str, Any]:
    warnings: list[str] = []
    filtered = [
        token
        for token in tokens
        if str(token.get("text", "")).strip() and int(token.get("conf", 0)) >= MIN_TOKEN_CONFIDENCE
    ]
    if not filtered:
        return {
            "table_rows_structured": [],
            "table_text_reconstructed": "",
            "warnings": ["No reliable tokens after confidence filtering."],
        }

    lines = _group_tokens_by_line(filtered)
    header_index, anchors = _detect_header_and_anchors(lines)
    if header_index is None:
        warnings.append("Table header not found.")

    ranges, method, range_warnings = _build_column_ranges(lines, header_index, anchors)
    warnings.extend(range_warnings)

    if header_index is not None:
        data_lines = lines[header_index + 1 :]
    else:
        data_lines = lines

    rows: list[dict[str, Any]] = []
    for line in data_lines:
        row = _line_to_row(line, ranges)
        if row is None:
            continue
        if not row["description"] and not row["line_total"] and not row["unit_price"]:
            continue
        rows.append(row)

    if len(rows) < 2:
        warnings.append("Less than two table rows detected.")

    reconstructed_lines = [
        (
            f"LIGNE: {row['description']} | qty={row['quantity'] or '?'} "
            f"| unit={row['unit_price'] or '?'} | total={row['line_total'] or '?'}"
        )
        for row in rows
    ]

    return {
        "table_rows_structured": rows,
        "table_text_reconstructed": "\n".join(reconstructed_lines),
        "warnings": warnings,
        "column_detection_method": method,
    }
