from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable

try:
    from rapidfuzz import fuzz, process
except ImportError:  # pragma: no cover - optional dependency at runtime
    fuzz = None
    process = None


@dataclass(frozen=True)
class ReferenceEntity:
    id: int
    canonical_name: str
    aliases: list[str]


def _normalize_text(value: str) -> str:
    lowered = (value or "").strip().lower()
    lowered = re.sub(r"\s+", " ", lowered)
    return lowered


def _score_with_fallback(left: str, right: str) -> float:
    return SequenceMatcher(a=left, b=right).ratio() * 100.0


def _flatten_choices(entities: Iterable[ReferenceEntity]) -> dict[str, tuple[int, str]]:
    choices: dict[str, tuple[int, str]] = {}
    for entity in entities:
        canonical = entity.canonical_name.strip()
        if not canonical:
            continue
        all_variants = [canonical, *(entity.aliases or [])]
        for alias in all_variants:
            normalized = _normalize_text(alias)
            if not normalized:
                continue
            choices[normalized] = (entity.id, canonical)
    return choices


def match_reference(
    text: str,
    entities: Iterable[ReferenceEntity],
    threshold: int,
) -> dict[str, object]:
    normalized_input = _normalize_text(text)
    if not normalized_input:
        return {
            "canonical": text,
            "score": 0.0,
            "matched_id": None,
            "action": "keep",
        }

    choice_map = _flatten_choices(entities)
    if not choice_map:
        return {
            "canonical": text,
            "score": 0.0,
            "matched_id": None,
            "action": "keep",
        }

    best_alias = None
    best_score = -1.0

    if process is not None and fuzz is not None:
        result = process.extractOne(
            normalized_input,
            list(choice_map.keys()),
            scorer=fuzz.WRatio,
        )
        if result:
            best_alias, best_score = result[0], float(result[1])
    else:
        for alias in choice_map.keys():
            score = _score_with_fallback(normalized_input, alias)
            if score > best_score:
                best_alias = alias
                best_score = score

    if best_alias is None or best_score < threshold:
        return {
            "canonical": text,
            "score": max(best_score, 0.0),
            "matched_id": None,
            "action": "keep",
        }

    matched_id, canonical = choice_map[best_alias]
    action = "replace" if _normalize_text(canonical) != normalized_input else "keep"
    return {
        "canonical": canonical,
        "score": best_score,
        "matched_id": matched_id,
        "action": action,
    }


class FuzzyNormalizer:
    def __init__(self, threshold: int):
        self.threshold = threshold

    def normalize_supplier(self, text: str, entities: Iterable[ReferenceEntity]) -> dict[str, object]:
        return match_reference(text, entities, self.threshold)

    def normalize_city(self, text: str, entities: Iterable[ReferenceEntity]) -> dict[str, object]:
        return match_reference(text, entities, self.threshold)

    def normalize_country(self, text: str, entities: Iterable[ReferenceEntity]) -> dict[str, object]:
        return match_reference(text, entities, self.threshold)
