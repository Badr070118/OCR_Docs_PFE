from __future__ import annotations

import io
from copy import deepcopy
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.review.bbox_enricher import enrich_fields_with_bboxes
from app.review.config import (
    FUZZY_MODE_DEFAULT,
    FUZZY_THRESHOLD,
    REVIEW_BBOX_ENRICH_ENABLED,
    REVIEW_BBOX_ENRICH_MIN_SCORE,
)
from app.review.fuzzy_normalizer import FuzzyNormalizer
from app.review import repository

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover - optional runtime dependency
    fitz = None


_FIELD_NORMALIZER = {
    "supplier_name": "supplier",
    "supplier": "supplier",
    "fournisseur": "supplier",
    "city": "city",
    "ville": "city",
    "country": "country",
    "pays": "country",
}


class ReviewService:
    def __init__(self, db: Session):
        self.db = db
        self.normalizer = FuzzyNormalizer(threshold=FUZZY_THRESHOLD)

    def _require_document(self, document_id: int) -> dict[str, Any]:
        repository.ensure_review_schema(self.db)
        document = repository.get_document(self.db, document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="Document not found.")
        return document

    def _normalize_one_field(self, field_name: str, value: Any) -> dict[str, Any]:
        text_value = "" if value is None else str(value)
        kind = _FIELD_NORMALIZER.get(field_name.strip().lower())
        if kind == "supplier":
            entities = repository.load_reference_entities(self.db, "suppliers")
            match = self.normalizer.normalize_supplier(text_value, entities)
        elif kind == "city":
            entities = repository.load_reference_entities(self.db, "cities")
            match = self.normalizer.normalize_city(text_value, entities)
        elif kind == "country":
            entities = repository.load_reference_entities(self.db, "countries")
            match = self.normalizer.normalize_country(text_value, entities)
        else:
            match = {
                "canonical": text_value,
                "score": 0.0,
                "matched_id": None,
                "action": "keep",
            }

        return {
            "original": value,
            "suggested": match["canonical"],
            "score": float(match["score"]),
            "matched_id": match["matched_id"],
            "action": match["action"],
        }

    @staticmethod
    def _as_field_payload(field_payload: Any) -> dict[str, Any]:
        if isinstance(field_payload, dict):
            return field_payload
        if hasattr(field_payload, "model_dump"):
            payload = field_payload.model_dump()
            if isinstance(payload, dict):
                return payload
        if hasattr(field_payload, "dict"):
            payload = field_payload.dict()
            if isinstance(payload, dict):
                return payload
        return {"value": field_payload}

    @staticmethod
    def _extract_field_value(field_payload: Any) -> Any:
        payload = ReviewService._as_field_payload(field_payload)
        if "value" in payload:
            return payload.get("value")
        if "text" in payload:
            return payload.get("text")
        return payload

    @staticmethod
    def _has_bbox(field_payload: Any) -> bool:
        payload = ReviewService._as_field_payload(field_payload)
        bbox = payload.get("bbox")
        return isinstance(bbox, list) and len(bbox) == 4

    def _enrich_normalized_bboxes(
        self,
        *,
        document: dict[str, Any],
        raw: dict[str, Any],
        normalized: dict[str, Any],
        corrected: dict[str, Any],
        status: str,
    ) -> dict[str, Any]:
        if not REVIEW_BBOX_ENRICH_ENABLED:
            return normalized

        review_keys = sorted(set(raw.keys()) | set(normalized.keys()) | set(corrected.keys()))
        if not review_keys:
            return normalized

        missing_bbox_keys: list[str] = []
        field_values: dict[str, Any] = {}

        for key in review_keys:
            value_source = corrected.get(key)
            if value_source is None:
                value_source = normalized.get(key)
            if value_source is None:
                value_source = raw.get(key)

            value = self._extract_field_value(value_source)
            if value is None or not str(value).strip():
                continue
            field_values[key] = value

            normalized_payload = normalized.get(key)
            if not self._has_bbox(normalized_payload):
                missing_bbox_keys.append(key)

        if not missing_bbox_keys:
            return normalized

        asset = repository.resolve_or_link_document_asset(
            self.db,
            document_id=int(document["id"]),
            date_uploaded=document.get("date_uploaded"),
        )
        if not asset:
            return normalized

        asset_path = repository.resolve_asset_path(asset)
        if not asset_path.exists():
            return normalized

        match_input = {key: field_values[key] for key in missing_bbox_keys if key in field_values}
        if not match_input:
            return normalized

        bbox_matches = enrich_fields_with_bboxes(
            asset_path,
            match_input,
            min_score=REVIEW_BBOX_ENRICH_MIN_SCORE,
        )
        if not bbox_matches:
            return normalized

        merged_normalized = deepcopy(normalized)
        changed = False

        for key in review_keys:
            if key in merged_normalized:
                continue
            source = corrected.get(key)
            if source is None:
                source = raw.get(key)

            if isinstance(source, dict):
                payload = deepcopy(source)
                payload.setdefault("value", self._extract_field_value(source))
            else:
                payload = {"value": self._extract_field_value(source)}
            merged_normalized[key] = payload

        for key, bbox_data in bbox_matches.items():
            payload = ReviewService._as_field_payload(merged_normalized.get(key))
            if self._has_bbox(payload):
                continue

            payload["value"] = field_values.get(key, payload.get("value"))
            payload["bbox"] = bbox_data.get("bbox")
            payload["page"] = bbox_data.get("page", 1)
            payload["bbox_relative"] = bool(bbox_data.get("bbox_relative", False))
            if payload.get("confidence") is None:
                payload["confidence"] = bbox_data.get("confidence")
            payload["bbox_score"] = bbox_data.get("bbox_score")
            merged_normalized[key] = payload
            changed = True

        if changed:
            repository.upsert_document_review(
                self.db,
                document_id=int(document["id"]),
                raw_extracted_fields=raw,
                normalized_fields=merged_normalized,
                user_corrected_fields=corrected,
                status=status,
            )

        return merged_normalized

    def normalize_fields(
        self,
        *,
        document_id: int,
        fields: dict[str, Any],
        mode: str | None,
    ) -> dict[str, Any]:
        document = self._require_document(document_id)
        final_mode = (mode or FUZZY_MODE_DEFAULT).strip().lower()
        if final_mode not in {"suggest", "apply"}:
            final_mode = "suggest"

        suggestions: dict[str, Any] = {}
        applied_fields: dict[str, Any] = {}

        for field_name, field_payload in fields.items():
            payload = self._as_field_payload(field_payload)
            value = payload.get("value")
            suggestion = self._normalize_one_field(field_name, value)
            suggestions[field_name] = suggestion

            if final_mode == "apply":
                next_payload = deepcopy(payload)
                if suggestion["action"] == "replace":
                    next_payload["value"] = suggestion["suggested"]
                else:
                    next_payload["value"] = suggestion["original"]
                next_payload["normalization"] = {
                    "score": suggestion["score"],
                    "matched_id": suggestion["matched_id"],
                    "action": suggestion["action"],
                }
                applied_fields[field_name] = next_payload

        if final_mode == "apply":
            existing_review = repository.get_document_review(self.db, document_id) or {}
            merged_normalized = {}
            if isinstance(existing_review.get("normalized_fields"), dict):
                merged_normalized.update(existing_review["normalized_fields"])
            merged_normalized.update(applied_fields)

            repository.upsert_document_review(
                self.db,
                document_id=document_id,
                raw_extracted_fields=document.get("data") or {},
                normalized_fields=merged_normalized,
                user_corrected_fields=existing_review.get("user_corrected_fields") or {},
                status=existing_review.get("status") or "in_review",
            )

        return {
            "suggestions": suggestions,
            "applied_fields": applied_fields if final_mode == "apply" else None,
        }

    def get_review_document(self, document_id: int) -> dict[str, Any]:
        document = self._require_document(document_id)
        review = repository.get_document_review(self.db, document_id) or {}

        raw = review.get("raw_extracted_fields")
        if not isinstance(raw, dict) or not raw:
            raw = document.get("data") or {}

        normalized = review.get("normalized_fields")
        if not isinstance(normalized, dict):
            normalized = {}

        corrected = review.get("user_corrected_fields")
        if not isinstance(corrected, dict):
            corrected = {}

        status = review.get("status")
        if status not in {"in_review", "validated"}:
            status = "in_review"

        normalized = self._enrich_normalized_bboxes(
            document=document,
            raw=raw,
            normalized=normalized,
            corrected=corrected,
            status=status,
        )

        return {
            "document_id": document_id,
            "file_name": str(document.get("file_name") or ""),
            "raw_extracted_fields": raw,
            "normalized_fields": normalized,
            "user_corrected_fields": corrected,
            "status": status,
        }

    def update_review_document(
        self,
        *,
        document_id: int,
        normalized_fields: dict[str, Any],
        user_corrected_fields: dict[str, Any],
        status: str,
    ) -> dict[str, Any]:
        document = self._require_document(document_id)
        safe_status = status if status in {"in_review", "validated"} else "in_review"

        repository.upsert_document_review(
            self.db,
            document_id=document_id,
            raw_extracted_fields=document.get("data") or {},
            normalized_fields=normalized_fields or {},
            user_corrected_fields=user_corrected_fields or {},
            status=safe_status,
        )

        return self.get_review_document(document_id)

    def get_preview_meta(self, document_id: int) -> dict[str, Any]:
        document = self._require_document(document_id)
        asset = repository.resolve_or_link_document_asset(
            self.db,
            document_id=document_id,
            date_uploaded=document.get("date_uploaded"),
        )
        if not asset:
            return {"available": False, "file_type": None, "page_count": 0}

        asset_path = repository.resolve_asset_path(asset)
        if not asset_path.exists():
            return {"available": False, "file_type": None, "page_count": 0}

        suffix = asset_path.suffix.lower()
        if suffix == ".pdf":
            if fitz is None:
                raise HTTPException(
                    status_code=500,
                    detail="PyMuPDF is required to render PDF previews.",
                )
            with fitz.open(asset_path) as document_pdf:
                page_count = len(document_pdf)
            return {"available": True, "file_type": "pdf", "page_count": page_count}

        return {"available": True, "file_type": "image", "page_count": 1}

    def render_preview_page(self, document_id: int, page: int) -> tuple[bytes, str]:
        document = self._require_document(document_id)
        asset = repository.resolve_or_link_document_asset(
            self.db,
            document_id=document_id,
            date_uploaded=document.get("date_uploaded"),
        )
        if not asset:
            raise HTTPException(status_code=404, detail="No preview file found for this document.")

        asset_path = repository.resolve_asset_path(asset)
        if not asset_path.exists():
            raise HTTPException(status_code=404, detail="Preview file is missing on disk.")

        suffix = asset_path.suffix.lower()
        if suffix != ".pdf":
            return asset_path.read_bytes(), asset.get("mime_type") or "application/octet-stream"

        if fitz is None:
            raise HTTPException(
                status_code=500,
                detail="PyMuPDF is required to render PDF previews.",
            )

        with fitz.open(asset_path) as pdf:
            if page < 1 or page > len(pdf):
                raise HTTPException(status_code=400, detail="Invalid page number.")
            page_obj = pdf[page - 1]
            pix = page_obj.get_pixmap(matrix=fitz.Matrix(2, 2))
            buffer = io.BytesIO(pix.tobytes("png"))
            return buffer.getvalue(), "image/png"
