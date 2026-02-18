from __future__ import annotations

import json
import re
from typing import Any, Optional

from app.llm.json_guard import ensure_valid_json_object, extract_json_block
from app.llm.provider import call_llm
from app.llm.prompt_builder import build_instruction_prompt, build_strict_json_prompt

CORE_DATA_FIELDS = (
    "nom",
    "prenom",
    "date",
    "montant",
    "adresse",
    "email",
    "numero_facture",
)

_ALIASES_TO_CORE = {
    "name": "nom",
    "full_name": "nom",
    "first_name": "prenom",
    "lastname": "nom",
    "surname": "nom",
    "amount": "montant",
    "total": "montant",
    "invoice_number": "numero_facture",
    "invoice_no": "numero_facture",
    "numero": "numero_facture",
    "numerofacture": "numero_facture",
    "n_facture": "numero_facture",
    "no_facture": "numero_facture",
    "address": "adresse",
    "mail": "email",
}


def _instruction_requests_json(instruction: Optional[str]) -> bool:
    if not instruction:
        return True
    lowered = instruction.lower()
    hints = ("json", "structure", "structur", "schema", "champ", "field", "extract")
    return any(hint in lowered for hint in hints)


def _basic_invoice_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["name", "date", "amount", "address", "email"],
        "properties": {
            "name": {"type": ["string", "null"]},
            "date": {"type": ["string", "null"]},
            "amount": {"type": ["number", "string", "null"]},
            "address": {"type": ["string", "null"]},
            "email": {"type": ["string", "null"]},
        },
        "additionalProperties": True,
    }


def _hybrid_json_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": [
            "nom",
            "prenom",
            "date",
            "montant",
            "adresse",
            "email",
            "numero_facture",
            "extra",
        ],
        "properties": {
            "nom": {"type": ["string", "null"]},
            "prenom": {"type": ["string", "null"]},
            "date": {"type": ["string", "null"]},
            "montant": {"type": ["number", "string", "null"]},
            "adresse": {"type": ["string", "null"]},
            "email": {"type": ["string", "null"]},
            "numero_facture": {"type": ["string", "null"]},
            "extra": {"type": "object"},
        },
        "additionalProperties": True,
    }


def _empty_hybrid_data() -> dict[str, Any]:
    payload = {field: None for field in CORE_DATA_FIELDS}
    payload["extra"] = {}
    return payload


def _is_empty_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return True
        if stripped.lower() in {"null", "none", "n/a", "na", "inconnu", "unknown"}:
            return True
    return False


def _normalize_scalar(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return value


def normalize_hybrid_data(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None

    source = payload
    top_level_extra: dict[str, Any] = {}
    if isinstance(payload.get("data"), dict):
        source = payload["data"]
        top_level_extra = {
            key: value for key, value in payload.items() if key not in {"data"}
        }

    result = _empty_hybrid_data()
    extra = result["extra"]
    existing_extra = source.get("extra")
    if isinstance(existing_extra, dict):
        extra.update(existing_extra)

    for key, value in source.items():
        if key == "extra":
            continue
        normalized_key = key.strip().lower()
        canonical = _ALIASES_TO_CORE.get(normalized_key, normalized_key)
        if canonical in CORE_DATA_FIELDS:
            result[canonical] = _normalize_scalar(value)
        else:
            extra[key] = value

    for key, value in top_level_extra.items():
        extra[key] = value

    return result


def _normalize_amount_fields(payload: Any) -> Any:
    if isinstance(payload, dict):
        normalized = {}
        for key, value in payload.items():
            if key.lower() in {"amount", "montant"}:
                normalized[key] = _to_number(value)
            else:
                normalized[key] = _normalize_amount_fields(value)
        return normalized
    if isinstance(payload, list):
        return [_normalize_amount_fields(item) for item in payload]
    return payload


def _to_number(value: Any) -> Any:
    if isinstance(value, (int, float)):
        return value
    if not isinstance(value, str):
        return value

    match = re.search(r"-?\d+(?:[.,]\d+)?", value.replace(" ", ""))
    if not match:
        return value
    return float(match.group(0).replace(",", "."))


def generate_from_llama(text: str, instruction: Optional[str] = None) -> str:
    """
    Generate a response from OCR text using local llama.cpp server.
    If instruction is provided and does not request JSON, returns free-form text.
    Otherwise returns JSON string.
    """
    if instruction and not _instruction_requests_json(instruction):
        prompt = build_instruction_prompt(ocr_text=text, instruction=instruction)
        return call_llm(prompt).strip()

    schema = _basic_invoice_schema()
    prompt = build_strict_json_prompt(ocr_text=text, schema=schema, instruction=instruction)
    raw_text = call_llm(prompt)
    parsed = ensure_valid_json_object(
        raw_output=raw_text,
        schema=schema,
        llm_call_fn=call_llm,
    )
    normalized = _normalize_amount_fields(parsed)
    return json.dumps(normalized, ensure_ascii=True, indent=2)


def extract_hybrid_data_from_text(text: str) -> dict[str, Any] | None:
    json_block = extract_json_block(text)
    if not json_block:
        return None
    try:
        parsed = json.loads(json_block)
    except json.JSONDecodeError:
        return None
    return normalize_hybrid_data(parsed)


def generate_hybrid_json_from_text(text: str, instruction: Optional[str] = None) -> dict[str, Any]:
    schema = _hybrid_json_schema()
    prompt = build_strict_json_prompt(ocr_text=text, schema=schema, instruction=instruction)
    raw_text = call_llm(prompt)
    parsed = ensure_valid_json_object(
        raw_output=raw_text,
        schema=schema,
        llm_call_fn=call_llm,
    )
    normalized = normalize_hybrid_data(parsed)
    if normalized is None:
        raise RuntimeError("LLM did not return a valid JSON object for hybrid data.")
    return normalized


def merge_hybrid_data(existing_data: Any, new_data: Any) -> dict[str, Any]:
    base = normalize_hybrid_data(existing_data) or _empty_hybrid_data()
    incoming = normalize_hybrid_data(new_data) or _empty_hybrid_data()

    merged = _empty_hybrid_data()
    for field in CORE_DATA_FIELDS:
        in_value = incoming.get(field)
        base_value = base.get(field)
        merged[field] = base_value if _is_empty_value(in_value) else in_value

    merged_extra: dict[str, Any] = {}
    if isinstance(base.get("extra"), dict):
        merged_extra.update(base["extra"])
    if isinstance(incoming.get("extra"), dict):
        merged_extra.update(incoming["extra"])
    merged["extra"] = merged_extra
    return merged
