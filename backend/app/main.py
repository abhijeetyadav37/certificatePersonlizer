import io
import json
import importlib.util
from pathlib import Path
from typing import Any

import pymupdf
import pytesseract
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError

try:
    import cv2
    import numpy as np
except ImportError:  # Optional: install opencv-python-headless for better background cleanup.
    cv2 = None
    np = None

_TESSERACT_WINDOWS = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
if Path(_TESSERACT_WINDOWS).exists():
    pytesseract.pytesseract.tesseract_cmd = _TESSERACT_WINDOWS

# Optional local AI OCR. Install requirements-ai.txt to enable EasyOCR.
_EASYOCR_READER = None
_EASYOCR_CHECKED = False
DPI = 200
SCALE = DPI / 72
MAX_FILE_SIZE = 10 * 1024 * 1024
MAX_PIXELS = 25_000_000
WATERMARK = "PERSONALIZED PREVIEW - NOT AN OFFICIAL CREDENTIAL"

app = FastAPI(
    title="Smart Certificate Personalizer",
    version="0.4.0",
    description="Edit OCR text by its detected coordinates on authorized documents.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


def _clean_text(value: str) -> str:
    return " ".join((value or "").split()).strip()


def _get_easyocr_reader():
    global _EASYOCR_READER, _EASYOCR_CHECKED
    if _EASYOCR_CHECKED:
        return _EASYOCR_READER
    _EASYOCR_CHECKED = True
    try:
        import easyocr
        _EASYOCR_READER = easyocr.Reader(["en"], gpu=False, verbose=False)
    except Exception:
        _EASYOCR_READER = None
    return _EASYOCR_READER


def _ocr_image(image: Image.Image) -> dict[str, Any]:
    image = ImageOps.exif_transpose(image).convert("RGB")
    lines: list[dict[str, Any]] = []
    method = "tesseract_ocr"

    reader = _get_easyocr_reader()
    if reader is not None and np is not None:
        try:
            results = reader.readtext(np.array(image), detail=1, paragraph=False)
            for index, result in enumerate(results):
                polygon, text, confidence = result
                points = [(int(point[0]), int(point[1])) for point in polygon]
                x1 = max(0, min(point[0] for point in points))
                y1 = max(0, min(point[1] for point in points))
                x2 = min(image.width, max(point[0] for point in points))
                y2 = min(image.height, max(point[1] for point in points))
                text = _clean_text(text)
                if text and x2 > x1 and y2 > y1:
                    lines.append({
                        "id": f"line_{index}", "text": text,
                        "bbox": {"x": x1, "y": y1, "width": x2 - x1, "height": y2 - y1},
                        "confidence": round(float(confidence) * 100, 1),
                    })
            method = "easyocr_ai" if lines else "tesseract_ocr"
        except Exception:
            lines = []

    if not lines:
        try:
            data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
        except pytesseract.pytesseract.TesseractNotFoundError as exc:
            raise HTTPException(status_code=503, detail="Tesseract OCR was not found. Install it or configure its executable path.") from exc
        except pytesseract.TesseractError as exc:
            raise HTTPException(status_code=422, detail="OCR could not process this image.") from exc

        grouped: dict[tuple[int, int, int], list[dict[str, Any]]] = {}
        for i, raw in enumerate(data["text"]):
            word = raw.strip()
            if not word:
                continue
            key = (int(data["block_num"][i]), int(data["par_num"][i]), int(data["line_num"][i]))
            grouped.setdefault(key, []).append({
                "text": word, "x": int(data["left"][i]), "y": int(data["top"][i]),
                "width": int(data["width"][i]), "height": int(data["height"][i]),
                "confidence": max(0.0, float(data["conf"][i])) if str(data["conf"][i]).replace(".", "", 1).lstrip("-").isdigit() else 0.0,
            })
        for index, words in enumerate(grouped.values()):
            words.sort(key=lambda word: word["x"])
            x1 = min(word["x"] for word in words)
            y1 = min(word["y"] for word in words)
            x2 = max(word["x"] + word["width"] for word in words)
            y2 = max(word["y"] + word["height"] for word in words)
            if x2 > x1 and y2 > y1:
                lines.append({
                    "id": f"line_{index}", "text": " ".join(word["text"] for word in words),
                    "bbox": {"x": x1, "y": y1, "width": x2 - x1, "height": y2 - y1},
                    "confidence": round(sum(word["confidence"] for word in words) / len(words), 1),
                })
        method = "tesseract_ocr"

    lines.sort(key=lambda line: (line["bbox"]["y"], line["bbox"]["x"]))
    for index, line in enumerate(lines):
        line["id"] = f"line_{index}"
    confidence_values = [line["confidence"] for line in lines if line.get("confidence") is not None]
    return {
        "text": "\n".join(line["text"] for line in lines),
        "lines": lines,
        "confidence": round(sum(confidence_values) / len(confidence_values), 1) if confidence_values else None,
        "image_size": {"width": image.width, "height": image.height},
        "method": method,
    }


def _pdf_to_image(data: bytes) -> tuple[Image.Image, tuple[float, float]]:
    try:
        with pymupdf.open(stream=data, filetype="pdf") as document:
            if document.is_encrypted:
                raise HTTPException(status_code=422, detail="Password-protected PDFs are not supported.")
            if document.page_count != 1:
                raise HTTPException(status_code=422, detail="Please upload a single-page PDF.")
            page = document[0]
            pixmap = page.get_pixmap(dpi=DPI, alpha=False)
            image = Image.open(io.BytesIO(pixmap.tobytes("png"))).convert("RGB")
            return image, (float(page.rect.width), float(page.rect.height))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=422, detail="This PDF is invalid or could not be read.") from exc


