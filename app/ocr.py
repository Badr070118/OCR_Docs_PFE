import base64
import io
import os
import re
from pathlib import Path
from typing import Any, Callable, Dict, List

import requests
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
import numpy as np

try:
    import fitz  # PyMuPDF
except ImportError as exc:  # pragma: no cover - optional at runtime
    fitz = None
    _pymupdf_import_error = exc

try:
    from rapidocr_onnxruntime import RapidOCR
except ImportError:  # pragma: no cover - optional at runtime
    RapidOCR = None

try:
    import pytesseract
except ImportError:  # pragma: no cover - optional at runtime
    pytesseract = None


def _is_truthy(value: str | None) -> bool:
    return bool(value and value.strip().lower() in {"1", "true", "yes", "on"})


GLM_OCR_API_URL = (os.getenv("GLM_OCR_API_URL") or "").strip()
GLM_OCR_API_KEY = (os.getenv("GLM_OCR_API_KEY") or "").strip()
GLM_OCR_PROVIDER = (os.getenv("GLM_OCR_PROVIDER") or "local").strip().lower()
GLM_OCR_MODEL = (os.getenv("GLM_OCR_MODEL") or "glm-ocr").strip() or "glm-ocr"
GLM_OCR_LAYOUT_PARSING_URL = (
    (os.getenv("GLM_OCR_LAYOUT_PARSING_URL") or "https://api.z.ai/api/paas/v4/layout_parsing").strip()
    or "https://api.z.ai/api/paas/v4/layout_parsing"
)
GLM_OCR_PROMPT = (
    (
        os.getenv("GLM_OCR_PROMPT")
        or "Extract all readable text from this document and return plain text only."
    ).strip()
    or "Extract all readable text from this document and return plain text only."
)
GLM_OCR_FILE_FIELD = (os.getenv("GLM_OCR_FILE_FIELD") or "file").strip() or "file"
GLM_OCR_RESPONSE_TEXT_KEY = (
    (os.getenv("GLM_OCR_RESPONSE_TEXT_KEY") or "text").strip() or "text"
)
GLM_OCR_TIMEOUT_SECONDS = int(os.getenv("GLM_OCR_TIMEOUT_SECONDS", "90"))
GLM_OCR_MOCK = _is_truthy(os.getenv("GLM_OCR_MOCK"))
GLM_OCR_USE_LOCAL = _is_truthy(os.getenv("GLM_OCR_USE_LOCAL"))
OCR_LANGS = (os.getenv("OCR_LANGS") or "fra+eng").strip() or "fra+eng"
_LOCAL_OCR = RapidOCR() if RapidOCR is not None else None


def _pdf_to_images(file_path: Path) -> List[Image.Image]:
    if fitz is None:
        raise RuntimeError(
            "PyMuPDF is required to process PDFs. Install pymupdf to continue."
        ) from _pymupdf_import_error

    images: List[Image.Image] = []
    doc = fitz.open(file_path)
    try:
        for page in doc:
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            img_bytes = pix.tobytes("png")
            images.append(Image.open(io.BytesIO(img_bytes)))
    finally:
        doc.close()
    return images


def _image_to_png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="PNG")
    return buffer.getvalue()


def _image_to_data_url(image: Image.Image) -> str:
    encoded = base64.b64encode(_image_to_png_bytes(image)).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _preprocess_image_for_ocr(image: Image.Image) -> Image.Image:
    # Stronger preprocessing for phone photos / low-resolution screenshots.
    img = ImageOps.exif_transpose(image).convert("L")
    img = ImageOps.autocontrast(img, cutoff=1)

    width, height = img.size
    long_edge = max(width, height)

    # Upscale aggressively when the source image is small.
    if long_edge < 2200:
        scale = min(12.0, 2200.0 / max(1.0, float(long_edge)))
        new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
        img = img.resize(new_size, Image.LANCZOS)
        width, height = img.size
        long_edge = max(width, height)

    # Keep a bounded size for performance.
    if long_edge > 3200:
        scale = 3200.0 / float(long_edge)
        new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
        img = img.resize(new_size, Image.LANCZOS)

    img = ImageEnhance.Contrast(img).enhance(2.0)
    img = img.filter(ImageFilter.UnsharpMask(radius=2, percent=180, threshold=2))

    return img


