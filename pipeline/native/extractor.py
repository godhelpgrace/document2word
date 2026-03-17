"""
Native PDF text extractor.

Extracts text with coordinates, font info, and reading order
directly from the PDF's text objects — no OCR needed.
"""

import fitz  # PyMuPDF

from model.document import Block, BlockType, BBox, Page, PageType


def sort_blocks_reading_order(blocks: list[Block], line_tolerance: float = 5.0) -> list[Block]:
    """
    Sort blocks in reading order: top-to-bottom, left-to-right.

    Groups blocks into lines (by y-coordinate within tolerance),
    then sorts within each line by x-coordinate.
    """
    if not blocks:
        return blocks

    # Sort primarily by y0, then by x0
    sorted_blocks = sorted(blocks, key=lambda b: (b.bbox.y0, b.bbox.x0))

    # Group into lines
    lines: list[list[Block]] = []
    current_line: list[Block] = [sorted_blocks[0]]
    current_y = sorted_blocks[0].bbox.y0

    for block in sorted_blocks[1:]:
        if abs(block.bbox.y0 - current_y) <= line_tolerance:
            current_line.append(block)
        else:
            lines.append(current_line)
            current_line = [block]
            current_y = block.bbox.y0

    lines.append(current_line)

    # Sort each line by x0 and flatten
    result = []
    for line in lines:
        line.sort(key=lambda b: b.bbox.x0)
        result.extend(line)

    return result


def extract_native_page(page: fitz.Page, page_number: int) -> Page:
    """
    Extract all text blocks from a native PDF page.

    Uses PyMuPDF's dict output to get text spans with:
    - Precise bounding boxes
    - Font name and size
    - Text content
    """
    page_rect = page.rect
    result_page = Page(
        page_number=page_number,
        width=page_rect.width,
        height=page_rect.height,
        page_type=PageType.NATIVE,
    )

    try:
        # Extract detailed text structure
        text_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)

        for block in text_dict.get("blocks", []):
            if block["type"] != 0:  # Skip image blocks
                continue

            block_bbox = block["bbox"]

            # Collect all text and styles from spans within this block
            block_text_parts = []
            block_font_sizes = []
            block_font_names = []

            for line in block.get("lines", []):
                line_text_parts = []
                for span in line.get("spans", []):
                    text = span.get("text", "")
                    if text.strip():
                        line_text_parts.append(text)
                        block_font_sizes.append(span.get("size", 12.0))
                        block_font_names.append(span.get("font", ""))

                if line_text_parts:
                    block_text_parts.append("".join(line_text_parts))

            if not block_text_parts:
                continue

            # Use the most common font size in the block
            avg_font_size = sum(block_font_sizes) / len(block_font_sizes) if block_font_sizes else 12.0
            primary_font = block_font_names[0] if block_font_names else None

            text_block = Block(
                type=BlockType.TEXT,
                bbox=BBox(
                    x0=block_bbox[0],
                    y0=block_bbox[1],
                    x1=block_bbox[2],
                    y1=block_bbox[3],
                ),
                content="\n".join(block_text_parts),
                font_size=round(avg_font_size, 1),
                font_name=primary_font,
            )
            result_page.blocks.append(text_block)

        # Sort blocks in reading order
        result_page.blocks = sort_blocks_reading_order(result_page.blocks)

    except Exception as e:
        result_page.errors.append(f"Native extraction error: {str(e)}")

    return result_page
