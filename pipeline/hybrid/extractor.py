"""
Hybrid PDF page extractor.

Combines native text extraction with OCR on image regions.
Resolves overlapping blocks by preferring native text.
"""

import fitz  # PyMuPDF

from model.document import Block, BlockType, BBox, Page, PageType
from pipeline.native.extractor import extract_native_page, sort_blocks_reading_order
from pipeline.scanned.extractor import render_page_to_image, render_page_to_bytes
from pipeline.scanned.ocr_engine import run_ocr, estimate_font_size


def extract_hybrid_page(page: fitz.Page, page_number: int) -> Page:
    """
    Extract text from a hybrid PDF page.

    Strategy:
    1. Extract native text blocks (same as native pipeline)
    2. Render page to image and run OCR
    3. Merge results, preferring native text when coordinates overlap
    4. Sort in reading order
    """
    page_rect = page.rect
    result_page = Page(
        page_number=page_number,
        width=page_rect.width,
        height=page_rect.height,
        page_type=PageType.HYBRID,
    )

    native_blocks: list[Block] = []
    ocr_blocks: list[Block] = []

    try:
        # 1. Extract native text blocks
        native_page = extract_native_page(page, page_number)
        native_blocks = native_page.blocks.copy()
        result_page.errors.extend(native_page.errors)

    except Exception as e:
        result_page.errors.append(f"Hybrid native extraction error: {str(e)}")

    try:
        # 2. Run OCR on the full page image
        img = render_page_to_image(page)
        ocr_results = run_ocr(
            image=img,
            page_width=page_rect.width,
            page_height=page_rect.height,
        )

        for item in ocr_results:
            font_size = estimate_font_size(item["bbox"], item["text"])
            ocr_block = Block(
                type=BlockType.TEXT,
                bbox=item["bbox"],
                content=item["text"],
                font_size=font_size,
                confidence=item["confidence"],
            )
            ocr_blocks.append(ocr_block)

    except Exception as e:
        result_page.errors.append(f"Hybrid OCR extraction error: {str(e)}")

    # 3. Merge: keep all native blocks, add OCR blocks that don't overlap
    merged_blocks = list(native_blocks)

    for ocr_block in ocr_blocks:
        is_duplicate = False
        for native_block in native_blocks:
            if ocr_block.bbox.overlaps(native_block.bbox, threshold=0.3):
                is_duplicate = True
                break

        if not is_duplicate:
            merged_blocks.append(ocr_block)

    # 4. Sort in reading order
    result_page.blocks = sort_blocks_reading_order(merged_blocks)

    # 5. Capture background image (useful for layout preservation)
    try:
        result_page.background_image = render_page_to_bytes(page)
    except Exception:
        pass

    return result_page
