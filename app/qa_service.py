from __future__ import annotations

import json
import os
import re
import unicodedata
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.db import Document
from app.llm.provider import call_llm
from app.schemas import DocumentAskResponse

NOT_FOUND_ANSWER = "Non trouvé dans ce document"
MAX_QUESTION_CHARS = int(os.getenv("QA_MAX_QUESTION_CHARS", "500"))
MAX_OCR_CONTEXT_CHARS = int(os.getenv("QA_MAX_OCR_CONTEXT_CHARS", "12000"))
MAX_STRUCTURED_CONTEXT_CHARS = int(os.getenv("QA_MAX_STRUCTURED_CONTEXT_CHARS", "6000"))
TABLE_QUESTION_HINTS = (
    "article",
    "ligne",
    "quantite",
    "prix",
    "unitaire",
)
TOTAL_QUESTION_HINTS = ("montant total", "total", "a payer", "montant")
TVA_QUESTION_HINTS = ("tva", "vat", "taxe")
DATE_QUESTION_HINTS = ("date", "echeance", "invoice date")
EMAIL_QUESTION_HINTS = ("email", "mail", "courriel")
ADDRESS_QUESTION_HINTS = ("adresse", "address")
SUPPLIER_QUESTION_HINTS = (
    "fournisseur",
    "emetteur",
    "emetteur",
    "vendeur",
    "societe",
    "entreprise",
    "issuer",
)
CLIENT_QUESTION_HINTS = (
    "client",
    "customer",
    "destinataire",
    "acheteur",
)
GENERIC_QUESTION_STOPWORDS = {
    "donne",
    "moi",
    "le",
    "la",
    "les",
    "de",
    "du",
    "des",
    "est",
    "quel",
    "quelle",
    "quels",
    "quelles",
    "avec",
    "dans",
    "sur",
    "ce",
    "document",
    "svp",
    "stp",
    "please",
}
GENERIC_TOKEN_ALIASES: dict[str, set[str]] = {
    "client": {"client", "customer", "nom_client", "client_name", "nom", "prenom"},
    "customer": {"client", "customer", "nom_client", "client_name", "nom", "prenom"},
    "facture": {"numero_facture", "invoice_number", "facture", "numero"},
    "numero": {"numero_facture", "invoice_number", "facture", "numero"},
    "email": {"email", "mail", "courriel"},
    "mail": {"email", "mail", "courriel"},
    "adresse": {"adresse", "address"},
    "address": {"adresse", "address"},
}

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


def _strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    return normalized.encode("ascii", "ignore").decode("ascii")


def _normalize_for_match(text: str) -> str:
    return re.sub(r"\s+", " ", _strip_accents(text).lower()).strip()


def _sanitize_question(question: str) -> str:
    cleaned = re.sub(r"[\x00-\x1f\x7f]+", " ", question or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:MAX_QUESTION_CHARS]


def _is_table_question(question: str) -> bool:
    value = _normalize_for_match(question)
    return any(hint in value for hint in TABLE_QUESTION_HINTS)


def _is_total_question(question: str) -> bool:
    value = _normalize_for_match(question)
    if any(hint in value for hint in TVA_QUESTION_HINTS):
        return False
    return any(hint in value for hint in TOTAL_QUESTION_HINTS)


def _is_tva_question(question: str) -> bool:
    value = _normalize_for_match(question)
    return any(hint in value for hint in TVA_QUESTION_HINTS)


def _is_date_question(question: str) -> bool:
    value = _normalize_for_match(question)
    return any(hint in value for hint in DATE_QUESTION_HINTS)


def _is_email_question(question: str) -> bool:
    value = _normalize_for_match(question)
    return any(hint in value for hint in EMAIL_QUESTION_HINTS)


def _is_address_question(question: str) -> bool:
    value = _normalize_for_match(question)
    return any(hint in value for hint in ADDRESS_QUESTION_HINTS)


def _is_supplier_question(question: str) -> bool:
    value = _normalize_for_match(question)
    return any(hint in value for hint in SUPPLIER_QUESTION_HINTS)


def _is_client_question(question: str) -> bool:
    value = _normalize_for_match(question)
    return any(hint in value for hint in CLIENT_QUESTION_HINTS)


def _normalize_money(value: str) -> str:
    raw = re.sub(r"[^0-9,.\-]", "", value or "")
    if not raw:
        return ""
    if "," in raw and "." not in raw:
        raw = raw.replace(",", ".")
    elif "," in raw and "." in raw:
        if raw.rfind(",") > raw.rfind("."):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif raw.count(".") > 1:
        parts = raw.split(".")
        raw = "".join(parts[:-1]) + "." + parts[-1]
    try:
        return f"{float(raw):.2f}"
    except ValueError:
        return value.strip()