def _binarize_image(image: Image.Image) -> Image.Image:
    arr = np.array(image.convert("L"), dtype=np.uint8)
    # Otsu thresholding without external OpenCV dependency.
    hist = np.bincount(arr.ravel(), minlength=256).astype(np.float64)
    total = arr.size
    if total == 0:
        return image.convert("L")
    sum_total = np.dot(np.arange(256, dtype=np.float64), hist)
    sum_b = 0.0
    w_b = 0.0
    max_var = -1.0
    threshold = 127
    for t in range(256):
        w_b += hist[t]
        if w_b == 0:
            continue
        w_f = total - w_b
        if w_f == 0:
            break
        sum_b += t * hist[t]
        m_b = sum_b / w_b
        m_f = (sum_total - sum_b) / w_f
        between = w_b * w_f * ((m_b - m_f) ** 2)
        if between > max_var:
            max_var = between
            threshold = t
    binary = np.where(arr > threshold, 255, 0).astype(np.uint8)
    return Image.fromarray(binary, mode="L")


def _score_ocr_text(text: str) -> float:
    if not text:
        return 0.0
    printable = sum(ch.isprintable() for ch in text)
    alnum = sum(ch.isalnum() for ch in text)
    words = len(re.findall(r"[A-Za-z0-9]{2,}", text))
    junk = sum(ch in "<>[]{}|\\^~`" for ch in text)
    return (printable * 0.2) + (alnum * 0.8) + (words * 4.0) - (junk * 2.0)


def _run_rapidocr(image: Image.Image) -> str:
    if _LOCAL_OCR is None:
        raise RuntimeError("rapidocr engine not available.")

    rgb_array = np.array(image.convert("RGB"))
    bgr_array = rgb_array[:, :, ::-1]
    ocr_result, _ = _LOCAL_OCR(bgr_array)
    if not ocr_result:
        return ""

    lines: List[str] = []
    for item in ocr_result:
        if not item:
            continue
        if isinstance(item, (list, tuple)):
            if len(item) >= 2 and isinstance(item[1], str):
                lines.append(item[1])
                continue
            if len(item) >= 1 and isinstance(item[0], str):
                lines.append(item[0])
                continue
        if isinstance(item, str):
            lines.append(item)
    return "\n".join(lines).strip()


def _run_tesseract(image: Image.Image) -> str:
    if pytesseract is None:
        raise RuntimeError("pytesseract Python package is not available.")
    best_text = ""
    best_score = -1.0
    for config in ("--oem 3 --psm 6", "--oem 3 --psm 4", "--oem 3 --psm 11"):
        try:
            text = pytesseract.image_to_string(
                image,
                lang=OCR_LANGS,
                config=config,
            ).strip()
        except Exception as exc:  # pragma: no cover - runtime dependency/host issue
            raise RuntimeError(f"tesseract engine failed: {exc}") from exc
        score = _score_ocr_text(text)
        if score > best_score:
            best_text = text
            best_score = score
    return best_text


def _run_local_ocr_on_image(image: Image.Image) -> str:
    enhanced = _preprocess_image_for_ocr(image)
    binarized = _binarize_image(enhanced)
    variants = [enhanced, binarized]
    engines = [_run_rapidocr, _run_tesseract]

    best_text = ""
    best_score = -1.0
    for candidate in variants:
        try:
            for engine in engines:
                try:
                    text = engine(candidate)
                except Exception:
                    continue
                score = _score_ocr_text(text)
                if score > best_score:
                    best_text = text
                    best_score = score
        finally:
            candidate.close()

    if best_score < 0:
        raise RuntimeError(
            "No local OCR engine is available. Install rapidocr-onnxruntime or "
            "pytesseract+tesseract."
        )

    return best_text


def _extract_text_from_payload(payload: Any) -> str | None:
    keys = [GLM_OCR_RESPONSE_TEXT_KEY, "text", "content", "ocr_text", "result", "output"]

    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        data = payload.get("data")
        if isinstance(data, dict):
            for key in keys:
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()

        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                message = first.get("message")
                if isinstance(message, dict):
                    content = message.get("content")
                    if isinstance(content, str) and content.strip():
                        return content.strip()
                    if isinstance(content, list):
                        parts: List[str] = []
                        for item in content:
                            if isinstance(item, str) and item.strip():
                                parts.append(item.strip())
                            elif isinstance(item, dict):
                                text = item.get("text")
                                if isinstance(text, str) and text.strip():
                                    parts.append(text.strip())
                        if parts:
                            return "\n".join(parts)
    return None


