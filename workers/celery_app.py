"""
Celery application configuration.
"""

from celery import Celery
from config import settings

celery_app = Celery(
    "document_ai",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # Long timeout for PDF processing
    task_soft_time_limit=600,  # 10 minutes
    task_time_limit=900,  # 15 minutes
)