def _normalize_quantity_token(value: str) -> str:
    token = (value or "").strip()
    if not token:
        return ""
    if not re.search(r"\d", token):
        candidate = token.lower().replace("e", "1")
        if candidate in {"1", "11"}:
            return "1"
    token = token.replace("I", "1").replace("l", "1").replace("|", "1")
    token = token.replace("O", "0").replace("o", "0")
    match = re.search(r"-?\d+", token)
    return match.group(0) if match else ""


def _is_scalar(value: Any) -> bool:
    return isinstance(value, (str, int, float)) and str(value).strip() != ""


def _find_value_with_path(data: Any, target_keys: set[str], prefix: str = "data") -> tuple[str, str] | None:
    if isinstance(data, dict):
        for key, value in data.items():
            path = f"{prefix}.{key}"
            key_norm = _normalize_for_match(str(key)).replace(" ", "_")
            if key_norm in target_keys and _is_scalar(value):
                return path, str(value).strip()
            nested = _find_value_with_path(value, target_keys, path)
            if nested:
                return nested
    elif isinstance(data, list):
        for index, item in enumerate(data):
            nested = _find_value_with_path(item, target_keys, f"{prefix}[{index}]")
            if nested:
                return nested
    return None


def _flatten_scalar_fields(data: Any, prefix: str = "data") -> list[tuple[str, str, str]]:
    fields: list[tuple[str, str, str]] = []
    if isinstance(data, dict):
        for key, value in data.items():
            path = f"{prefix}.{key}"
            if _is_scalar(value):
                fields.append((path, _normalize_for_match(str(key)).replace(" ", "_"), str(value).strip()))
            else:
                fields.extend(_flatten_scalar_fields(value, path))
    elif isinstance(data, list):
        for index, item in enumerate(data):
            fields.extend(_flatten_scalar_fields(item, f"{prefix}[{index}]"))
    return fields


def _extract_question_tokens(question: str) -> set[str]:
    normalized = _normalize_for_match(question)
    raw_tokens = re.split(r"[^a-z0-9_]+", normalized)
    tokens = {token for token in raw_tokens if len(token) >= 3 and token not in GENERIC_QUESTION_STOPWORDS}
    return tokens


def _extract_rows_from_structured_data(data: Any) -> list[dict[str, str]]:
    if not isinstance(data, dict):
        return []
    extra = data.get("extra")
    if not isinstance(extra, dict):
        return []

    candidates: list[Any] = []
    for key in ("articles", "lignes", "line_items", "items"):
        value = extra.get(key)
        if isinstance(value, list):
            candidates.extend(value)

    rows: list[dict[str, str]] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        description = str(
            item.get("description")
            or item.get("libelle")
            or item.get("label")
            or ""
        ).strip()
        quantity = _normalize_quantity_token(
            str(item.get("quantite") or item.get("quantity") or item.get("qte") or "")
        )
        unit_price = _normalize_money(
            str(item.get("unit_price") or item.get("prixUnitaireHT") or item.get("prix") or "")
        )
        line_total = _normalize_money(
            str(item.get("line_total") or item.get("totalHT") or item.get("total") or "")
        )
        if description or quantity or unit_price or line_total:
            rows.append(
                {
                    "description": description or "?",
                    "quantity": quantity or "?",
                    "unit_price": unit_price or "?",
                    "line_total": line_total or "?",
                }
            )
    return rows


def _extract_rows_from_raw_text(raw_text: str) -> tuple[list[dict[str, str]], list[str]]:
    lines = [line.strip() for line in (raw_text or "").splitlines() if line.strip()]
    if not lines:
        return [], []

    normalized_lines = [_normalize_for_match(line) for line in lines]
    header_idx = None
    for index, line in enumerate(normalized_lines):
        if "description" in line and ("prix" in line or "total" in line):
            header_idx = index
            break
    if header_idx is None:
        return [], []

    stop_words = (
        "sous total",
        "total",
        "tva",
        "signature",
        "mode de paiement",
        "date d'echeance",
    )
    money_pattern = re.compile(r"\d[\d\s]*(?:[.,]\d{1,2})?\s*€?")

    rows: list[dict[str, str]] = []
    evidence: list[str] = []

    for idx in range(header_idx + 1, len(lines)):
        raw_line = lines[idx]
        norm_line = normalized_lines[idx]
        if any(norm_line.startswith(word) for word in stop_words):
            break

        matches = list(money_pattern.finditer(raw_line))
        if len(matches) < 2:
            continue

        unit_match = matches[-2]
        total_match = matches[-1]
        unit_price = _normalize_money(unit_match.group(0))
        line_total = _normalize_money(total_match.group(0))

        prefix = raw_line[: unit_match.start()].strip()
        prefix_tokens = prefix.split()
        quantity = ""
        description_tokens = prefix_tokens
        if prefix_tokens:
            quantity_candidate = _normalize_quantity_token(prefix_tokens[-1])
            if quantity_candidate:
                quantity = quantity_candidate
                description_tokens = prefix_tokens[:-1]

        description = " ".join(description_tokens).strip()
        if not description:
            continue

        rows.append(
            {
                "description": description,
                "quantity": quantity or "?",
                "unit_price": unit_price or "?",
                "line_total": line_total or "?",
            }
        )
        evidence.append(raw_line)

    return rows, evidence


