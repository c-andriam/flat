import os

from celery import Celery

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = os.getenv("REDIS_PORT", "6379")
BROKER_URL = f"redis://{REDIS_HOST}:{REDIS_PORT}/0"

app = Celery(
    "dsio",
    broker=BROKER_URL,
    backend=BROKER_URL,
    include=["app.workers.ingestion", "app.workers.writeback", "app.workers.notifications"],
)

app.conf.task_routes = {
    "app.workers.ingestion.*": {"queue": "ingestion_queue"},
    "app.workers.writeback.*": {"queue": "writeback_queue"},
}

app.conf.beat_schedule = {
    # Exécution quotidienne à 8h du matin pour les relances
    "check-relances-quotidiennes": {
        "task": "app.workers.notifications.check_and_send",
        "schedule": 86400.0,  # TODO: utiliser crontab(hour=8, minute=0) plus tard
    },
}
