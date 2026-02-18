from __future__ import annotations

import os
from typing import Any

import requests

from app.llm.llm_client import call_llama_cpp


def _is_truthy(value: str | None) -> bool:
    return bool(value and value.strip().lower() in {"1", "true", "yes", "on"})


def _call_ollama(prompt: str) -> str:
    base_url = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434").strip().rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "llama3.1").strip() or "llama3.1"
    timeout_seconds = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "180"))

    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": float(os.getenv("LLAMA_TEMPERATURE", "0.1")),
            "top_p": float(os.getenv("LLAMA_TOP_P", "0.9")),
            "num_predict": int(os.getenv("LLAMA_MAX_TOKENS", "800")),
        },
    }

    response = requests.post(
        f"{base_url}/api/generate",
        json=payload,
        timeout=timeout_seconds,
    )
    if not response.ok:
        raise RuntimeError(
            f"Ollama server returned HTTP {response.status_code}: {response.text[:500]}"
        )
    body = response.json()
    text = body.get("response")
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError("Ollama returned an empty response.")
    return text.strip()


def call_llm(prompt: str) -> str:
    try:
        return call_llama_cpp(prompt)
    except Exception as llama_cpp_error:
        if not _is_truthy(os.getenv("LLM_FALLBACK_OLLAMA", "1")):
            raise
        try:
            return _call_ollama(prompt)
        except Exception as ollama_error:
            raise RuntimeError(
                "Primary llama.cpp call failed and Ollama fallback failed: "
                f"{llama_cpp_error} | {ollama_error}"
            ) from ollama_error

