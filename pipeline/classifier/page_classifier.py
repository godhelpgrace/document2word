"""
Page-level PDF classifier.

Determines whether each page is NATIVE, SCANNED, or HYBRID
based on text object count and image coverage ratio.
"""

import fitz  # PyMuPDF

from model.document import PageType
from config import settings


def classify_page(page: fitz.Page) -> PageType:
    """
    Classify a single PDF page.

    Decision logic:
    - Count extractable text characters
    - Calculate image coverage ratio (total image area / page area)
    - Route based on thresholds:
        - text_chars > threshold AND image_coverage < 0.5 → NATIVE
        - text_chars < threshold AND image_coverage > 0.5 → SCANNED
        - otherwise → HYBRID
    """
    text_char_threshold = settings.TEXT_CHAR_THRESHOLD
    image_coverage_threshold = settings.IMAGE_COVERAGE_THRESHOLD

    # 1. Count text characters
    text = page.get_text("text")
    text_chars = len(text.strip())

    # 2. Calculate image coverage
    page_rect = page.rect
    page_area = page_rect.width * page_rect.height

    image_area = 0.0
    image_list = page.get_images(full=True)

    if image_list:
        # Get image bounding boxes from the page's display list
        blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_IMAGES)["blocks"]
        for block in blocks:
            if block["type"] == 1:  # Image block
                bbox = block["bbox"]
                w = bbox[2] - bbox[0]
                h = bbox[3] - bbox[1]
                image_area += w * h

    image_coverage = image_area / page_area if page_area > 0 else 0.0

    # 3. Classification decision
    has_text = text_chars > text_char_threshold
    has_images = image_coverage > image_coverage_threshold

    if has_text and not has_images:
        return PageType.NATIVE
    elif not has_text and has_images:
        return PageType.SCANNED
    else:
        # Mixed content or edge cases → HYBRID handles both
        if has_text and has_images:
            return PageType.HYBRID
        # Very little text and very little image → treat as native if any text
        if text_chars > 0:
            return PageType.NATIVE
        return PageType.SCANNED


def classify_document(doc: fitz.Document) -> list[PageType]:
    """Classify all pages in a PDF document."""
    return [classify_page(doc[i]) for i in range(len(doc))]
