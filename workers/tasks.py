"""
Celery tasks for PDF conversion.
"""

import logging

from workers.celery_app import celery_app
from storage.task_store import task_store
from model.document import TaskStatus

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="convert_pdf")
def convert_pdf_task(self, task_id: str, input_path: str, output_path: str):
    """
    Async task: Convert a PDF to DOCX.

    Steps:
    1. Update status to PROCESSING
    2. Run the pipeline coordinator
    3. Update status to COMPLETED or FAILED
    """
    logger.info(f"Starting conversion task: {task_id}")

    try:
        # Update status
        task_store.update_status(task_id, TaskStatus.PROCESSING)

        # Progress callback to update task store
        def on_progress(current_page, total_pages):
            task_store.update_status(
                task_id,
                TaskStatus.PROCESSING,
                processed_pages=current_page,
                total_pages=total_pages,
            )

        # Run pipeline
        from pipeline.coordinator import process_pdf
        document = process_pdf(input_path, output_path, progress_callback=on_progress)

        # Mark complete
        task_store.update_status(
            task_id,
            TaskStatus.COMPLETED,
            processed_pages=document.total_pages,
            total_pages=document.total_pages,
        )

        logger.info(f"Task {task_id} completed successfully: {document.total_pages} pages")

    except Exception as e:
        logger.error(f"Task {task_id} failed: {str(e)}", exc_info=True)
        task_store.update_status(
            task_id,
            TaskStatus.FAILED,
            error_message=str(e),
        )
        raise
