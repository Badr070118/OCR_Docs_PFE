from __future__ import annotations

import json
import mimetypes
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.review.config import REVIEW_FILE_MATCH_WINDOW_SECONDS, UPLOADS_DIR
from app.review.fuzzy_normalizer import ReferenceEntity

_SCHEMA_READY = False
_SCHEMA_LOCK = Lock()
_SCHEMA_FILE = Path(__file__).with_name("migrations") / "001_review_schema.sql"
_ALLOWED_REFERENCE_TABLES = {"suppliers", "cities", "countries"}


def _split_sql_statements(sql_script: str) -> list[str]:
    statements: list[str] = []
    current: list[str] = []
    for line in sql_script.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        current.append(line)
        if stripped.endswith(";"):
            statements.append("\n".join(current).strip())
            current = []
    if current:
        statements.append("\n".join(current).strip())
    return statements


def ensure_review_schema(db: Session) -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return

    with _SCHEMA_LOCK:
        if _SCHEMA_READY:
            return

        sql_script = _SCHEMA_FILE.read_text(encoding="utf-8")
        for statement in _split_sql_statements(sql_script):
            db.execute(text(statement))
        db.commit()
        _SCHEMA_READY = True


def get_document(db: Session, document_id: int) -> dict[str, Any] | None:
    row = db.execute(
        text(
            """
            SELECT id, file_name, data, date_uploaded
            FROM documents
            WHERE id = :document_id
            """
        ),
        {"document_id": document_id},
    ).mappings().first()
    return dict(row) if row else None


def get_document_review(db: Session, document_id: int) -> dict[str, Any] | None:
    row = db.execute(
        text(
            """
            SELECT document_id, raw_extracted_fields, normalized_fields, user_corrected_fields, status
            FROM document_reviews
            WHERE document_id = :document_id
            """
        ),
        {"document_id": document_id},
    ).mappings().first()
    return dict(row) if row else None


def upsert_document_review(
    db: Session,
    *,
    document_id: int,
    raw_extracted_fields: dict[str, Any],
    normalized_fields: dict[str, Any],
    user_corrected_fields: dict[str, Any],
    status: str,
) -> None:
    db.execute(
        text(
            """
            INSERT INTO document_reviews (
                document_id,
                raw_extracted_fields,
                normalized_fields,
                user_corrected_fields,
                status,
                created_at,
                updated_at
            )
            VALUES (
                :document_id,
                CAST(:raw_extracted_fields AS JSONB),
                CAST(:normalized_fields AS JSONB),
                CAST(:user_corrected_fields AS JSONB),
                :status,
                NOW(),
                NOW()
            )
            ON CONFLICT (document_id) DO UPDATE SET
                raw_extracted_fields = EXCLUDED.raw_extracted_fields,
                normalized_fields = EXCLUDED.normalized_fields,
                user_corrected_fields = EXCLUDED.user_corrected_fields,
                status = EXCLUDED.status,
                updated_at = NOW()
            """
        ),
        {
            "document_id": document_id,
            "raw_extracted_fields": json.dumps(raw_extracted_fields or {}),
            "normalized_fields": json.dumps(normalized_fields or {}),
            "user_corrected_fields": json.dumps(user_corrected_fields or {}),
            "status": status,
        },
    )
    db.commit()


def load_reference_entities(db: Session, table_name: str) -> list[ReferenceEntity]:
    if table_name not in _ALLOWED_REFERENCE_TABLES:
        raise ValueError(f"Unsupported reference table: {table_name}")

    rows = db.execute(
        text(f"SELECT id, canonical_name, aliases FROM {table_name} ORDER BY canonical_name")
    ).mappings().all()

    entities: list[ReferenceEntity] = []
    for row in rows:
        aliases = row.get("aliases")
        if isinstance(aliases, str):
            try:
                aliases = json.loads(aliases)
            except json.JSONDecodeError:
                aliases = []
        if not isinstance(aliases, list):
            aliases = []
        entities.append(
            ReferenceEntity(
                id=int(row["id"]),
                canonical_name=str(row.get("canonical_name") or ""),
                aliases=[str(item) for item in aliases if str(item).strip()],
            )
        )
    return entities


def get_document_asset(db: Session, document_id: int) -> dict[str, Any] | None:
    row = db.execute(
        text(
            """
            SELECT document_id, stored_file_name, mime_type, source
            FROM document_assets
            WHERE document_id = :document_id
            """
        ),
        {"document_id": document_id},
    ).mappings().first()
    return dict(row) if row else None


def upsert_document_asset(
    db: Session,
    *,
    document_id: int,
    stored_file_name: str,
    mime_type: str,
    source: str = "heuristic",
) -> dict[str, Any]:
    db.execute(
        text(
            """
            INSERT INTO document_assets (
                document_id,
                stored_file_name,
                mime_type,
                source,
                created_at
            )
            VALUES (:document_id, :stored_file_name, :mime_type, :source, NOW())
            ON CONFLICT (document_id) DO UPDATE SET
                stored_file_name = EXCLUDED.stored_file_name,
                mime_type = EXCLUDED.mime_type,
                source = EXCLUDED.source
            """
        ),
        {
            "document_id": document_id,
            "stored_file_name": stored_file_name,
            "mime_type": mime_type,
            "source": source,
        },
    )
    db.commit()
    return {
        "document_id": document_id,
        "stored_file_name": stored_file_name,
        "mime_type": mime_type,
        "source": source,
    }


def _guess_mime_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def resolve_or_link_document_asset(
    db: Session,
    *,
    document_id: int,
    date_uploaded: datetime | None,
) -> dict[str, Any] | None:
    existing = get_document_asset(db, document_id)
    if existing:
        return existing

    if not UPLOADS_DIR.exists():
        return None

    used_names = {
        row["stored_file_name"]
        for row in db.execute(text("SELECT stored_file_name FROM document_assets")).mappings().all()
    }

    candidates = [
        path
        for path in UPLOADS_DIR.iterdir()
        if path.is_file() and path.suffix.lower() in {".pdf", ".png", ".jpg", ".jpeg"}
    ]
    if not candidates:
        return None

    if date_uploaded is None:
        chosen = min(candidates, key=lambda item: item.stat().st_mtime)
    else:
        uploaded_ts = date_uploaded.timestamp()
        candidates.sort(key=lambda item: abs(item.stat().st_mtime - uploaded_ts))
        chosen = candidates[0]
        delta = abs(chosen.stat().st_mtime - uploaded_ts)
        if delta > REVIEW_FILE_MATCH_WINDOW_SECONDS:
            unlinked = [item for item in candidates if item.name not in used_names]
            if unlinked:
                chosen = unlinked[0]

    return upsert_document_asset(
        db,
        document_id=document_id,
        stored_file_name=chosen.name,
        mime_type=_guess_mime_type(chosen),
        source="heuristic",
    )


def resolve_asset_path(asset: dict[str, Any]) -> Path:
    return UPLOADS_DIR / str(asset["stored_file_name"])
