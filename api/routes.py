"""
FastAPI API routes.

Endpoints:
1. POST /api/v1/convert     — Upload PDF, create task
2. GET  /api/v1/tasks/{id}   — Query task status
3. GET  /api/v1/tasks/{id}/download — Download result DOCX
"""

import logging
import io
import base64
from pathlib import Path
from typing import List

import fitz  # PyMuPDF
import numpy as np
from PIL import Image
from fastapi import APIRouter, UploadFile, File, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from storage.file_storage import file_storage
from storage.preview_store import preview_store
from storage.task_store import task_store
from workers.tasks import convert_pdf_task
from model.document import Document, Page, PageType, Block, BlockType, BBox
from pipeline.scanned.ocr_engine import run_ocr, estimate_font_size
from pipeline.scanned.extractor import (
    render_page_to_image,
    image_to_bytes,
    remove_text_from_image,
    _sample_text_color,
    _restore_english_spaces,
    _dedupe_ocr_results,
)
from pipeline.native.extractor import sort_blocks_reading_order
from render.docx_renderer import render_document_to_docx


def _load_font(text: str, size_px: int):
    """Best-effort font loader for preview rendering."""
    from PIL import ImageFont
    from pathlib import Path

    cjk = any("\u4e00" <= ch <= "\u9fff" for ch in text)
    if cjk:
        candidates = [
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/Supplemental/Songti.ttc",
            "/System/Library/Fonts/Supplemental/Heiti.ttc",
        ]
    else:
        candidates = [
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/System/Library/Fonts/Supplemental/Helvetica.ttf",
        ]
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size_px)
            except Exception:
                continue
    return ImageFont.load_default()


def _render_preview_image(page: Page, image_np: np.ndarray) -> bytes:
    """Composite background + text blocks into a preview image."""
    from PIL import ImageDraw

    img = Image.fromarray(image_np).convert("RGB")
    draw = ImageDraw.Draw(img)
    img_h, img_w = image_np.shape[:2]
    scale_y = img_h / max(1.0, page.height)
    scale_x = img_w / max(1.0, page.width)
    scale = (scale_x + scale_y) / 2.0

    for block in page.blocks:
        if block.type != BlockType.TEXT:
            continue
        x = block.bbox.x0 * scale_x
        y = block.bbox.y0 * scale_y
        font_size = int(max(8, (block.font_size or 12) * scale))
        font = _load_font(block.content or "", font_size)
        color = block.font_color or (0, 0, 0)
        draw.text((x, y), block.content or "", fill=color, font=font)

    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def _decode_data_url(data_url: str) -> bytes:
    if not data_url:
        return b""
    if "," in data_url:
        _, payload = data_url.split(",", 1)
    else:
        payload = data_url
    try:
        return base64.b64decode(payload)
    except Exception:
        return b""


def _apply_replacements(
    image_np: np.ndarray,
    replacements: list["ImageReplacement"],
    page_width: float,
    page_height: float,
) -> np.ndarray:
    if not replacements:
        return image_np

    base = Image.fromarray(image_np).convert("RGBA")
    img_w, img_h = base.size
    scale_x = img_w / max(1.0, page_width)
    scale_y = img_h / max(1.0, page_height)

    for rep in replacements:
        data = _decode_data_url(rep.image_data)
        if not data:
            continue
        try:
            overlay = Image.open(io.BytesIO(data)).convert("RGBA")
        except Exception:
            continue

        x0 = int(round(rep.x0 * scale_x))
        y0 = int(round(rep.y0 * scale_y))
        x1 = int(round(rep.x1 * scale_x))
        y1 = int(round(rep.y1 * scale_y))

        x0 = max(0, min(x0, img_w - 1))
        y0 = max(0, min(y0, img_h - 1))
        x1 = max(0, min(x1, img_w))
        y1 = max(0, min(y1, img_h))

        if x1 <= x0 + 2 or y1 <= y0 + 2:
            continue

        overlay = overlay.resize((x1 - x0, y1 - y0), Image.LANCZOS)
        base.paste(overlay, (x0, y0), mask=overlay)

    return np.array(base.convert("RGB"))

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1")


class TextOverride(BaseModel):
    page_index: int
    item_id: int
    text: str


class ImageReplacement(BaseModel):
    page_index: int
    x0: float
    y0: float
    x1: float
    y1: float
    image_data: str


class SelectionItem(BaseModel):
    page_index: int
    selected_ids: List[int]


class GenerateRequest(BaseModel):
    session_id: str
    selections: List[SelectionItem] = []
    text_overrides: List[TextOverride] = []
    image_replacements: List[ImageReplacement] = []


