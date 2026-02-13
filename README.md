# OCR Docs PFE

OCR Docs PFE is a full document processing app:
- upload PDF or image files,
- extract OCR text,
- build structured JSON fields,
- enrich output with Ollama (Llama),
- store and browse documents in PostgreSQL.

## Project Stack

- Backend: FastAPI + SQLAlchemy
- Frontend: React + Vite
- Database: PostgreSQL
- OCR engines: Local OCR (RapidOCR/Tesseract) or GLM OCR API
- LLM: Ollama (`llama3.1`)
- Runtime: Docker Compose

## Repository Structure

- `app/`: FastAPI API, OCR services, Llama services, DB layer
- `frontend/`: React client
- `docker-compose.yml`: full local stack
- `Dockerfile.backend`: backend image
- `.env.example`: environment variable template

## Main Features

- Upload supported files: `.pdf`, `.jpg`, `.jpeg`, `.png`
- OCR extraction from uploaded documents
- Invoice-like field extraction to JSON
- Document history view from database
- Llama processing and JSON refinement
- Save and merge structured data per document

## Quick Start (Docker)

Run all services:

```bash
docker compose up --build -d
```

Access:

- Frontend: `http://localhost:5180`
- API docs (through proxy): `http://localhost:5180/api/docs`

Useful commands:

```bash
docker compose ps
docker compose logs -f
docker compose down
```

Rebuild only frontend:

```bash
docker compose build --no-cache frontend
docker compose up -d --force-recreate frontend
```

## Local Development (Without Docker)

### 1) Backend

```bash
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Local API:

- `http://127.0.0.1:8000`
- `http://127.0.0.1:8000/docs`

### 2) Frontend

```bash
cd frontend
npm install
npm run dev
```

Default frontend API target is `http://127.0.0.1:8000`.

Optional override:

```dotenv
# frontend/.env
VITE_API_BASE_URL=http://127.0.0.1:8000
```

## Environment Variables

Copy `.env.example` to `.env`, then adapt values for your setup.

Important variables:

- `DATABASE_URL`
- `FASTAPI_ROOT_PATH`
- `OLLAMA_BASE_URL`
- `OLLAMA_MODEL`
- `GLM_OCR_PROVIDER`
- `GLM_OCR_USE_LOCAL`
- `GLM_OCR_API_KEY`
- `GLM_OCR_API_URL`
- `OCR_LANGS`

## OCR Modes

OCR mode is selected from environment configuration:

1. `GLM_OCR_USE_LOCAL=1` forces local OCR.
2. `GLM_OCR_PROVIDER=local` uses local OCR.
3. `GLM_OCR_PROVIDER=official` with `GLM_OCR_API_KEY` uses official GLM OCR.
4. `GLM_OCR_API_URL` uses custom OCR endpoint (multipart mode).
5. `GLM_OCR_MOCK=1` returns mock OCR output for local testing.

## API Endpoints

### `GET /`

Health endpoint.

### `POST /upload`

Upload + OCR + initial JSON extraction + DB save.

### `POST /ocr`

Run local OCR only, returns `{ "text": "..." }`.

### `GET /documents`

List all stored documents, newest first.

### `POST /generate_with_llama`

Generate Llama output from OCR text.

### `POST /process_with_llama`

Generate Llama output and try to return structured JSON.

Payload fields:

- `text` (required)
- `instruction` (optional)
- `document_id` (optional)
- `sync_data` (optional, default `false`)

### `PUT /documents/{document_id}/data`

Save structured JSON for one document.

Payload fields:

- `data` (required JSON object)
- `merge` (optional, default `true`)

## cURL Examples

Upload file:

```bash
curl -F "file=@C:\path\to\invoice.png" http://127.0.0.1:8000/upload
```

Process with Llama:

```bash
curl -X POST http://127.0.0.1:8000/process_with_llama ^
  -H "Content-Type: application/json" ^
  -d "{\"text\":\"...\",\"instruction\":\"Extract invoice number and total\",\"document_id\":1,\"sync_data\":true}"
```

## Database Model

Table: `documents`

- `id` (integer, primary key)
- `file_name` (string)
- `data` (JSONB)
- `raw_text` (text, nullable)
- `llama_output` (text, nullable)
- `date_uploaded` (timestamp)

## Troubleshooting

- Frontend still shows old UI:
  - rebuild/recreate frontend container,
  - hard refresh browser (`Ctrl + F5`).
- Ollama errors:
  - check Ollama service is running,
  - check model is present (`ollama pull llama3.1`).
- Local OCR errors:
  - verify Tesseract or RapidOCR installation,
  - verify `OCR_LANGS` value.
- CORS issues:
  - verify backend `CORS_ALLOW_ORIGINS`.

## Git Notes

Ignored by git:

- `.env`
- `venv/`
- `uploads/`
- `models/`
- `frontend/node_modules/`
- `frontend/dist/`
