"""
PaddleOCR engine wrapper.

Provides a singleton OCR engine and coordinate conversion utilities.
Compatible with PaddleOCR v3+ (paddlex-based API).
"""

import os
import logging
import numpy as np
from typing import Optional

from config import settings
from model.document import BBox

logger = logging.getLogger(__name__)

# Lazy import to avoid loading PaddleOCR at module level
_ocr_instance = None

# Suppress verbose PaddleOCR output / connectivity checks
os.environ.setdefault("DISABLE_MODEL_SOURCE_CHECK", "True")
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")


def _get_ocr_engine():
    """Get or create the PaddleOCR singleton."""
    global _ocr_instance
    if _ocr_instance is None:
        from paddleocr import PaddleOCR
        from config import settings

        # Use lightweight mobile models to avoid OOM
        # Disable heavy doc orientation/unwarping models
        _ocr_instance = PaddleOCR(
            lang=settings.OCR_LANG,
            ocr_version="PP-OCRv4",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )
        logger.info("PaddleOCR engine initialized (PP-OCRv4 mobile)")
    return _ocr_instance


def run_ocr(
    image: np.ndarray,
    page_width: float,
    page_height: float,
) -> list[dict]:
    """
    Run OCR on an image and return detected text blocks.

    Args:
        image: Input image (preprocessed or raw)
        page_width: Original PDF page width in points
        page_height: Original PDF page height in points

    Returns:
        List of dicts with keys: bbox, text, confidence
    """
    ocr = _get_ocr_engine()
    results = ocr.ocr(image)

    if not results:
        return []

    img_h, img_w = image.shape[:2]
    scale_x = page_width / img_w
    scale_y = page_height / img_h

    blocks = []

    def _poly_to_xy(poly) -> Optional[tuple[list[float], list[float]]]:
        """Normalize polygon/box into xs, ys lists."""
        try:
            if hasattr(poly, "tolist"):
                poly = poly.tolist()
            if isinstance(poly, (list, tuple)) and poly:
                # List of points [[x, y], ...]
                if isinstance(poly[0], (list, tuple)) and len(poly[0]) >= 2:
                    xs = [float(p[0]) for p in poly]
                    ys = [float(p[1]) for p in poly]
                    return xs, ys
                # Flat box [x0, y0, x1, y1]
                if len(poly) == 4 and all(isinstance(v, (int, float)) for v in poly):
                    x0, y0, x1, y1 = [float(v) for v in poly]
                    xs = [x0, x1, x1, x0]
                    ys = [y0, y0, y1, y1]
                    return xs, ys
        except Exception:
            return None
        return None

    # Handle PaddleOCR v3+ OCRResult (paddlex)
    if isinstance(results, list) and results and hasattr(results[0], "get"):
        try:
            obj = results[0]
            texts = obj.get("rec_texts") or []
            scores = obj.get("rec_scores") or []
            polys = obj.get("dt_polys") or obj.get("rec_polys") or obj.get("rec_boxes") or []

            n = min(len(texts), len(polys)) if polys else len(texts)
            if scores:
                n = min(n, len(scores))

            for i in range(n):
                text = str(texts[i]) if texts[i] is not None else ""
                # Preserve internal spaces; only trim newlines/tabs
                cleaned = text.strip("\n\r\t")
                if not cleaned.strip():
                    continue
                confidence = float(scores[i]) if i < len(scores) else 0.0
                poly = polys[i] if i < len(polys) else None
                xy = _poly_to_xy(poly) if poly is not None else None
                if not xy:
                    continue
                xs, ys = xy

                bbox = BBox(
                    x0=min(xs) * scale_x,
                    y0=min(ys) * scale_y,
                    x1=max(xs) * scale_x,
                    y1=max(ys) * scale_y,
                )

                blocks.append({
                    "bbox": bbox,
                    "poly": list(zip(xs, ys)),
                    "text": cleaned,
                    "confidence": confidence,
                })

            return blocks
        except Exception as e:
            logger.debug(f"Failed to parse OCRResult format: {e}")
            # Fall through to legacy parsing

    # Handle different legacy PaddleOCR result formats
    ocr_lines = results
    # Some versions wrap results in an extra list
    if ocr_lines and isinstance(ocr_lines[0], list) and len(ocr_lines[0]) > 0:
        if isinstance(ocr_lines[0][0], list):
            ocr_lines = ocr_lines[0]

    for line in ocr_lines:
        try:
            if isinstance(line, dict):
                # Newer dict format
                text = line.get("rec_text", "") or line.get("text", "")
                confidence = line.get("rec_score", 0.0) or line.get("score", 0.0)
                points = line.get("dt_polys", []) or line.get("points", [])

                if not str(text).strip():
                    continue

                if points and len(points) >= 4:
                    xs = [float(p[0]) for p in points]
                    ys = [float(p[1]) for p in points]
                else:
                    continue

            elif isinstance(line, (list, tuple)) and len(line) >= 2:
                # Classic PaddleOCR format: [[points], (text, confidence)]
                points = line[0]
                text_info = line[1]

                if isinstance(text_info, (list, tuple)):
                    text, confidence = text_info[0], text_info[1]
                elif isinstance(text_info, dict):
                    text = text_info.get("text", "")
                    confidence = text_info.get("score", 0.0)
                else:
                    continue

                if not str(text).strip():
                    continue

                xs = [float(p[0]) for p in points]
                ys = [float(p[1]) for p in points]
            else:
                continue

            bbox = BBox(
                x0=min(xs) * scale_x,
                y0=min(ys) * scale_y,
                x1=max(xs) * scale_x,
                y1=max(ys) * scale_y,
            )

            cleaned = str(text).strip("\n\r\t")
            blocks.append({
                "bbox": bbox,
                "poly": list(zip(xs, ys)),
                "text": cleaned,
                "confidence": float(confidence),
            })

        except Exception as e:
            logger.debug(f"Skipping OCR line due to parsing error: {e}")
            continue

    return blocks


def estimate_font_size(bbox: BBox, text: str) -> Optional[float]:
    """
    Estimate font size from bounding box height.

    Rough heuristic: font size ≈ bbox height * 0.75
    (accounting for line spacing and descenders)
    """
    if not text:
        return None
    height = bbox.height
    estimated = height * settings.FONT_SIZE_SCALE
    # Clamp to reasonable range
    return max(6.0, min(estimated, 72.0))