@router.post("/convert")
async def create_conversion_task(file: UploadFile = File(...)):
    """
    Upload a PDF file and create a conversion task.

    Returns:
        {"task_id": "...", "status": "queued"}
    """
    # Validate file type
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    # Read and save the upload
    file_bytes = await file.read()
    if len(file_bytes) == 0:
        raise HTTPException(status_code=400, detail="Empty file")

    input_path = file_storage.save_upload(file_bytes, file.filename)
    logger.info(f"Saved upload: {input_path}")

    # Create task record
    task = task_store.create_task(
        input_path=input_path,
        output_path=file_storage.get_result_path("placeholder"),
    )

    # Update output path with actual task_id
    output_path = file_storage.get_result_path(task.task_id)
    task_store.update_status(task.task_id, task.status)

    # Dispatch async task
    convert_pdf_task.delay(task.task_id, input_path, output_path)

    logger.info(f"Dispatched task: {task.task_id}")

    return {
        "task_id": task.task_id,
        "status": "queued",
        "message": "Conversion task created. Poll /api/v1/tasks/{task_id} for status.",
    }


@router.get("/tasks/{task_id}")
async def get_task_status(task_id: str):
    """
    Query task status and progress.

    Returns:
        {"task_id": "...", "status": "...", "progress": {...}, "error": "..."}
    """
    task = task_store.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    response = {
        "task_id": task.task_id,
        "status": task.status.value,
        "progress": {
            "processed_pages": task.processed_pages,
            "total_pages": task.total_pages,
        },
    }

    if task.error_message:
        response["error"] = task.error_message

    return response


@router.get("/tasks/{task_id}/download")
async def download_result(task_id: str):
    """
    Download the converted DOCX file.

    Only available when task status is 'completed'.
    """
    task = task_store.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status.value != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"Task is not completed. Current status: {task.status.value}",
        )

    result_path = file_storage.get_result_path(task_id)
    if not Path(result_path).exists():
        raise HTTPException(status_code=404, detail="Result file not found")

    return FileResponse(
        path=result_path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=f"converted_{task_id}.docx",
    )


@router.post("/preview")
async def preview_pdf(
    file: UploadFile = File(...),
    max_pages: int = Query(5, ge=1, le=50),
):
    """
    Upload a PDF and return preview images + OCR boxes for manual selection.
    """
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    file_bytes = await file.read()
    if len(file_bytes) == 0:
        raise HTTPException(status_code=400, detail="Empty file")

    input_path = file_storage.save_upload(file_bytes, file.filename)
    session_id = preview_store.create_session(input_path)

    doc = fitz.open(input_path)
    total_pages = min(len(doc), max_pages)

    pages_resp = []
    for page_idx in range(total_pages):
        page = doc[page_idx]
        img = render_page_to_image(page)
        ocr_results = run_ocr(
            image=img,
            page_width=page.rect.width,
            page_height=page.rect.height,
        )

        for item in ocr_results:
            item["text"] = _restore_english_spaces(img, item.get("poly"), item.get("text", ""))

        ocr_results = _dedupe_ocr_results(ocr_results)

        serial = []
        for idx, item in enumerate(ocr_results):
            bbox = item["bbox"]
            serial.append(
                {
                    "id": idx,
                    "bbox": {"x0": bbox.x0, "y0": bbox.y0, "x1": bbox.x1, "y1": bbox.y1},
                    "poly": [[float(p[0]), float(p[1])] for p in (item.get("poly") or [])],
                    "text": item.get("text", ""),
                    "confidence": float(item.get("confidence", 0.0)),
                }
            )

        image_bytes = image_to_bytes(img)
        preview_store.save_page(
            session_id=session_id,
            page_index=page_idx,
            page_number=page_idx + 1,
            width=page.rect.width,
            height=page.rect.height,
            image_bytes=image_bytes,
            ocr_results=serial,
        )

        pages_resp.append(
            {
                "page_index": page_idx,
                "page_number": page_idx + 1,
                "width": page.rect.width,
                "height": page.rect.height,
                "image_url": f"/api/v1/preview/{session_id}/pages/{page_idx}",
                "ocr": serial,
            }
        )

    doc.close()

    return {"session_id": session_id, "pages": pages_resp}


@router.get("/preview/{session_id}/pages/{page_index}")
async def get_preview_page(session_id: str, page_index: int):
    image_path = preview_store.get_image_path(session_id, page_index)
    if image_path is None or not image_path.exists():
        raise HTTPException(status_code=404, detail="Preview page not found")
    return FileResponse(path=str(image_path), media_type="image/png")


