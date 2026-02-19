from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field


class ReviewFieldInput(BaseModel):
    value: Any = None
    bbox: Optional[list[float]] = None
    page: Optional[int] = None
    confidence: Optional[float] = None
    bbox_relative: Optional[bool] = None


class NormalizeRequest(BaseModel):
    document_id: int
    fields: Dict[str, ReviewFieldInput] = Field(default_factory=dict)
    mode: Literal["suggest", "apply"] | None = None


class SuggestionOut(BaseModel):
    original: Any
    suggested: Any
    score: float
    matched_id: int | None = None
    action: Literal["replace", "keep"]


class NormalizeResponse(BaseModel):
    suggestions: Dict[str, SuggestionOut]
    applied_fields: Dict[str, Dict[str, Any]] | None = None


class ReviewUpdateRequest(BaseModel):
    user_corrected_fields: Dict[str, Any] = Field(default_factory=dict)
    normalized_fields: Dict[str, Any] = Field(default_factory=dict)
    status: Literal["in_review", "validated"] = "in_review"


class ReviewDocumentResponse(BaseModel):
    document_id: int
    file_name: str
    raw_extracted_fields: Dict[str, Any]
    normalized_fields: Dict[str, Any]
    user_corrected_fields: Dict[str, Any]
    status: Literal["in_review", "validated"]


class ReviewPreviewMetaResponse(BaseModel):
    available: bool
    file_type: Literal["pdf", "image"] | None = None
    page_count: int = 0
