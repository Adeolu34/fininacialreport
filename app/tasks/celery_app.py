from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "financial_reports",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "app.tasks.report_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_routes={
        "app.tasks.report_tasks.generate_report_task": {"queue": "reports"},
        "app.tasks.report_tasks.download_portal_reports_task": {"queue": "downloads"},
        "app.tasks.report_tasks.send_report_email_task": {"queue": "emails"},
    },
)

# ---------------------------------------------------------------------------
# Beat schedule
# ---------------------------------------------------------------------------
celery_app.conf.beat_schedule = {
    # Daily report at the configurable hour/minute (default 08:00 UTC)
    "daily-report": {
        "task": "app.tasks.report_tasks.generate_report_task",
        "schedule": crontab(
            hour=str(settings.report_schedule_hour),
            minute=str(settings.report_schedule_minute),
        ),
        "kwargs": {"report_type": "daily", "date_range": None, "source_files": []},
    },
    # Weekly report — Monday at 08:00 UTC
    "weekly-report": {
        "task": "app.tasks.report_tasks.generate_report_task",
        "schedule": crontab(hour="8", minute="0", day_of_week="1"),
        "kwargs": {"report_type": "weekly", "date_range": None, "source_files": []},
    },
    # Monthly report — 1st of every month at 08:00 UTC
    "monthly-report": {
        "task": "app.tasks.report_tasks.generate_report_task",
        "schedule": crontab(hour="8", minute="0", day_of_month="1"),
        "kwargs": {"report_type": "monthly", "date_range": None, "source_files": []},
    },
}
