# REVIEW Feature Guide

This document describes the additive review workflow introduced on top of the existing OCR pipeline.

## What is added

- New backend routes (existing routes unchanged):
  - `POST /review/normalize`
  - `GET /review/documents/{id}`
  - `PUT /review/documents/{id}`
  - `GET /review/documents/{id}/preview/meta`
  - `GET /review/documents/{id}/preview?page=1`
- New PostgreSQL additive tables:
  - `suppliers`
  - `cities`
  - `countries`
  - `document_reviews`
  - `document_assets`
- New React route:
  - `/documents/:id/review`

## Environment variables

Add these to your `.env`:

```dotenv
REVIEW_FEATURE_ENABLED=1
FUZZY_THRESHOLD=85
FUZZY_MODE_DEFAULT=suggest
REVIEW_FILE_MATCH_WINDOW_SECONDS=900
REVIEW_BBOX_ENRICH_ENABLED=1
REVIEW_BBOX_ENRICH_MIN_SCORE=55
VITE_REVIEW_FEATURE_ENABLED=1
VITE_ENHANCED_HIGHLIGHTS=1
VITE_REVIEW_AUTO_ZOOM_DEFAULT=0
```

A ready template is provided in `.env.review.example`.

## Install optional fuzzy dependency

```bash
pip install -r requirements-review.txt
```

`rapidfuzz` is used when available. The code has a fallback matcher for environments where `rapidfuzz` is not installed.

## Apply migration and seed reference data

```bash
python scripts/apply_review_migration.py
python scripts/seed_reference_entities.py
```

## Review workflow

1. Open documents list in frontend.
2. Click `Review` for a document.
3. In `/documents/:id/review`:
   - `Obtenir suggestions` -> calls `POST /review/normalize` in `suggest` mode.
   - `Appliquer suggestions` -> calls `POST /review/normalize` in `apply` mode.
   - `Sauvegarder corrections` -> calls `PUT /review/documents/{id}` with `status=in_review`.
   - `Valider` -> calls `PUT /review/documents/{id}` with `status=validated`.

### Enhanced highlights toggles

- `VITE_ENHANCED_HIGHLIGHTS=1` enables fade-in, auto-scroll, multi-highlight, invalid/error colors, and pulse.
- `VITE_ENHANCED_HIGHLIGHTS=0` falls back to the previous single-highlight behavior.
- `VITE_REVIEW_AUTO_ZOOM_DEFAULT=0` starts with auto-zoom OFF (user can toggle ON/OFF in UI).

## Data preservation policy

No overwrite of the original extraction pipeline payload:

- Original extracted data remains in `documents.data`.
- Review data is stored separately in `document_reviews`:
  - `raw_extracted_fields`
  - `normalized_fields`
  - `user_corrected_fields`

### Automatic bbox enrichment

- If `REVIEW_BBOX_ENRICH_ENABLED=1`, `GET /review/documents/{id}` tries to enrich missing field bboxes additively.
- It uses OCR line tokens from the original uploaded file and approximate string matching.
- Only missing bbox metadata is injected into `normalized_fields`; original extracted values remain unchanged.
- `REVIEW_BBOX_ENRICH_MIN_SCORE` controls how strict matching is (default `55`).

## Notes on preview

- The review page tries to resolve a document file from `uploads/` using an additive `document_assets` mapping.
- For old documents where exact file linkage was not stored historically, a timestamp-based heuristic is used.
