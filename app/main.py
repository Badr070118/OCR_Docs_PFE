import json
import shutil
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import (
    Document,
    create_db_and_tables,
    get_db,
    save_document,
    update_document_data,
    update_llama_output,
)
from app.invoice_ocr import invoice_ocr
from app.llama_service import (
    extract_hybrid_data_from_text,
    generate_from_llama,
    generate_hybrid_json_from_text,
    merge_hybrid_data,
)
from app.ocr import (
    extract_text_with_glm_ocr,
    extract_text_with_local_ocr,
    format_extracted_text_as_json,
)
from app.qa_service import ask_document_question
from app.review.router import review_router
from app.schemas import DocumentAskRequest, DocumentAskResponse, DocumentOut

FASTAPI_ROOT_PATH = (os.getenv("FASTAPI_ROOT_PATH") or "").strip()

app = FastAPI(
    title="GLM-OCR API",
    description="FastAPI service for OCR extraction and llama.cpp Llama processing.",
    version="1.0.0",
    root_path=FASTAPI_ROOT_PATH,
)

# Allow the frontend to call the API from the browser.
_cors_origins_raw = os.getenv(
    "CORS_ALLOW_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174,http://localhost:5180,http://127.0.0.1:5180",
)
_cors_origins = [origin.strip() for origin in _cors_origins_raw.split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(review_router)

UPLOADS_DIR = Path("uploads")
RESULTS_DIR = Path("results")
ALLOWED_CONTENT_TYPES = {"application/pdf", "image/jpeg", "image/png", "image/jpg"}
ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}


@app.on_event("startup")
def on_startup() -> None:
    # Ensure folders and database are ready when the server starts.
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    create_db_and_tables()


@app.get("/", tags=["health"])
def root() -> dict:
    return {"status": "API OK"}


class LlamaRequest(BaseModel):
    text: str
    instruction: str | None = None


class ProcessWithLlamaRequest(BaseModel):
    text: str
    instruction: str | None = None
    document_id: int | None = None
    sync_data: bool = False


class UpdateDocumentDataRequest(BaseModel):
    data: dict[str, Any]
    merge: bool = True


def _is_allowed_upload(file: UploadFile) -> bool:
    extension = Path(file.filename or "").suffix.lower()
    if file.content_type in ALLOWED_CONTENT_TYPES:
        return True
    return extension in ALLOWED_EXTENSIONS


@app.post("/upload", response_model=DocumentOut, tags=["documents"])
async def upload_file(
    file: UploadFile = File(...), db: Session = Depends(get_db)
) -> Document:
    if not _is_allowed_upload(file):
        raise HTTPException(status_code=400, detail="Unsupported file type.")

    original_name = Path(file.filename or "upload").name
    extension = Path(original_name).suffix.lower()
    safe_name = f"{uuid4().hex}{extension}"
    destination = UPLOADS_DIR / safe_name

    with destination.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        extracted_text = extract_text_with_glm_ocr(str(destination))
        structured_data = format_extracted_text_as_json(extracted_text)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    document = save_document(
        db, file_name=original_name, data=structured_data, raw_text=extracted_text
    )
    return document


@app.post("/ocr", tags=["ocr"])
async def run_local_ocr(file: UploadFile = File(...)) -> dict:
    if not _is_allowed_upload(file):
        raise HTTPException(status_code=400, detail="Unsupported file type.")

    original_name = Path(file.filename or "upload").name
    extension = Path(original_name).suffix.lower()
    safe_name = f"{uuid4().hex}{extension}"
    destination = UPLOADS_DIR / safe_name

    with destination.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        text = extract_text_with_local_ocr(str(destination))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {"text": text}


@app.post("/ocr/invoice-table", tags=["ocr"])
async def run_invoice_table_ocr(file: UploadFile = File(...)) -> dict:
    if not _is_allowed_upload(file):
        raise HTTPException(status_code=400, detail="Unsupported file type.")

    original_name = Path(file.filename or "upload").name
    extension = Path(original_name).suffix.lower()
    safe_name = f"{uuid4().hex}{extension}"
    destination = UPLOADS_DIR / safe_name

    with destination.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        result = invoice_ocr(str(destination))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return result


@app.get("/documents", response_model=list[DocumentOut], tags=["documents"])
def list_documents(db: Session = Depends(get_db)) -> list[Document]:
    return db.query(Document).order_by(Document.date_uploaded.desc()).all()


@app.post(
    "/documents/{document_id}/ask",
    response_model=DocumentAskResponse,
    tags=["documents"],
)
def ask_document(
    document_id: int,
    payload: DocumentAskRequest,
    db: Session = Depends(get_db),
) -> DocumentAskResponse:
    try:
        return ask_document_question(db, document_id, payload.question)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/generate_with_llama", tags=["llama"])
def generate_with_llama(payload: LlamaRequest) -> dict:
    # Expects OCR text; returns the Ollama Llama-generated result.
    try:
        generated = generate_from_llama(payload.text, payload.instruction)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"result": generated}


@app.post("/process_with_llama", tags=["llama"])
def process_with_llama(
    payload: ProcessWithLlamaRequest, db: Session = Depends(get_db)
) -> dict:
    try:
        generated = generate_from_llama(payload.text, payload.instruction)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    structured_data = extract_hybrid_data_from_text(generated)
    if structured_data is None:
        try:
            structured_data = generate_hybrid_json_from_text(
                payload.text, payload.instruction
            )
        except Exception:
            structured_data = None
    if structured_data is not None:
        generated = json.dumps(structured_data, ensure_ascii=False, indent=2)

    if payload.document_id is not None and payload.sync_data:
        existing_document = (
            db.query(Document).filter(Document.id == payload.document_id).first()
        )
        update_llama_output(db, payload.document_id, generated)
        if existing_document is not None and structured_data is not None:
            merged_data = merge_hybrid_data(existing_document.data, structured_data)
            updated_document = update_document_data(
                db, payload.document_id, merged_data
            )
            structured_data = updated_document.data if updated_document else merged_data

    return {
        "generated_text": generated,
        "document_id": payload.document_id,
        "structured_data": structured_data,
    }


@app.put("/documents/{document_id}/data", response_model=DocumentOut, tags=["documents"])
def save_document_structured_data(
    document_id: int,
    payload: UpdateDocumentDataRequest,
    db: Session = Depends(get_db),
) -> Document:
    document = db.query(Document).filter(Document.id == document_id).first()
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")

    final_data = (
        merge_hybrid_data(document.data, payload.data)
        if payload.merge
        else payload.data
    )
    updated = update_document_data(db, document_id, final_data)
    if updated is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return updated


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
