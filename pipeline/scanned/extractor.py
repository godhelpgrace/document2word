"""
Scanned PDF page extractor.

Renders the page as an image, runs preprocessing + OCR,
and produces text blocks with page coordinates.
"""

import io
import re
from typing import Optional, Tuple

import fitz  # PyMuPDF
import numpy as np
import cv2
from PIL import Image

from config import settings
from model.document import Block, BlockType, BBox, Page, PageType
from pipeline.native.extractor import sort_blocks_reading_order
from pipeline.scanned.ocr_engine import run_ocr, estimate_font_size


def render_page_to_image(page: fitz.Page, dpi: int = None) -> np.ndarray:
    """Render a PDF page to a numpy array image at the given DPI."""
    if dpi is None:
        dpi = settings.RENDER_DPI

    zoom = dpi / 72.0  # 72 DPI is the base
    matrix = fitz.Matrix(zoom, zoom)
    pixmap = page.get_pixmap(matrix=matrix, alpha=False)

    # Convert to numpy array
    img = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
        pixmap.height, pixmap.width, pixmap.n
    )

    return img


def render_page_to_bytes(page: fitz.Page, dpi: int = None, fmt: str = "png") -> bytes:
    """Render a PDF page to image bytes."""
    if dpi is None:
        dpi = settings.RENDER_DPI

    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    pixmap = page.get_pixmap(matrix=matrix, alpha=False)

    return pixmap.tobytes(output=fmt)


def image_to_bytes(image: np.ndarray, fmt: str = "png") -> bytes:
    """Encode a numpy image to bytes."""
    if image.ndim == 2:
        pil_img = Image.fromarray(image, mode="L")
    else:
        pil_img = Image.fromarray(image, mode="RGB")
    out = io.BytesIO()
    pil_img.save(out, format=fmt.upper())
    return out.getvalue()


def remove_text_from_image(image: np.ndarray, ocr_results: list[dict]) -> np.ndarray:
    """
    Inpaint OCR-detected text regions to create a clean background image.
    """
    if not ocr_results:
        return image

    scale = settings.INPAINT_DOWNSCALE
    if scale <= 0:
        scale = 1.0

    h, w = image.shape[:2]
    # Convert to BGR for OpenCV operations, keep RGB for output
    img_bgr = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)

    if scale < 1.0:
        new_w = max(1, int(w * scale))
        new_h = max(1, int(h * scale))
        img_work = cv2.resize(img_bgr, (new_w, new_h), interpolation=cv2.INTER_AREA)
    else:
        img_work = img_bgr

    mask = np.zeros(img_work.shape[:2], dtype=np.uint8)

    for item in ocr_results:
        poly = item.get("poly")
        if not poly:
            continue
        pts = np.array(poly, dtype=np.float32)
        if pts.ndim != 2 or pts.shape[1] != 2:
            continue
        if scale < 1.0:
            pts[:, 0] *= scale
            pts[:, 1] *= scale
        pts = pts.astype(np.int32)
        cv2.fillPoly(mask, [pts], 255)

    if mask.sum() == 0:
        return image

    # Expand mask to fully cover text edges (helps remove residuals)
    k = max(1, int(settings.INPAINT_KERNEL))
    if k % 2 == 0:
        k += 1
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (k, k))
    dilate_iters = max(0, int(settings.INPAINT_DILATE))
    if dilate_iters > 0:
        mask = cv2.dilate(mask, kernel, iterations=dilate_iters)

    # Protect strong edges to avoid bleeding into shapes/gradients
    if settings.INPAINT_EDGE_PROTECT:
        gray = cv2.cvtColor(img_work, cv2.COLOR_BGR2GRAY)
        med = float(np.median(gray))
        lower = int(max(0, 0.66 * med))
        upper = int(min(255, 1.33 * med))
        edges = cv2.Canny(gray, lower, upper)
        edge_thick = max(0, int(settings.INPAINT_EDGE_THICKNESS))
        if edge_thick > 0:
            edge_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
            edges = cv2.dilate(edges, edge_kernel, iterations=edge_thick)
        if edges is not None:
            # Only protect edges outside the text mask to avoid leaving text residues
            inner_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
            mask_inner = cv2.erode(mask, inner_kernel, iterations=1)
            protect = (edges > 0) & (mask_inner == 0)
            if protect.any():
                mask[protect] = 0

    if mask.sum() == 0:
        return image

    radius = max(1, int(settings.INPAINT_RADIUS))
    inpainted = cv2.inpaint(img_work, mask, radius, cv2.INPAINT_TELEA)
    if scale < 1.0:
        inpainted = cv2.resize(inpainted, (w, h), interpolation=cv2.INTER_LINEAR)
        mask_full = cv2.resize(mask, (w, h), interpolation=cv2.INTER_NEAREST)
    else:
        mask_full = mask

    # Composite only inpainted regions to preserve original colors elsewhere
    out = img_bgr.copy()
    out[mask_full > 0] = inpainted[mask_full > 0]

    return cv2.cvtColor(out, cv2.COLOR_BGR2RGB)


