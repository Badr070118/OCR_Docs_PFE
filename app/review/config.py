from __future__ import annotations

import os
from pathlib import Path


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


REVIEW_FEATURE_ENABLED = _as_bool(os.getenv("REVIEW_FEATURE_ENABLED"), True)
FUZZY_THRESHOLD = int(os.getenv("FUZZY_THRESHOLD", "85"))
FUZZY_MODE_DEFAULT = (os.getenv("FUZZY_MODE_DEFAULT") or "suggest").strip().lower()
if FUZZY_MODE_DEFAULT not in {"suggest", "apply"}:
    FUZZY_MODE_DEFAULT = "suggest"

REVIEW_FILE_MATCH_WINDOW_SECONDS = int(
    os.getenv("REVIEW_FILE_MATCH_WINDOW_SECONDS", "900")
)
REVIEW_BBOX_ENRICH_ENABLED = _as_bool(os.getenv("REVIEW_BBOX_ENRICH_ENABLED"), True)
REVIEW_BBOX_ENRICH_MIN_SCORE = float(os.getenv("REVIEW_BBOX_ENRICH_MIN_SCORE", "55"))
UPLOADS_DIR = Path(os.getenv("UPLOADS_DIR") or "uploads")
