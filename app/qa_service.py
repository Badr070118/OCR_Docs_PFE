from __future__ import annotations

import json
import os
import re
from typing import Any

import requests
from pydantic import ValidationError
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import RequestException, Timeout
from sqlalchemy.orm import Session

from app.db import Document
from app.schemas import DocumentAskResponse

NOT_FOUND_ANSWER = "Non trouvé dans ce document"
MAX_QUESTION_CHARS = int(os.getenv("QA_MAX_QUESTION_CHARS", "500"))
MAX_OCR_CONTEXT_CHARS = int(os.getenv("QA_MAX_OCR_CONTEXT_CHARS", "12000"))
MAX_STRUCTURED_CONTEXT_CHARS = int(os.getenv("QA_MAX_STRUCTURED_CONTEXT_CHARS", "6000"))

QA_SYSTEM_PROMPT = (
    "Tu es un assistant d'analyse de documents. "
    "Tu dois repondre uniquement depuis CONTEXT. "
    "Si information absente ou illisible => found=false et answer='Non trouve dans ce document'. "
    "Tu dois fournir evidence: extraits exacts OCR ou chemins de champs JSON. "
    "Tu dois rendre UNIQUEMENT un JSON valide, sans markdown, sans commentaires. "
    "Format exact attendu: "
    '{"answer":"string","found":true,"fields_used":["data.montant"],"evidence":["..."],"confidence":0.0}. '
    "confidence doit etre un nombre entre 0.0 et 1.0. "
    "Ne jamais inventer."
)


def _sanitize_question(question: str) -> str:
    cleaned = re.sub(r"[\x00-\x1f\x7f]+", " ", question or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:MAX_QUESTION_CHARS]


def _truncate_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars].rstrip()}\n...[TRUNCATED]"


def _serialize_structured_json(data: Any) -> str:
    try:
        content = json.dumps(data or {}, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        content = "{}"
    return _truncate_text(content, MAX_STRUCTURED_CONTEXT_CHARS)


def _build_messages(
    question: str, structured_json_text: str, ocr_text: str, retry_mode: bool
) -> list[dict[str, str]]:
    retry_hint = (
        "\nIMPORTANT: Ta reponse precedente n'etait pas un JSON valide."
        " Reponds uniquement avec un objet JSON strict, sans texte autour."
        if retry_mode
        else ""
    )
    user_prompt = (
        f"QUESTION:\n{question}\n\n"
        "CONTEXT_STRUCTURED_JSON:\n"
        f"{structured_json_text}\n\n"
        "CONTEXT_OCR_TEXT:\n"
        f"{ocr_text}\n"
        f"{retry_hint}"
    )
    return [
        {"role": "system", "content": QA_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def _extract_error_detail(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text.strip() or "Unknown error."
    return str(payload.get("error") or payload).strip()


def _call_ollama(messages: list[dict[str, str]]) -> str:
    base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "llama3.1")
    endpoint = f"{base_url}/api/chat"
    timeout_seconds = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "180"))

    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "format": "json",
        "options": {
            "temperature": float(os.getenv("QA_TEMPERATURE", "0")),
            "top_p": float(os.getenv("QA_TOP_P", "0.2")),
            "num_predict": int(os.getenv("QA_MAX_TOKENS", "512")),
        },
    }

    try:
        response = requests.post(endpoint, json=payload, timeout=timeout_seconds)
    except RequestsConnectionError as exc:
        raise RuntimeError(
            f"Cannot reach Ollama at {base_url}. Start Ollama and retry."
        ) from exc
    except Timeout as exc:
        raise RuntimeError(
            "Ollama request timed out. Increase OLLAMA_TIMEOUT_SECONDS or reduce context size."
        ) from exc
    except RequestException as exc:
        raise RuntimeError(f"Ollama request failed: {exc}") from exc

    if response.status_code == 404:
        raise RuntimeError(
            f"Ollama model '{model}' is not available locally. Run: ollama pull {model}"
        )
    if not response.ok:
        detail = _extract_error_detail(response)
        raise RuntimeError(f"Ollama returned HTTP {response.status_code}: {detail}")

    try:
        body = response.json()
    except ValueError as exc:
        raise RuntimeError("Invalid JSON response from Ollama endpoint.") from exc

    content = (body.get("message") or {}).get("content")
    if not isinstance(content, str):
        raise RuntimeError(f"Unexpected Ollama payload: {json.dumps(body, ensure_ascii=True)}")
    return content.strip()


def _extract_json_payload(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        raise ValueError("Empty response from model.")

    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("Model output is not valid JSON.")
    parsed = json.loads(raw[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("Model output JSON must be an object.")
    return parsed


def _validate_payload(payload: dict[str, Any]) -> DocumentAskResponse:
    if hasattr(DocumentAskResponse, "model_validate"):
        return DocumentAskResponse.model_validate(payload)
    return DocumentAskResponse.parse_obj(payload)


def _normalize_qa_response(response: DocumentAskResponse) -> DocumentAskResponse:
    fields_used = [str(item).strip() for item in response.fields_used if str(item).strip()]
    evidence = [str(item).strip() for item in response.evidence if str(item).strip()]
    answer = (response.answer or "").strip()

    try:
        confidence = float(response.confidence)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(confidence, 1.0))

    found = bool(response.found)
    if not evidence:
        found = False
        answer = NOT_FOUND_ANSWER
        confidence = min(confidence, 0.35)
    elif not found:
        answer = NOT_FOUND_ANSWER
        confidence = min(confidence, 0.35)
    elif not answer:
        answer = "Information trouvee dans le document."

    return DocumentAskResponse(
        answer=answer,
        found=found,
        fields_used=fields_used,
        evidence=evidence,
        confidence=confidence,
    )


def ask_document_question(db: Session, document_id: int, question: str) -> DocumentAskResponse:
    document = db.query(Document).filter(Document.id == document_id).first()
    if document is None:
        raise LookupError("Document not found.")

    clean_question = _sanitize_question(question)
    if not clean_question:
        raise ValueError("Question is empty after sanitization.")

    structured_json_text = _serialize_structured_json(document.data)
    raw_text = _truncate_text((document.raw_text or "").strip(), MAX_OCR_CONTEXT_CHARS)

    last_error: Exception | None = None
    for retry_mode in (False, True):
        try:
            messages = _build_messages(
                clean_question,
                structured_json_text,
                raw_text,
                retry_mode=retry_mode,
            )
            model_text = _call_ollama(messages)
            parsed = _extract_json_payload(model_text)
            validated = _validate_payload(parsed)
            return _normalize_qa_response(validated)
        except (json.JSONDecodeError, ValueError, ValidationError) as exc:
            last_error = exc
            continue

    raise RuntimeError(
        f"Model did not return a valid QA JSON response after retry: {last_error}"
    )