def _build_table_answer(rows: list[dict[str, str]]) -> str:
    parts = []
    for row in rows:
        parts.append(
            f"{row['description']} | qty={row['quantity']} | prix={row['unit_price']} | total={row['line_total']}"
        )
    return "\n".join(parts)


def _try_answer_table_question(question: str, data: Any, raw_text: str) -> DocumentAskResponse | None:
    if not _is_table_question(question):
        return None

    rows = _extract_rows_from_structured_data(data)
    evidence: list[str] = []
    fields_used = ["data.extra.articles"] if rows else []

    if not rows:
        rows, evidence = _extract_rows_from_raw_text(raw_text)
        if rows:
            fields_used = ["context.ocr_text"]

    if not rows:
        return DocumentAskResponse(
            answer=NOT_FOUND_ANSWER,
            found=False,
            fields_used=[],
            evidence=[],
            confidence=0.0,
        )

    answer = _build_table_answer(rows)
    if not evidence:
        evidence = [answer.splitlines()[0]]

    known_qty = sum(1 for row in rows if row["quantity"] != "?")
    confidence = 0.9 if known_qty == len(rows) else 0.75
    return DocumentAskResponse(
        answer=answer,
        found=True,
        fields_used=fields_used,
        evidence=evidence[:5],
        confidence=confidence,
    )


def _extract_total_answer(data: Any, raw_text: str) -> DocumentAskResponse | None:
    field_match = _find_value_with_path(
        data,
        {
            "montant",
            "total",
            "montant_total",
            "total_ttc",
            "amount_total",
            "invoice_total",
        },
    )
    if field_match:
        path, value = field_match
        normalized = _normalize_money(value) or value
        return DocumentAskResponse(
            answer=f"Montant total: {normalized}",
            found=True,
            fields_used=[path],
            evidence=[f"{path}={value}"],
            confidence=0.95,
        )

    match = re.search(
        r"(?im)^total\s*[:\-]?\s*([0-9][0-9\s.,]*)\s*€?\s*$",
        raw_text or "",
    )
    if match:
        value = _normalize_money(match.group(1)) or match.group(1).strip()
        return DocumentAskResponse(
            answer=f"Montant total: {value}",
            found=True,
            fields_used=["context.ocr_text"],
            evidence=[match.group(0).strip()],
            confidence=0.85,
        )
    return None


def _extract_tva_answer(data: Any, raw_text: str) -> DocumentAskResponse | None:
    field_match = _find_value_with_path(
        data,
        {"tva", "taux_tva", "vat", "taxe", "tax_rate"},
    )
    if field_match:
        path, value = field_match
        value_text = value.strip()
        if value_text and "%" not in value_text:
            value_text = f"{value_text}%"
        return DocumentAskResponse(
            answer=f"TVA: {value_text}",
            found=True,
            fields_used=[path],
            evidence=[f"{path}={value}"],
            confidence=0.9,
        )

    match = re.search(
        r"(?im)^(?:taux\s*)?tva\s*[:\-]?\s*([0-9]+(?:[.,][0-9]+)?\s*%?)",
        raw_text or "",
    )
    if match:
        value_text = match.group(1).strip()
        if "%" not in value_text:
            value_text = f"{value_text}%"
        return DocumentAskResponse(
            answer=f"TVA: {value_text}",
            found=True,
            fields_used=["context.ocr_text"],
            evidence=[match.group(0).strip()],
            confidence=0.85,
        )
    return None


