from __future__ import annotations

import json
from typing import Any


def _schema_as_text(schema: dict[str, Any]) -> str:
    return json.dumps(schema, ensure_ascii=True, indent=2)


def build_strict_json_prompt(
    *,
    ocr_text: str,
    schema: dict[str, Any],
    instruction: str | None = None,
) -> str:
    instruction_text = (instruction or "").strip() or "Extraire les champs du document."
    return (
        "SYSTEM:\n"
        "Tu es un extracteur de donnees de documents.\n"
        "Tu dois repondre UNIQUEMENT avec un JSON valide.\n"
        "Interdit: markdown, commentaires, texte hors JSON.\n"
        "Si une valeur manque, utiliser null.\n"
        "Respecte strictement ce schema JSON cible:\n"
        f"{_schema_as_text(schema)}\n\n"
        "USER INSTRUCTION:\n"
        f"{instruction_text}\n\n"
        "OCR TEXT:\n"
        f"{ocr_text}\n\n"
        "OUTPUT:\n"
        "Retourne UNIQUEMENT l'objet JSON valide."
    )


def build_json_fix_prompt(
    *,
    raw_output: str,
    schema: dict[str, Any],
) -> str:
    return (
        "SYSTEM:\n"
        "Corrige la sortie pour produire UNIQUEMENT un JSON valide.\n"
        "Aucun texte avant/apres.\n"
        "Respecte ce schema:\n"
        f"{_schema_as_text(schema)}\n\n"
        "SORTIE A CORRIGER:\n"
        f"{raw_output}\n\n"
        "OUTPUT:\n"
        "Retourne uniquement le JSON corrige."
    )


def build_instruction_prompt(*, ocr_text: str, instruction: str) -> str:
    return (
        "SYSTEM:\n"
        "Tu aides a analyser un texte OCR. Reponds en francais, de maniere concise.\n"
        "N'invente pas d'information absente du texte.\n\n"
        "INSTRUCTION:\n"
        f"{instruction.strip()}\n\n"
        "OCR TEXT:\n"
        f"{ocr_text}\n"
    )