def _extract_pdf_text_layer(data: bytes) -> dict[str, Any] | None:
    try:
        with pymupdf.open(stream=data, filetype="pdf") as document:
            if document.page_count != 1 or document.is_encrypted:
                return None
            page = document[0]
            raw = page.get_text("dict")
            lines: list[dict[str, Any]] = []
            for block in raw.get("blocks", []):
                for line in block.get("lines", []):
                    spans = line.get("spans", [])
                    text = _clean_text(" ".join(span.get("text", "") for span in spans))
                    if not text:
                        continue
                    x1 = min(span["bbox"][0] for span in spans)
                    y1 = min(span["bbox"][1] for span in spans)
                    x2 = max(span["bbox"][2] for span in spans)
                    y2 = max(span["bbox"][3] for span in spans)
                    lines.append({
                        "text": text,
                        "bbox": {"x": round(x1 * SCALE), "y": round(y1 * SCALE),
                                 "width": max(1, round((x2 - x1) * SCALE)), "height": max(1, round((y2 - y1) * SCALE))},
                        "confidence": None,
                    })
            if not lines:
                return None
            lines.sort(key=lambda item: (item["bbox"]["y"], item["bbox"]["x"]))
            for index, line in enumerate(lines):
                line["id"] = f"line_{index}"
            return {"text": "\n".join(line["text"] for line in lines), "lines": lines,
                    "confidence": None, "method": "pdf_text_layer"}
    except Exception:
        return None


async def _read_upload(file: UploadFile) -> tuple[str, str, bytes]:
    filename = Path(file.filename or "document").name
    extension = Path(filename).suffix.lower()
    if extension not in {".pdf", ".png", ".jpg", ".jpeg"}:
        raise HTTPException(status_code=415, detail="Upload a single-page PDF, PNG, JPG, or JPEG file.")
    data = await file.read(MAX_FILE_SIZE + 1)
    await file.close()
    if not data:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    if len(data) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File size exceeds the 10 MB limit.")
    if extension == ".pdf" and not data.startswith(b"%PDF-"):
        raise HTTPException(status_code=415, detail="The uploaded file is not a valid PDF.")
    if extension in {".png", ".jpg", ".jpeg"}:
        try:
            with Image.open(io.BytesIO(data)) as image:
                if image.format not in {"PNG", "JPEG"}:
                    raise HTTPException(status_code=415, detail="Only PNG and JPEG images are supported.")
                if image.width * image.height > MAX_PIXELS:
                    raise HTTPException(status_code=413, detail="The image dimensions are too large.")
        except HTTPException:
            raise
        except (UnidentifiedImageError, OSError) as exc:
            raise HTTPException(status_code=422, detail="The uploaded image is damaged or invalid.") from exc
    return filename, extension, data


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "smart-certificate-personalizer", "version": "0.4.0"}


