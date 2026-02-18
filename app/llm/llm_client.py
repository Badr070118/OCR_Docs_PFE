from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Iterable
from urllib.parse import urlparse, urlunparse

import requests
from requests.exceptions import RequestException, Timeout

LOGGER = logging.getLogger(__name__)


def _is_truthy(value: str | None) -> bool:
    return bool(value and value.strip().lower() in {"1", "true", "yes", "on"})


def _get_stop_sequences() -> list[str]:
    raw = os.getenv("LLAMA_STOP_SEQUENCES", "```|</json>|<|eot_id|>")
    parts = [part.strip() for part in raw.replace(",", "|").split("|")]
    return [part for part in parts if part]


def _extract_text_from_payload(payload: Any) -> str:
    if isinstance(payload, dict):
        content = payload.get("content")
        if isinstance(content, str):
            return content.strip()

        text = payload.get("text")
        if isinstance(text, str):
            return text.strip()

        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                message = first.get("message")
                if isinstance(message, dict):
                    message_content = message.get("content")
                    if isinstance(message_content, str):
                        return message_content.strip()
                for key in ("text", "content"):
                    value = first.get(key)
                    if isinstance(value, str):
                        return value.strip()

    raise RuntimeError(f"Unexpected llama.cpp response payload: {json.dumps(payload, ensure_ascii=True)[:600]}")


def _build_url_with_path(base_url: str, new_path: str) -> str:
    parsed = urlparse(base_url)
    return urlunparse((parsed.scheme, parsed.netloc, new_path, "", "", ""))


def _candidate_urls(base_url: str) -> list[str]:
    trimmed = base_url.strip().rstrip("/")
    parsed = urlparse(trimmed)
    path = parsed.path.lower().rstrip("/")

    candidates = [trimmed]
    if path.endswith("/completion"):
        candidates.append(_build_url_with_path(trimmed, "/v1/completions"))
        candidates.append(_build_url_with_path(trimmed, "/v1/chat/completions"))
    elif path.endswith("/v1/completions"):
        candidates.append(_build_url_with_path(trimmed, "/completion"))
        candidates.append(_build_url_with_path(trimmed, "/v1/chat/completions"))
    elif path.endswith("/v1/chat/completions"):
        candidates.append(_build_url_with_path(trimmed, "/v1/completions"))
        candidates.append(_build_url_with_path(trimmed, "/completion"))
    else:
        candidates.append(trimmed + "/completion")
        candidates.append(trimmed + "/v1/completions")
        candidates.append(trimmed + "/v1/chat/completions")

    seen: set[str] = set()
    unique: list[str] = []
    for candidate in candidates:
        if candidate not in seen:
            seen.add(candidate)
            unique.append(candidate)
    return unique


def _build_payload(
    *,
    prompt: str,
    url: str,
    temperature: float,
    top_p: float,
    max_tokens: int,
    stop_sequences: list[str],
) -> dict[str, Any]:
    lower_url = url.lower()
    if lower_url.endswith("/v1/chat/completions"):
        return {
            "model": os.getenv("LLAMA_CPP_MODEL", "local-model"),
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "top_p": top_p,
            "max_tokens": max_tokens,
            "stop": stop_sequences,
            "stream": False,
        }
    if lower_url.endswith("/v1/completions"):
        return {
            "model": os.getenv("LLAMA_CPP_MODEL", "local-model"),
            "prompt": prompt,
            "temperature": temperature,
            "top_p": top_p,
            "max_tokens": max_tokens,
            "stop": stop_sequences,
            "stream": False,
        }
    return {
        "prompt": prompt,
        "temperature": temperature,
        "top_p": top_p,
        "n_predict": max_tokens,
        "stop": stop_sequences,
        "stream": False,
    }


def call_llama_cpp(
    prompt: str,
    *,
    temperature: float | None = None,
    top_p: float | None = None,
    max_tokens: int | None = None,
    stop_sequences: Iterable[str] | None = None,
) -> str:
    base_url = os.getenv("LLAMA_CPP_URL", "http://127.0.0.1:8080/completion").strip()
    urls = _candidate_urls(base_url)
    timeout_seconds = int(os.getenv("LLAMA_HTTP_TIMEOUT_SECONDS", "120"))
    retries = int(os.getenv("LLAMA_HTTP_RETRIES", "1"))
    sleep_seconds = float(os.getenv("LLAMA_HTTP_RETRY_BACKOFF_SECONDS", "0.75"))
    debug_mode = _is_truthy(os.getenv("LLAMA_DEBUG"))

    selected_temperature = float(os.getenv("LLAMA_TEMPERATURE", "0.1")) if temperature is None else float(temperature)
    selected_top_p = float(os.getenv("LLAMA_TOP_P", "0.9")) if top_p is None else float(top_p)
    selected_max_tokens = int(os.getenv("LLAMA_MAX_TOKENS", "800")) if max_tokens is None else int(max_tokens)
    selected_stop_sequences = list(stop_sequences) if stop_sequences is not None else _get_stop_sequences()

    if debug_mode:
        LOGGER.warning("llama.cpp prompt (first 1200 chars): %s", prompt[:1200])

    last_error: Exception | None = None
    for attempt in range(retries + 1):
        for url in urls:
            payload = _build_payload(
                prompt=prompt,
                url=url,
                temperature=selected_temperature,
                top_p=selected_top_p,
                max_tokens=selected_max_tokens,
                stop_sequences=selected_stop_sequences,
            )
            try:
                response = requests.post(url, json=payload, timeout=timeout_seconds)
                if response.status_code == 404:
                    last_error = RuntimeError(f"llama.cpp server returned HTTP 404 on {url}: {response.text[:300]}")
                    continue
                if not response.ok:
                    raise RuntimeError(f"llama.cpp server returned HTTP {response.status_code}: {response.text[:500]}")
                body = response.json()
                text = _extract_text_from_payload(body)
                if debug_mode:
                    LOGGER.warning("llama.cpp endpoint used: %s", url)
                    LOGGER.warning("llama.cpp output (first 1200 chars): %s", text[:1200])
                return text
            except (Timeout, RequestException, ValueError, RuntimeError) as exc:
                last_error = exc
                continue
        if attempt < retries:
            time.sleep(sleep_seconds)
            continue
        break

    raise RuntimeError(f"llama.cpp call failed after retries: {last_error}")
