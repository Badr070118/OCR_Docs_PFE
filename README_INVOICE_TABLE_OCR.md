# Invoice Table OCR (Tesseract layout)

This project now includes a dedicated invoice-table OCR pipeline with layout-aware token extraction and table reconstruction.

## Prerequisites

1. Install Tesseract engine.
2. Install French and English language packs (`fra`, `eng`).
3. Install Python dependencies:

```bash
pip install -r requirements.txt
```

If you use Docker, rebuild backend image after dependency changes:

```bash
docker compose up -d --build backend
```

## Run quick test on `/samples`

Put up to 5 sample files (`.png`, `.jpg`, `.jpeg`, `.pdf`) in `samples/`, then run:

```bash
python tests/run_invoice_table_test.py
```

The script prints:
- OCR mean confidence
- detected table row count
- preview of extracted structured rows

## API endpoint

FastAPI route:

```text
POST /ocr/invoice-table
```

When deployed with `FASTAPI_ROOT_PATH=/api`, call:

```text
POST /api/ocr/invoice-table
```