def _extract_date_answer(question: str, data: Any, raw_text: str) -> DocumentAskResponse | None:
    wants_due_date = "echeance" in _normalize_for_match(question)
    due_date_match = re.search(
        r"(?is)date\s+d[' ]?echeance\s*[:\-]?\s*([0-9]{1,2}[/-][0-9]{1,2}[/-][0-9]{2,4})",
        raw_text or "",
    )
    if wants_due_date and due_date_match:
        due_date = due_date_match.group(1).strip()
        return DocumentAskResponse(
            answer=f"Date d'echeance: {due_date}",
            found=True,
            fields_used=["context.ocr_text"],
            evidence=[due_date_match.group(0).strip()],
            confidence=0.88,
        )

    field_match = _find_value_with_path(
        data,
        {"date", "date_facture", "invoice_date", "document_date"},
    )
    if field_match:
        path, value = field_match
        return DocumentAskResponse(
            answer=f"Date du document: {value}",
            found=True,
            fields_used=[path],
            evidence=[f"{path}={value}"],
            confidence=0.92,
        )

    date_match = re.search(
        r"(?im)^date\s*[:\-]?\s*([0-9]{1,2}[/-][0-9]{1,2}[/-][0-9]{2,4})",
        raw_text or "",
    )
    if date_match:
        value = date_match.group(1).strip()
        return DocumentAskResponse(
            answer=f"Date du document: {value}",
            found=True,
            fields_used=["context.ocr_text"],
            evidence=[date_match.group(0).strip()],
            confidence=0.85,
        )
    return None


def _extract_email_answer(data: Any, raw_text: str) -> DocumentAskResponse | None:
    field_match = _find_value_with_path(data, {"email", "mail", "courriel"})
    if field_match and field_match[1].strip().lower() not in {"none", "null", "nan"}:
        path, value = field_match
        return DocumentAskResponse(
            answer=f"Email: {value}",
            found=True,
            fields_used=[path],
            evidence=[f"{path}={value}"],
            confidence=0.9,
        )

    email_match = re.search(r"([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})", raw_text or "")
    if email_match:
        email = email_match.group(1)
        return DocumentAskResponse(
            answer=f"Email: {email}",
            found=True,
            fields_used=["context.ocr_text"],
            evidence=[email],
            confidence=0.82,
        )
    return None


def _extract_address_answer(data: Any, raw_text: str) -> DocumentAskResponse | None:
    field_match = _find_value_with_path(data, {"adresse", "address"})
    if field_match and field_match[1].strip().lower() not in {"none", "null", "nan"}:
        path, value = field_match
        return DocumentAskResponse(
            answer=f"Adresse: {value}",
            found=True,
            fields_used=[path],
            evidence=[f"{path}={value}"],
            confidence=0.88,
        )

    address_match = re.search(
        r"(?im)^\s*\d{1,5}\s+[A-Za-z0-9 .,'-]+$",
        raw_text or "",
    )
    if address_match:
        address = address_match.group(0).strip()
        return DocumentAskResponse(
            answer=f"Adresse: {address}",
            found=True,
            fields_used=["context.ocr_text"],
            evidence=[address],
            confidence=0.76,
        )
    return None


def _extract_supplier_answer(data: Any, raw_text: str) -> DocumentAskResponse | None:
    field_match = _find_value_with_path(
        data,
        {"fournisseur", "emetteur", "issuer", "vendor", "societe", "company"},
    )
    if field_match:
        path, value = field_match
        return DocumentAskResponse(
            answer=f"Fournisseur: {value}",
            found=True,
            fields_used=[path],
            evidence=[f"{path}={value}"],
            confidence=0.9,
        )

    top_lines = [line.strip() for line in (raw_text or "").splitlines()[:5] if line.strip()]
    for line in top_lines:
        match = re.search(r"(?i)^(.+?)\s+facture\b", line)
        if match:
            supplier = match.group(1).strip(" -:")
            if supplier:
                return DocumentAskResponse(
                    answer=f"Fournisseur: {supplier}",
                    found=True,
                    fields_used=["context.ocr_text"],
                    evidence=[line],
                    confidence=0.82,
                )
    return None