def _sample_text_color(image: np.ndarray, poly) -> Optional[Tuple[int, int, int]]:
    """Sample a likely text color from the polygon region in the RGB image."""
    if poly is None:
        return None
    pts = np.array(poly, dtype=np.float32)
    if pts.ndim != 2 or pts.shape[1] != 2:
        return None

    h, w = image.shape[:2]
    mask = np.zeros((h, w), dtype=np.uint8)
    cv2.fillPoly(mask, [pts.astype(np.int32)], 255)

    if mask.sum() == 0:
        return None

    # Prefer inner pixels to reduce background bleed
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    inner = cv2.erode(mask, kernel, iterations=1)
    if inner.sum() < 10:
        inner = mask

    pixels = image[inner > 0]
    if pixels.size == 0:
        return None

    # Estimate local background color from a thin ring around the text
    dilated = cv2.dilate(mask, kernel, iterations=2)
    ring = cv2.subtract(dilated, mask)
    bg_pixels = image[ring > 0]
    if bg_pixels.size == 0:
        bg_pixels = image[mask == 0]
    bg_color = np.median(bg_pixels, axis=0) if bg_pixels.size else np.median(pixels, axis=0)

    # Pick pixels most different from background
    diff = pixels.astype(np.float32) - bg_color.astype(np.float32)
    dist = np.sqrt((diff * diff).sum(axis=1))
    if dist.size == 0:
        return None
    thresh = np.percentile(dist, 70)
    sel = dist >= thresh

    if sel.sum() < 10:
        # Fallback using luminance contrast
        bg_luma = float(0.299 * bg_color[0] + 0.587 * bg_color[1] + 0.114 * bg_color[2])
        gray = 0.299 * pixels[:, 0] + 0.587 * pixels[:, 1] + 0.114 * pixels[:, 2]
        if bg_luma >= 128:
            t = np.percentile(gray, 30)
            sel = gray <= t
        else:
            t = np.percentile(gray, 70)
            sel = gray >= t

    chosen = pixels[sel] if sel.sum() else pixels
    if chosen.size == 0:
        return None

    median = np.median(chosen, axis=0)
    # Ensure contrast from background
    bg_luma = float(0.299 * bg_color[0] + 0.587 * bg_color[1] + 0.114 * bg_color[2])
    dist_final = float(np.linalg.norm(median - bg_color))
    if dist_final < 25:
        if bg_luma >= 128:
            median = np.clip(bg_color - 80, 0, 255)
        else:
            median = np.clip(bg_color + 80, 0, 255)
    return (int(median[0]), int(median[1]), int(median[2]))


_ENGLISH_NO_SPACE_RE = re.compile(r"^[A-Za-z0-9,.'\"/:\\-]+$")
_DUP_TEXT_RE = re.compile(r"[^0-9A-Za-z\u4e00-\u9fff]+")


def _normalize_text(text: str) -> str:
    return _DUP_TEXT_RE.sub("", (text or "").lower())


def _dedupe_ocr_results(items: list[dict]) -> list[dict]:
    """Remove near-duplicate OCR boxes (high overlap + similar text)."""
    if not items:
        return items

    def _score(it: dict) -> float:
        return float(it.get("confidence") or 0.0)

    sorted_items = sorted(items, key=_score, reverse=True)
    kept: list[dict] = []
    kept_norms: list[str] = []
    for item in sorted_items:
        bbox = item.get("bbox")
        if bbox is None:
            continue
        norm = _normalize_text(item.get("text", ""))
        is_dup = False
        for k, k_norm in zip(kept, kept_norms):
            if not k_norm or not norm:
                continue
            try:
                if bbox.overlaps(k["bbox"], threshold=0.85) and (
                    norm == k_norm or norm in k_norm or k_norm in norm
                ):
                    is_dup = True
                    break
            except Exception:
                continue
        if not is_dup:
            kept.append(item)
            kept_norms.append(norm)

    return kept