@app.get("/api/engine")
def engine_status() -> dict[str, Any]:
    ai_available = importlib.util.find_spec("easyocr") is not None and cv2 is not None and np is not None
    return {"ocr_engine": "EasyOCR local AI (loads on first extraction)" if ai_available else "Tesseract OCR fallback",
            "ai_available": ai_available, "background_cleanup": "OpenCV inpainting" if cv2 is not None else "basic fill fallback"}


@app.post("/api/extract")
async def extract_document(file: UploadFile = File(...)) -> dict[str, Any]:
    filename, extension, data = await _read_upload(file)
    if extension == ".pdf":
        image, page_size = _pdf_to_image(data)
        result = _extract_pdf_text_layer(data)
        if result is None:
            result = _ocr_image(image)
        result["image_size"] = {"width": image.width, "height": image.height}
        result["page_size"] = {"width": page_size[0], "height": page_size[1]}
        result["page_number"] = 1
    else:
        with Image.open(io.BytesIO(data)) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
        if image.width * image.height > MAX_PIXELS:
            raise HTTPException(status_code=413, detail="The image dimensions are too large.")
        result = _ocr_image(image)
        result["page_number"] = 1
    result["message"] = "Text extraction completed." if result["lines"] else "No text was detected."
    return {"filename": filename, "size_bytes": len(data), **result}


def _inpaint(image: Image.Image, boxes: list[tuple[int, int, int, int]]) -> Image.Image:
    if not boxes:
        return image.copy()
    if cv2 is not None and np is not None:
        rgb = np.array(image.convert("RGB"))
        mask = np.zeros((rgb.shape[0], rgb.shape[1]), dtype=np.uint8)
        for x1, y1, x2, y2 in boxes:
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(rgb.shape[1], x2), min(rgb.shape[0], y2)
            if x2 > x1 and y2 > y1:
                mask[y1:y2, x1:x2] = 255
        # Navier-Stokes inpainting reconstructs small regions from surrounding pixels.
        restored = cv2.inpaint(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), mask, 4, cv2.INPAINT_NS)
        return Image.fromarray(cv2.cvtColor(restored, cv2.COLOR_BGR2RGB))

    # Dependency-free fallback: fill each region with the average of its border pixels.
    output = image.convert("RGB").copy()
    pixels = output.load()
    for x1, y1, x2, y2 in boxes:
        samples = []
        for x in range(max(0, x1 - 2), min(output.width, x2 + 2)):
            for y in (max(0, y1 - 2), min(output.height - 1, y2 + 1)):
                samples.append(pixels[x, y])
        for y in range(max(0, y1 - 2), min(output.height, y2 + 2)):
            for x in (max(0, x1 - 2), min(output.width - 1, x2 + 1)):
                samples.append(pixels[x, y])
        color = tuple(round(sum(sample[channel] for sample in samples) / max(1, len(samples))) for channel in range(3))
        ImageDraw.Draw(output).rectangle((x1, y1, x2, y2), fill=color)
    return output


