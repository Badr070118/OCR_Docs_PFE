from __future__ import annotations

import json
import os
import re
from typing import Any, Optional

import requests
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import RequestException, Timeout

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


def _get_ollama_base_url() -> str:
    return os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")


def _get_ollama_model() -> str:
    return os.getenv("OLLAMA_MODEL", "llama3.1")


def _build_messages(text: str, instruction: Optional[str], strict_json: bool) -> list[dict[str, str]]:
    if strict_json:
        system_prompt = os.getenv(
            "LLAMA_SYSTEM_PROMPT",
            (
                "Reponds en francais. "
                "Extrais les champs cle d'une facture (name, date, amount, address, email). "
                "Retourne UNIQUEMENT un objet JSON valide avec ces cles. "
                "Pas de notes, pas de markdown. "
                "Utilise un point pour les decimales et mets amount en nombre JSON. "
                "Si un champ est absent, mets la valeur \"inconnu\"."
            ),
        )
        user_prompt = (
            "OCR TEXT:\n"
            f"{text}\n\n"
            "Retourne uniquement le JSON."
        )
    else:
        system_prompt = (
            "Reponds en francais. Suis strictement l'instruction utilisateur. "
            "N'invente rien. Si un champ demande est absent, ecris \"inconnu\"."
        )
        user_prompt = (
            "INSTRUCTION:\n"
            f"{instruction}\n\n"
            "OCR TEXT:\n"
            f"{text}"
        )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _build_ollama_options() -> dict[str, Any]:
    return {
        "temperature": float(os.getenv("LLAMA_TEMPERATURE", "0.2")),
        "top_p": float(os.getenv("LLAMA_TOP_P", "0.9")),
        "num_predict": int(os.getenv("LLAMA_MAX_TOKENS", "512")),
    }


def _build_hybrid_json_messages(text: str, instruction: Optional[str]) -> list[dict[str, str]]:
    system_prompt = (
        "Tu es un extracteur de donnees de factures. "
        "Retourne UNIQUEMENT un objet JSON valide avec ces cles top-level: "
        "nom, prenom, date, montant, adresse, email, numero_facture, extra. "
        "Les 7 premieres cles sont ton noyau stable. "
        "Si une valeur manque, mets null. "
        "La cle extra doit toujours etre un objet JSON (vide {} si rien). "
        "Ne renvoie ni markdown ni explication."
    )
    instruction_text = instruction.strip() if instruction else ""
    user_prompt = (
        "Instruction utilisateur (optionnelle):\n"
        f"{instruction_text or 'Aucune instruction supplementaire'}\n\n"
        "OCR TEXT:\n"
        f"{text}\n\n"
        "Renvoie uniquement l'objet JSON."
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _extract_error_detail(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text.strip() or "Unknown error."
    return str(payload.get("error") or payload).strip()


def _generate_text(messages: list[dict[str, str]]) -> str:
    base_url = _get_ollama_base_url()
    model = _get_ollama_model()
    timeout_seconds = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "180"))
    endpoint = f"{base_url}/api/chat"

    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": _build_ollama_options(),
    }

    try:
        response = requests.post(endpoint, json=payload, timeout=timeout_seconds)
    except RequestsConnectionError as exc:
        raise RuntimeError(
            f"Cannot reach Ollama at {base_url}. "
            "Start Ollama (`ollama serve`) and ensure the model is pulled "
            "(`ollama pull llama3.1`)."
        ) from exc
    except Timeout as exc:
        raise RuntimeError(
            "Ollama request timed out. Increase OLLAMA_TIMEOUT_SECONDS or reduce prompt size."
        ) from exc
    except RequestException as exc:
        raise RuntimeError(f"Ollama request failed: {exc}") from exc

    if response.status_code == 404:
        raise RuntimeError(
            f"Ollama model '{model}' is not available locally. Run: ollama pull {model}"
        )
    if not response.ok:
        detail = _extract_error_detail(response)
        raise RuntimeError(
            f"Ollama returned HTTP {response.status_code}: {detail}"
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError("Invalid JSON response from Ollama.") from exc

    content = (data.get("message") or {}).get("content")
    if not isinstance(content, str):
        raise RuntimeError(f"Unexpected Ollama response: {json.dumps(data, ensure_ascii=True)}")
    return content.strip()


def generate_from_llama(text: str, instruction: Optional[str] = None) -> str:
    """
    Generate a response from OCR text using local Llama 3.1.
    If instruction is provided, returns free-form text.
    """
    strict_json = instruction is None
    messages = _build_messages(text, instruction, strict_json)
    raw_text = _generate_text(messages)
    if not strict_json:
        return raw_text

    json_block = _extract_json_block(raw_text)
    try:
        parsed = json.loads(json_block)
    except json.JSONDecodeError:
        return json_block.strip()

    normalized = _normalize_amount_fields(parsed)
    return json.dumps(normalized, ensure_ascii=True, indent=2)


def _extract_json_block(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return text
    return text[start : end + 1]


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


def extract_hybrid_data_from_text(text: str) -> dict[str, Any] | None:
    json_block = _extract_json_block(text)
    try:
        parsed = json.loads(json_block)
    except json.JSONDecodeError:
        return None
    return normalize_hybrid_data(parsed)


def generate_hybrid_json_from_text(text: str, instruction: Optional[str] = None) -> dict[str, Any]:
    messages = _build_hybrid_json_messages(text, instruction)
    raw_text = _generate_text(messages)
    parsed = extract_hybrid_data_from_text(raw_text)
    if parsed is None:
        raise RuntimeError("Llama did not return a valid JSON object for hybrid data.")
    return parsed


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