def _post_and_extract_text(
    url: str, headers: Dict[str, str], *, json_payload: Dict[str, Any] | None = None,
    multipart_files: Dict[str, Any] | None = None
) -> str:
    try:
        response = requests.post(
            url,
            headers=headers,
            json=json_payload,
            files=multipart_files,
            timeout=GLM_OCR_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"Unable to reach OCR service: {exc}") from exc

    if response.status_code in {401, 403}:
        raise RuntimeError(
            "Access denied by OCR provider (HTTP 401/403). Verify GLM_OCR_API_KEY "
            "permissions and account access."
        )
    if response.status_code == 429:
        raise RuntimeError("OCR provider rate limit reached (HTTP 429). Retry later.")
    if response.status_code >= 500:
        raise RuntimeError(
            f"OCR provider server error (HTTP {response.status_code}). Retry later."
        )
    response.raise_for_status()

    try:
        payload: Any = response.json()
    except ValueError as exc:
        raise RuntimeError("OCR provider returned a non-JSON response.") from exc

    text_value = _extract_text_from_payload(payload)
    if text_value is None:
        raise RuntimeError(
            "OCR provider response does not contain extracted text. "
            f"Expected keys include '{GLM_OCR_RESPONSE_TEXT_KEY}'."
        )
    return text_value


def _run_glm_official_ocr_on_image(image: Image.Image) -> str:
    if not GLM_OCR_API_KEY:
        raise RuntimeError(
            "GLM_OCR_API_KEY is required for official GLM-OCR (layout_parsing)."
        )

    headers = {
        "Authorization": f"Bearer {GLM_OCR_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": GLM_OCR_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": GLM_OCR_PROMPT},
                    {"type": "file_url", "file_url": {"url": _image_to_data_url(image)}},
                ],
            }
        ],
    }
    return _post_and_extract_text(
        GLM_OCR_LAYOUT_PARSING_URL, headers=headers, json_payload=payload
    )


def _run_glm_multipart_ocr_on_image(image: Image.Image) -> str:
    if not GLM_OCR_API_URL:
        raise RuntimeError("GLM_OCR_API_URL is not configured for multipart OCR mode.")

    image_bytes = _image_to_png_bytes(image)
    headers = {}
    if GLM_OCR_API_KEY:
        headers["Authorization"] = f"Bearer {GLM_OCR_API_KEY}"

    return _post_and_extract_text(
        GLM_OCR_API_URL,
        headers=headers,
        multipart_files={GLM_OCR_FILE_FIELD: ("image.png", image_bytes, "image/png")},
    )


def _run_glm_ocr_on_image(image: Image.Image) -> str:
    if GLM_OCR_USE_LOCAL:
        return _run_local_ocr_on_image(image)

    if GLM_OCR_PROVIDER in {"local", "rapidocr", "offline"}:
        return _run_local_ocr_on_image(image)

    if GLM_OCR_PROVIDER in {"zai", "zhipu", "layout_parsing", "official"}:
        return _run_glm_official_ocr_on_image(image)

    if GLM_OCR_API_URL:
        return _run_glm_multipart_ocr_on_image(image)

    if GLM_OCR_API_KEY:
        return _run_glm_official_ocr_on_image(image)

    if GLM_OCR_MOCK:
        # Mock output for local development when no OCR backend is configured.
        return (
            "Nom: Demo\n"
            "Prenom: OCR\n"
            "Date: 01/01/2026\n"
            "Montant: 123.45\n"
            "Adresse: 1 Example Street\n"
            "Email: demo@example.com"
        )

    raise RuntimeError(
        "No OCR backend configured. Set GLM_OCR_API_KEY for official GLM-OCR, or "
        "set GLM_OCR_API_URL for custom OCR endpoint, or GLM_OCR_USE_LOCAL=1 "
        "for local fallback."
    )


