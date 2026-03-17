"""
Pipeline coordinator.

Orchestrates the full PDF → Document conversion:
1. Opens PDF
2. Classifies each page
3. Routes to the appropriate extractor
4. Collects all pages into a Document
5. Renders to DOCX
"""

import logging
from pathlib import Path

import fitz  # PyMuPDF

from model.document import Document, PageType
from pipeline.classifier.page_classifier import classify_page
from pipeline.native.extractor import extract_native_page
from pipeline.scanned.extractor import extract_scanned_page
from pipeline.hybrid.extractor import extract_hybrid_page
from render.docx_renderer import render_document_to_docx

logger = logging.getLogger(__name__)


def process_pdf(input_path: str, output_path: str, progress_callback=None, max_pages=None) -> Document:
    """
    Process a PDF file end-to-end.

    Args:
        input_path: Path to the input PDF file
        output_path: Path for the output DOCX file
        progress_callback: Optional callback(page_number, total_pages)
        max_pages: Optional max number of pages to process (from start)

    Returns:
        The constructed Document model

    Raises:
        FileNotFoundError: If input PDF doesn't exist
        Exception: On critical processing errors
    """
    input_path = str(input_path)
    output_path = str(output_path)

    if not Path(input_path).exists():
        raise FileNotFoundError(f"PDF file not found: {input_path}")

    logger.info(f"Opening PDF: {input_path}")
    doc = fitz.open(input_path)
    total_pages = len(doc)
    if max_pages is not None and max_pages > 0:
        total_pages = min(total_pages, max_pages)

    document = Document(
        source_path=input_path,
        total_pages=total_pages,
    )

    logger.info(f"Processing {total_pages} pages...")

    for page_idx in range(total_pages):
        page = doc[page_idx]
        logger.info(f"Processing page {page_idx + 1}/{total_pages}")

        try:
            # 1. Classify the page
            page_type = classify_page(page)
            logger.info(f"  Page {page_idx + 1} classified as: {page_type.value}")

            # 2. Route to appropriate extractor
            if page_type == PageType.NATIVE:
                result_page = extract_native_page(page, page_idx)
            elif page_type == PageType.SCANNED:
                result_page = extract_scanned_page(page, page_idx)
            else:  # HYBRID
                result_page = extract_hybrid_page(page, page_idx)

            # Log any per-page errors
            if result_page.errors:
                for err in result_page.errors:
                    logger.warning(f"  Page {page_idx + 1}: {err}")

            document.pages.append(result_page)

        except Exception as e:
            logger.error(f"  Failed to process page {page_idx + 1}: {str(e)}")
            # Create an empty page placeholder to maintain page count
            from model.document import Page
            error_page = Page(
                page_number=page_idx,
                width=page.rect.width,
                height=page.rect.height,
                page_type=PageType.SCANNED,
                errors=[f"Processing failed: {str(e)}"],
            )
            # Try to at least capture the background
            try:
                from pipeline.scanned.extractor import render_page_to_bytes
                error_page.background_image = render_page_to_bytes(page)
            except Exception:
                pass
            document.pages.append(error_page)

        # Progress callback
        if progress_callback:
            progress_callback(page_idx + 1, total_pages)

    doc.close()

    # 3. Render to DOCX
    logger.info(f"Rendering DOCX to: {output_path}")
    render_document_to_docx(document, output_path)

    logger.info("Processing complete!")
    return document
