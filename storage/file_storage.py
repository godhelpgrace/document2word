"""
Local file storage manager.

Handles upload storage and result file management.
"""

import shutil
import uuid
from pathlib import Path

from config import settings


class FileStorage:
    """Manages file storage for uploads and results."""

    def __init__(self):
        self.upload_dir = settings.UPLOAD_DIR
        self.result_dir = settings.RESULT_DIR

    def save_upload(self, file_bytes: bytes, original_filename: str) -> str:
        """
        Save an uploaded file and return its storage path.

        Args:
            file_bytes: Raw file content
            original_filename: Original filename for extension detection

        Returns:
            Absolute path to the saved file
        """
        ext = Path(original_filename).suffix or ".pdf"
        file_id = str(uuid.uuid4())
        filename = f"{file_id}{ext}"
        file_path = self.upload_dir / filename
        file_path.write_bytes(file_bytes)
        return str(file_path)

    def get_result_path(self, task_id: str) -> str:
        """Get the expected result file path for a task."""
        return str(self.result_dir / f"{task_id}.docx")

    def result_exists(self, task_id: str) -> bool:
        """Check if a result file exists."""
        return Path(self.get_result_path(task_id)).exists()

    def get_result_file(self, task_id: str) -> Path:
        """Get the result file path if it exists."""
        path = Path(self.get_result_path(task_id))
        if path.exists():
            return path
        return None

    def cleanup_upload(self, file_path: str):
        """Remove an uploaded file."""
        path = Path(file_path)
        if path.exists():
            path.unlink()

    def cleanup_result(self, task_id: str):
        """Remove a result file."""
        path = Path(self.get_result_path(task_id))
        if path.exists():
            path.unlink()


# Singleton
file_storage = FileStorage()
