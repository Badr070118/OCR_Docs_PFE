# GLM-OCR Frontend

React UI for the FastAPI OCR backend with LLaMA post-processing.

## Install
```bash
npm install
```

## Run (dev)
```bash
npm run dev
```

The app runs on `http://localhost:5180` by default.

## Configure API base URL
By default the frontend calls `http://127.0.0.1:8000`.
To override, create a `.env` file in `frontend/`:
```bash
VITE_API_BASE_URL=http://127.0.0.1:8000
```

## CORS (FastAPI)
If the browser blocks requests, add CORS to your FastAPI app:
```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5180"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

If you use CRA instead of Vite, update the origin to `http://localhost:3000`.

## Flow
- Upload file -> OCR text displayed.
- Click "Generer avec IA" to send OCR text to `/process_with_llama`.
