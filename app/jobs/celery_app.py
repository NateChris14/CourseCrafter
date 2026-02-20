## Celery Configuration
from celery import Celery
from app.settings import settings

celery_app = Celery(
    "course_crafter",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    task_track_started=True,
    task_serializer='json',
    result_serializer='json',
    accept_content=['json'],
)