@router.post("/generate")
async def generate_docx(payload: GenerateRequest):
    session = preview_store.get_session(payload.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Preview session not found")

    selection_map = {s.page_index: set(s.selected_ids) for s in payload.selections}
    override_map = {(o.page_index, o.item_id): o.text for o in payload.text_overrides}
    replacement_map: dict[int, list[ImageReplacement]] = {}
    for rep in payload.image_replacements:
        replacement_map.setdefault(rep.page_index, []).append(rep)

    document = Document(
        source_path=session.get("input_path"),
        total_pages=len(session.get("pages", [])),
    )

    result_pages = []
    for page_meta in session.get("pages", []):
        page_index = page_meta["page_index"]
        page = Page(
            page_number=page_index,
            width=page_meta["width"],
            height=page_meta["height"],
            page_type=PageType.SCANNED,
        )

        image_path = Path(page_meta["image_path"])
        img = Image.open(image_path).convert("RGB")
        img_np = np.array(img)

        ocr_results = page_meta.get("ocr_results", [])
        selected_ids = selection_map.get(page_index)
        if selected_ids is None:
            source_items = ocr_results
        else:
            source_items = [item for item in ocr_results if item.get("id") in selected_ids]

        selected_items = []
        for item in source_items:
            new_item = dict(item)
            override = override_map.get((page_index, item.get("id")))
            if override is not None:
                new_item["text"] = override
            selected_items.append(new_item)

        # Convert to BBox objects and dedupe overlaps
        dedupe_candidates = []
        for item in selected_items:
            bbox_dict = item.get("bbox") or {}
            dedupe_candidates.append(
                {
                    "bbox": BBox(
                        x0=float(bbox_dict.get("x0", 0)),
                        y0=float(bbox_dict.get("y0", 0)),
                        x1=float(bbox_dict.get("x1", 0)),
                        y1=float(bbox_dict.get("y1", 0)),
                    ),
                    "poly": item.get("poly"),
                    "text": item.get("text", ""),
                    "confidence": item.get("confidence", 0.0),
                }
            )
        selected_items = _dedupe_ocr_results(dedupe_candidates)

        # Build blocks from selected items
        for item in selected_items:
            bbox = item.get("bbox")
            text = item.get("text", "")
            font_size = estimate_font_size(bbox, text)
            font_color = _sample_text_color(img_np, item.get("poly"))
            page.blocks.append(
                Block(
                    type=BlockType.TEXT,
                    bbox=bbox,
                    content=text,
                    font_size=font_size,
                    font_color=font_color,
                    confidence=item.get("confidence"),
                )
            )

        page.blocks = sort_blocks_reading_order(page.blocks)

        # Background image: only remove selected text
        if selected_items:
            bg_img = remove_text_from_image(img_np, selected_items)
        else:
            bg_img = img_np

        replacements = replacement_map.get(page_index, [])
        if replacements:
            bg_img = _apply_replacements(bg_img, replacements, page.width, page.height)

        page.background_image = image_to_bytes(bg_img)

        document.pages.append(page)

        # Save result preview image (background + text overlay)
        preview_bytes = _render_preview_image(page, np.array(Image.open(io.BytesIO(page.background_image))))
        preview_store.save_result_page(payload.session_id, page_index, preview_bytes)
        result_pages.append(
            {
                "page_index": page_index,
                "page_number": page_meta.get("page_number"),
                "image_url": f"/api/v1/preview/{payload.session_id}/results/{page_index}",
            }
        )

    output_path = file_storage.get_result_path(payload.session_id)
    render_document_to_docx(document, output_path)

    return {
        "download_url": f"/api/v1/preview/{payload.session_id}/download",
        "pages": document.total_pages,
        "result_pages": result_pages,
    }


@router.get("/preview/{session_id}/download")
async def download_preview_result(session_id: str):
    result_path = file_storage.get_result_path(session_id)
    if not Path(result_path).exists():
        raise HTTPException(status_code=404, detail="Result file not found")
    return FileResponse(
        path=result_path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=f"preview_{session_id}.docx",
    )


@router.get("/preview/{session_id}/results/{page_index}")
async def download_preview_result_image(session_id: str, page_index: int):
    image_path = preview_store.get_result_image_path(session_id, page_index)
    if image_path is None or not image_path.exists():
        raise HTTPException(status_code=404, detail="Result preview not found")
    return FileResponse(path=str(image_path), media_type="image/png")