def _extract_client_answer(data: Any, raw_text: str) -> DocumentAskResponse | None:
    field_match = _find_value_with_path(
        data,
        {"client", "customer", "nom_client", "client_name", "destinataire", "acheteur"},
    )
    if field_match:
        path, value = field_match
        return DocumentAskResponse(
            answer=f"Client: {value}",
            found=True,
            fields_used=[path],
            evidence=[f"{path}={value}"],
            confidence=0.9,
        )

    nom_match = _find_value_with_path(data, {"nom"})
    prenom_match = _find_value_with_path(data, {"prenom"})
    if nom_match or prenom_match:
        nom = nom_match[1].strip() if nom_match else ""
        prenom = prenom_match[1].strip() if prenom_match else ""
        full_name = f"{prenom} {nom}".strip()
        if full_name:
            fields_used = []
            evidence = []
            if prenom_match:
                fields_used.append(prenom_match[0])
                evidence.append(f"{prenom_match[0]}={prenom_match[1]}")
            if nom_match:
                fields_used.append(nom_match[0])
                evidence.append(f"{nom_match[0]}={nom_match[1]}")
            return DocumentAskResponse(
                answer=f"Client: {full_name}",
                found=True,
                fields_used=fields_used,
                evidence=evidence,
                confidence=0.86,
            )

    lines = [line.strip() for line in (raw_text or "").splitlines() if line.strip()]
    for idx, line in enumerate(lines):
        if _normalize_for_match(line) == "client":
            for candidate in lines[idx + 1 : idx + 4]:
                candidate_norm = _normalize_for_match(candidate)
                if not candidate_norm:
                    continue
                if "@" in candidate or "http" in candidate_norm or "www" in candidate_norm:
                    continue
                return DocumentAskResponse(
                    answer=f"Client: {candidate}",
                    found=True,
                    fields_used=["context.ocr_text"],
                    evidence=[f"Client -> {candidate}"],
                    confidence=0.8,
                )
    return None


def _extract_generic_field_answer(question: str, data: Any) -> DocumentAskResponse | None:
    tokens = _extract_question_tokens(question)
    if not tokens:
        return None

    fields = _flatten_scalar_fields(data)
    if not fields:
        return None

    best: tuple[int, str, str, str] | None = None
    for path, key_norm, value in fields:
        key_tokens = set(part for part in key_norm.split("_") if part)
        score = 0
        for token in tokens:
            alias_targets = GENERIC_TOKEN_ALIASES.get(token, set())
            if token in key_tokens or token in key_norm:
                score += 2
            elif key_norm in alias_targets or (key_tokens & alias_targets):
                score += 2
        if score > 0 and (best is None or score > best[0]):
            best = (score, path, key_norm, value)

    if best is None:
        return None

    _, path, key_norm, value = best
    label = key_norm.replace("_", " ").strip().title() or "Valeur"
    return DocumentAskResponse(
        answer=f"{label}: {value}",
        found=True,
        fields_used=[path],
        evidence=[f"{path}={value}"],
        confidence=0.78,
    )


def _try_answer_common_question(question: str, data: Any, raw_text: str) -> DocumentAskResponse | None:
    if _is_total_question(question):
        return _extract_total_answer(data, raw_text)
    if _is_tva_question(question):
        return _extract_tva_answer(data, raw_text)
    if _is_date_question(question):
        return _extract_date_answer(question, data, raw_text)
    if _is_email_question(question):
        return _extract_email_answer(data, raw_text)
    if _is_address_question(question):
        return _extract_address_answer(data, raw_text)
    if _is_client_question(question):
        return _extract_client_answer(data, raw_text)
    if _is_supplier_question(question):
        return _extract_supplier_answer(data, raw_text)
    return _extract_generic_field_answer(question, data)


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


def _build_prompt(
    question: str, structured_json_text: str, ocr_text: str, retry_mode: bool
) -> str:
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
    return f"SYSTEM:\n{QA_SYSTEM_PROMPT}\n\nUSER:\n{user_prompt}"


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

    deterministic = _try_answer_table_question(
        clean_question,
        document.data,
        document.raw_text or "",
    )
    if deterministic is not None:
        return _normalize_qa_response(deterministic)

    deterministic_common = _try_answer_common_question(
        clean_question,
        document.data,
        document.raw_text or "",
    )
    if deterministic_common is not None:
        return _normalize_qa_response(deterministic_common)

    structured_json_text = _serialize_structured_json(document.data)
    raw_text = _truncate_text((document.raw_text or "").strip(), MAX_OCR_CONTEXT_CHARS)

    last_error: Exception | None = None
    for retry_mode in (False, True):
        try:
            prompt = _build_prompt(
                clean_question,
                structured_json_text,
                raw_text,
                retry_mode=retry_mode,
            )
            model_text = call_llm(prompt)
            parsed = _extract_json_payload(model_text)
            validated = _validate_payload(parsed)
            return _normalize_qa_response(validated)
        except (json.JSONDecodeError, ValueError, ValidationError, RuntimeError) as exc:
            last_error = exc
            continue

    # Keep API stable for the frontend: if llama.cpp is unavailable,
    # return a safe deterministic shape instead of surfacing HTTP 500.
    return _normalize_qa_response(
        DocumentAskResponse(
            answer=NOT_FOUND_ANSWER,
            found=False,
            fields_used=[],
            evidence=[],
            confidence=0.0,
        )
    )