def _font(size: int) -> ImageFont.ImageFont:
    size = max(9, min(120, size))
    for candidate in [r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\calibri.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _draw_fitted_text(draw: ImageDraw.ImageDraw, text: str, bbox: tuple[int, int, int, int]) -> None:
    x1, y1, x2, y2 = bbox
    box_width = max(8, x2 - x1)
    box_height = max(10, y2 - y1)
    size = max(9, int(box_height * 0.88))
    font = _font(size)
    while size > 8 and draw.textbbox((0, 0), text, font=font)[2] > box_width * 1.35:
        size -= 1
        font = _font(size)
    # Keep the replacement aligned to the detected line's top-left anchor.
    draw.text((x1, max(0, y1 - max(0, int(box_height * 0.05)))), text, fill=(20, 20, 20), font=font)


def _add_watermark(image: Image.Image) -> Image.Image:
    image = image.convert("RGB")
    overlay = Image.new("RGBA", image.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)
    font = _font(max(10, image.width // 65))
    label = WATERMARK
    bounds = draw.textbbox((0, 0), label, font=font)
    pad = max(8, image.width // 120)
    x = max(4, (image.width - (bounds[2] - bounds[0])) // 2)
    y = max(4, image.height - (bounds[3] - bounds[1]) - pad * 2)
    draw.rounded_rectangle((x - pad, y - pad, x + bounds[2] + pad, y + bounds[3] + pad), radius=5, fill=(255, 255, 255, 210), outline=(120, 35, 35, 230), width=2)
    draw.text((x, y), label, font=font, fill=(150, 20, 20, 255))
    return Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")


def _generate_image(image: Image.Image, edits: list[dict[str, Any]]) -> Image.Image:
    changed = []
    boxes = []
    for item in edits:
        old_text = _clean_text(str(item.get("original_text", "")))
        new_text = str(item.get("text", ""))
        bbox = item.get("bbox") or {}
        if not old_text or new_text == old_text:
            continue
        try:
            x = int(bbox["x"]); y = int(bbox["y"])
            width = int(bbox["width"]); height = int(bbox["height"])
        except (KeyError, TypeError, ValueError):
            continue
        if width < 1 or height < 1:
            continue
        pad_x = max(2, int(height * 0.18))
        pad_y = max(2, int(height * 0.16))
        rect = (max(0, x - pad_x), max(0, y - pad_y), min(image.width, x + width + pad_x), min(image.height, y + height + pad_y))
        boxes.append(rect)
        changed.append((new_text, (x, y, min(image.width, x + width), min(image.height, y + height))))
    if changed:
        image = _inpaint(image.convert("RGB"), boxes)
        draw = ImageDraw.Draw(image)
        for text, bbox in changed:
            if text.strip():
                _draw_fitted_text(draw, text.strip(), bbox)
    return _add_watermark(image)


@app.post("/api/generate")
async def generate_document(
    file: UploadFile = File(...),
    edits_json: str = Form(...),
    output_format: str = Form("png"),
) -> Response:
    filename, extension, data = await _read_upload(file)
    if output_format not in {"png", "pdf"}:
        raise HTTPException(status_code=400, detail="Output format must be PNG or PDF.")
    try:
        edits = json.loads(edits_json)
        if not isinstance(edits, list):
            raise ValueError
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(status_code=400, detail="The edited text payload is invalid.")

    if extension == ".pdf":
        image, page_size = _pdf_to_image(data)
    else:
        with Image.open(io.BytesIO(data)) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
        page_size = (image.width / SCALE, image.height / SCALE)
    if image.width * image.height > MAX_PIXELS:
        raise HTTPException(status_code=413, detail="The image dimensions are too large.")

    generated = _generate_image(image, edits)
    buffer = io.BytesIO()
    if output_format == "png":
        generated.save(buffer, format="PNG")
        return Response(buffer.getvalue(), media_type="image/png", headers={"Content-Disposition": 'inline; filename="personalized-preview.png"'})

    pdf = pymupdf.open()
    with pdf:
        page = pdf.new_page(width=page_size[0], height=page_size[1])
        png = io.BytesIO()
        generated.save(png, format="PNG")
        page.insert_image(page.rect, stream=png.getvalue())
        pdf_bytes = pdf.tobytes()
    return Response(pdf_bytes, media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="personalized-preview.pdf"'})
