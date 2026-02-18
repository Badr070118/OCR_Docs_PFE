from __future__ import annotations

import json
from typing import Any, Callable

from app.llm.prompt_builder import build_json_fix_prompt


def extract_json_block(text: str) -> str | None:
    start = (text or "").find("{")
    end = (text or "").rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return text[start : end + 1]


def _parse_object(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        return None
    return None


def _has_required_keys(payload: dict[str, Any], schema: dict[str, Any]) -> bool:
    required = schema.get("required")
    if not isinstance(required, list):
        return True
    return all(key in payload for key in required)


def ensure_valid_json_object(
    raw_output: str,
    *,
    schema: dict[str, Any],
    llm_call_fn: Callable[[str], str],
) -> dict[str, Any]:
    parsed = _parse_object(raw_output)
    if parsed is None:
        extracted = extract_json_block(raw_output)
        parsed = _parse_object(extracted or "")
    if parsed is not None and _has_required_keys(parsed, schema):
        return parsed

    fix_prompt = build_json_fix_prompt(raw_output=raw_output, schema=schema)
    fixed_output = llm_call_fn(fix_prompt)
    fixed = _parse_object(fixed_output)
    if fixed is None:
        extracted = extract_json_block(fixed_output)
        fixed = _parse_object(extracted or "")

    if fixed is None or not _has_required_keys(fixed, schema):
        raise RuntimeError("LLM did not return valid JSON after one fix attempt.")
    return fixed