def _restore_english_spaces(image: np.ndarray, poly, text: str) -> str:
    """
    Heuristically restore spaces in English text by analyzing column gaps.
    Only runs when text has no spaces and is mostly ASCII.
    """
    if not text or " " in text:
        return text
    if len(text) < 6:
        return text
    if not _ENGLISH_NO_SPACE_RE.match(text):
        return text
    if poly is None:
        return text

    h, w = image.shape[:2]
    pts = np.array(poly, dtype=np.float32)
    if pts.ndim != 2 or pts.shape[1] != 2:
        return text
    x0 = max(0, int(np.floor(pts[:, 0].min())))
    x1 = min(w, int(np.ceil(pts[:, 0].max())))
    y0 = max(0, int(np.floor(pts[:, 1].min())))
    y1 = min(h, int(np.ceil(pts[:, 1].max())))
    if x1 <= x0 + 2 or y1 <= y0 + 2:
        return text

    crop = image[y0:y1, x0:x1]
    if crop.size == 0:
        return text

    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    # Otsu threshold for text/background separation
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # Decide polarity: text should be white in mask
    if bw.mean() > 127:
        text_mask = bw == 0
    else:
        text_mask = bw == 255

    proj = text_mask.sum(axis=0)
    max_proj = int(proj.max()) if proj.size else 0
    if max_proj == 0:
        return text

    gap_ratio = float(settings.SPACE_GAP_RATIO)
    gap_thresh = max(1, int(max_proj * gap_ratio))
    is_gap = proj <= gap_thresh
    # Find gap segments
    gaps = []
    start = None
    for i, g in enumerate(is_gap):
        if g and start is None:
            start = i
        elif not g and start is not None:
            gaps.append((start, i - 1))
            start = None
    if start is not None:
        gaps.append((start, len(is_gap) - 1))

    if not gaps:
        return text

    # Estimate minimum gap width based on average char width
    crop_w = max(1, x1 - x0)
    char_w = crop_w / max(1, len(text))
    min_gap_ratio = float(settings.SPACE_MIN_GAP_RATIO)
    min_gap = max(2, int(char_w * min_gap_ratio))

    insert_positions = []
    for s, e in gaps:
        if e - s + 1 < min_gap:
            continue
        center = (s + e) / 2.0
        idx = int(round(center / crop_w * len(text)))
        if 0 < idx < len(text):
            insert_positions.append(idx)

    if not insert_positions:
        return text

    insert_positions = sorted(set(insert_positions))
    if len(insert_positions) > int(len(text) * 0.5):
        return text
    out = []
    last_idx = 0
    offset = 0
    for idx in insert_positions:
        idx_adj = idx + offset
        if idx_adj <= last_idx:
            continue
        out.append(text[last_idx:idx_adj])
        out.append(" ")
        last_idx = idx_adj
        offset += 1
    out.append(text[last_idx:])
    return "".join(out)


def extract_scanned_page(page: fitz.Page, page_number: int) -> Page:
    """
    Extract text from a scanned PDF page using OCR.

    Steps:
    1. Render page to high-DPI image
    2. Preprocess image (denoise, deskew, binarize)
    3. Run OCR to get text + coordinates
    4. Build TextBlock list
    5. Capture full-page background image
    """
    page_rect = page.rect
    result_page = Page(
        page_number=page_number,
        width=page_rect.width,
        height=page_rect.height,
        page_type=PageType.SCANNED,
    )

    try:
        # 1. Render page to image
        img = render_page_to_image(page)

        # 2. Run OCR (use original image for better color recognition)
        ocr_results = run_ocr(
            image=img,
            page_width=page_rect.width,
            page_height=page_rect.height,
        )

        # 4. Build text blocks
        for item in ocr_results:
            item_text = _restore_english_spaces(img, item.get("poly"), item.get("text", ""))
            item["text"] = item_text

        ocr_results = _dedupe_ocr_results(ocr_results)

        for item in ocr_results:
            item_text = item.get("text", "")
            font_size = estimate_font_size(item["bbox"], item_text)
            font_color = _sample_text_color(img, item.get("poly"))
            text_block = Block(
                type=BlockType.TEXT,
                bbox=item["bbox"],
                content=item_text,
                font_size=font_size,
                font_color=font_color,
                confidence=item["confidence"],
            )
            result_page.blocks.append(text_block)

        # Sort blocks in reading order
        result_page.blocks = sort_blocks_reading_order(result_page.blocks)

        # 5. Capture background image with text removed
        try:
            bg_img = remove_text_from_image(img, ocr_results)
            result_page.background_image = image_to_bytes(bg_img)
        except Exception:
            result_page.background_image = render_page_to_bytes(page)

    except Exception as e:
        result_page.errors.append(f"Scanned extraction error: {str(e)}")
        # Still try to capture background even on OCR failure
        try:
            result_page.background_image = render_page_to_bytes(page)
        except Exception:
            pass

    return result_page