def _extract_text_with_runner(
    path: Path, runner: Callable[[Image.Image], str], preprocess: bool = True
) -> str:
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    if path.suffix.lower() == ".pdf":
        images = _pdf_to_images(path)
    else:
        images = [Image.open(path)]

    texts: List[str] = []
    for image in images:
        processed = _preprocess_image_for_ocr(image) if preprocess else image.copy()
        try:
            texts.append(runner(processed))
        finally:
            processed.close()
            image.close()

    full_text = "\n".join(texts).strip()

    if os.getenv("SAVE_OCR_TEXT", "").strip().lower() in {"1", "true", "yes", "on"}:
        output_dir = Path("results")
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{path.stem}.txt"
        output_path.write_text(full_text, encoding="utf-8")

    return full_text


def extract_text_with_glm_ocr(file_path: str) -> str:
    use_local_pipeline = GLM_OCR_USE_LOCAL or GLM_OCR_PROVIDER in {"local", "rapidocr", "offline"}
    return _extract_text_with_runner(
        Path(file_path),
        _run_glm_ocr_on_image,
        preprocess=not use_local_pipeline,
    )


def extract_text_with_local_ocr(file_path: str) -> str:
    return _extract_text_with_runner(Path(file_path), _run_local_ocr_on_image, preprocess=False)


def format_extracted_text_as_json(text: str) -> Dict[str, str | None]:
    def normalize_text(value: str) -> str:
        value = value.replace("\r\n", "\n").replace("\r", "\n")
        value = re.sub(r"[ \t]+", " ", value)
        return value.strip()

    def find_first(patterns: List[str]) -> str | None:
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
            if match:
                value = match.group(1).strip()
                if value:
                    return value
        return None

    def extract_block_after_label(
        label_patterns: List[str], stop_patterns: List[str], max_lines: int = 5
    ) -> List[str]:
        lines = [line.strip() for line in normalize_text(text).split("\n")]
        for idx, line in enumerate(lines):
            if any(re.search(pat, line, flags=re.IGNORECASE) for pat in label_patterns):
                block: List[str] = []
                for follow in lines[idx + 1 :]:
                    if not follow:
                        break
                    if any(
                        re.search(stop, follow, flags=re.IGNORECASE)
                        for stop in stop_patterns
                    ):
                        break
                    block.append(follow)
                    if len(block) >= max_lines:
                        break
                return block
        return []

    client_block = extract_block_after_label(
        label_patterns=[r"votre client", r"nom du client", r"\bclient\b"],
        stop_patterns=[
            r"facture",
            r"date",
            r"echeance",
            r"description",
            r"quantite",
            r"prix",
            r"montant",
            r"total",
        ],
        max_lines=5,
    )
    client_name = client_block[0] if client_block else None
    address_lines = [line for line in client_block[1:] if "@" not in line]
    client_address = ", ".join(address_lines).strip() if address_lines else None

    extracted = {
        "numero_facture": find_first(
            [
                r"(?:facture|invoice)[^\n\r]{0,40}\b([A-Za-z]{0,6}-?\d[\w-]{2,})\b",
                r"\b([A-Za-z]{1,6}-\d{2,}[A-Za-z0-9-]*)\b",
                r"facture\s*(?:n|no|n°|numero|numéro)\s*[:#]?\s*([A-Za-z0-9-]+)",
                r"facture\s*[:#]?\s*([A-Za-z0-9-]+)",
            ]
        ),
        "nom": client_name
        or find_first([r"nom du client\s*[:\-]?\s*(?:\r?\n)?\s*([^\n\r]+)"]),
        "prenom": find_first(
            [
                r"(?:prenom|first name)\s*[:\-]?\s*(?:\r?\n)?\s*([^\n\r]+)",
            ]
        ),
        "date": find_first(
            [
                r"(?:date)\s*[:\-]?\s*(?:\r?\n)?\s*([^\n\r]+)",
            ]
        ),
        "montant": find_first(
            [
                r"(?:total\s+a\s+payer|total\s+à\s+payer)\s*(?:\(.*?\))?\s*[:\-]?\s*([0-9][0-9\s.,]*)",
                r"(?:montant total|total ttc|total)\s*(?:\(.*?\))?\s*[:\-]?\s*([0-9][0-9\s.,]*)",
                r"(?:montant)\s*[:\-]?\s*([0-9][0-9\s.,]*)",
            ]
        ),
        "adresse": client_address
        or find_first([r"(?:adresse|address)\s*[:\-]?\s*(?:\r?\n)?\s*([^\n\r]+)"]),
        "email": find_first(
            [
                r"([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})",
            ]
        ),
    }

    return extracted
