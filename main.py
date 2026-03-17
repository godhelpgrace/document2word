"""
CLI entry point for local testing.

Usage:
    python main.py input.pdf output.docx

Runs the pipeline coordinator synchronously (no Celery/Redis needed).
"""

import sys
import os
import logging
import time
from pathlib import Path


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger = logging.getLogger("main")

    if len(sys.argv) < 2:
        print("Usage: python main.py <input.pdf> [output.docx]")
        print("\nExamples:")
        print('  python main.py "Catalogue from Guangxinxing(DHD) 2025.12.pdf"')
        print('  python main.py input.pdf output.docx')
        sys.exit(1)

    input_path = sys.argv[1]
    if not Path(input_path).exists():
        logger.error(f"File not found: {input_path}")
        sys.exit(1)

    # Default output path
    if len(sys.argv) >= 3:
        output_path = sys.argv[2]
    else:
        stem = Path(input_path).stem
        output_path = f"{stem}_converted.docx"

    logger.info(f"Input:  {input_path}")
    logger.info(f"Output: {output_path}")

    start_time = time.time()

    # Run the pipeline
    from pipeline.coordinator import process_pdf

    def on_progress(current, total):
        logger.info(f"Progress: {current}/{total} pages")

    try:
        max_pages_env = os.getenv("MAX_PAGES")
        max_pages = int(max_pages_env) if max_pages_env else None
        document = process_pdf(
            input_path,
            output_path,
            progress_callback=on_progress,
            max_pages=max_pages,
        )

        elapsed = time.time() - start_time
        logger.info(f"✅ Done! {document.total_pages} pages processed in {elapsed:.1f}s")
        logger.info(f"Output saved to: {output_path}")

        # Print page type summary
        from collections import Counter
        type_counts = Counter(p.page_type.value for p in document.pages)
        logger.info(f"Page types: {dict(type_counts)}")

        # Report any errors
        error_pages = [p for p in document.pages if p.errors]
        if error_pages:
            logger.warning(f"Pages with errors: {len(error_pages)}")
            for p in error_pages:
                for err in p.errors:
                    logger.warning(f"  Page {p.page_number + 1}: {err}")

    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"❌ Failed after {elapsed:.1f}s: {str(e)}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
