"""
Task state store backed by Redis.

Tracks conversion task status, progress, and metadata.
"""

import json
import time
import logging
from typing import Optional

import redis

from config import settings
from model.document import TaskRecord, TaskStatus

logger = logging.getLogger(__name__)


class TaskStore:
    """Redis-backed task state management."""

    KEY_PREFIX = "docai:task:"
    TTL_SECONDS = 86400  # 24 hours

    def __init__(self):
        self._redis = None

    @property
    def redis_client(self) -> redis.Redis:
        """Lazy Redis connection."""
        if self._redis is None:
            self._redis = redis.Redis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
            )
        return self._redis

    def _key(self, task_id: str) -> str:
        return f"{self.KEY_PREFIX}{task_id}"

    def create_task(self, input_path: str, output_path: str) -> TaskRecord:
        """Create a new task record."""
        task = TaskRecord(
            input_path=input_path,
            output_path=output_path,
        )
        self.redis_client.setex(
            self._key(task.task_id),
            self.TTL_SECONDS,
            json.dumps(task.to_dict()),
        )
        logger.info(f"Created task: {task.task_id}")
        return task

    def update_status(
        self,
        task_id: str,
        status: TaskStatus,
        processed_pages: int = 0,
        total_pages: int = 0,
        error_message: Optional[str] = None,
    ):
        """Update task status and progress."""
        task = self.get_task(task_id)
        if task is None:
            logger.warning(f"Task not found for update: {task_id}")
            return

        task.status = status
        task.processed_pages = processed_pages
        task.total_pages = total_pages
        task.updated_at = time.time()

        if error_message:
            task.error_message = error_message

        self.redis_client.setex(
            self._key(task_id),
            self.TTL_SECONDS,
            json.dumps(task.to_dict()),
        )

    def get_task(self, task_id: str) -> Optional[TaskRecord]:
        """Retrieve a task record."""
        data = self.redis_client.get(self._key(task_id))
        if data is None:
            return None
        return TaskRecord.from_dict(json.loads(data))

    def delete_task(self, task_id: str):
        """Delete a task record."""
        self.redis_client.delete(self._key(task_id))


# Singleton
task_store = TaskStore()
