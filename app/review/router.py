from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.review.config import REVIEW_FEATURE_ENABLED
from app.review.schemas import (
    NormalizeRequest,
    NormalizeResponse,
    ReviewDocumentResponse,
    ReviewPreviewMetaResponse,
    ReviewUpdateRequest,
)
from app.review.service import ReviewService

review_router = APIRouter(prefix="/review", tags=["review"])


def _ensure_feature_enabled() -> None:
    if not REVIEW_FEATURE_ENABLED:
        raise HTTPException(status_code=404, detail="Review feature is disabled.")


def get_review_service(db: Session = Depends(get_db)) -> ReviewService:
    return ReviewService(db)


@review_router.post("/normalize", response_model=NormalizeResponse)
def normalize_review_fields(
    payload: NormalizeRequest,
    service: ReviewService = Depends(get_review_service),
) -> NormalizeResponse:
    _ensure_feature_enabled()
    result = service.normalize_fields(
        document_id=payload.document_id,
        fields=payload.fields,
        mode=payload.mode,
    )
    return NormalizeResponse(**result)


@review_router.get("/documents/{document_id}", response_model=ReviewDocumentResponse)
def get_review_document(
    document_id: int,
    service: ReviewService = Depends(get_review_service),
) -> ReviewDocumentResponse:
    _ensure_feature_enabled()
    payload = service.get_review_document(document_id)
    return ReviewDocumentResponse(**payload)


@review_router.put("/documents/{document_id}", response_model=ReviewDocumentResponse)
def update_review_document(
    document_id: int,
    payload: ReviewUpdateRequest,
    service: ReviewService = Depends(get_review_service),
) -> ReviewDocumentResponse:
    _ensure_feature_enabled()
    updated = service.update_review_document(
        document_id=document_id,
        user_corrected_fields=payload.user_corrected_fields,
        normalized_fields=payload.normalized_fields,
        status=payload.status,
    )
    return ReviewDocumentResponse(**updated)


@review_router.get("/documents/{document_id}/preview/meta", response_model=ReviewPreviewMetaResponse)
def review_preview_meta(
    document_id: int,
    service: ReviewService = Depends(get_review_service),
) -> ReviewPreviewMetaResponse:
    _ensure_feature_enabled()
    payload = service.get_preview_meta(document_id)
    return ReviewPreviewMetaResponse(**payload)


@review_router.get("/documents/{document_id}/preview")
def review_preview_file(
    document_id: int,
    page: int = Query(1, ge=1),
    service: ReviewService = Depends(get_review_service),
) -> Response:
    _ensure_feature_enabled()
    content, media_type = service.render_preview_page(document_id, page)
    return Response(content=content, media_type=media_type)
