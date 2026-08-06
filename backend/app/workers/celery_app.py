import os

from celery import Celery

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = os.getenv("REDIS_PORT", "6379")
BROKER_URL = f"redis://{REDIS_HOST}:{REDIS_PORT}/0"

app = Celery(
    "dsio",
    broker=BROKER_URL,
    backend=BROKER_URL,
    include=["app.workers.ingestion", "app.workers.writeback"],
)

app.conf.task_routes = {
    "app.workers.ingestion.*": {"queue": "ingestion_queue"},
    "app.workers.writeback.*": {"queue": "writeback_queue"},
}

app.conf.beat_schedule = {
    # TODO: définir les tâches de relance Outlook (notifications) planifiées.
    # "check-relances-outlook": {
    #     "task": "app.workers.notifications.check_and_send",
    #     "schedule": 3600.0,
    # },
}
