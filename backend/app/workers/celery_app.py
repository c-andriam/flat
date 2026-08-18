from celery import Celery
from celery.schedules import crontab

from app.config import settings

BROKER_URL = settings.redis_url

app = Celery(
    "dsio",
    broker=BROKER_URL,
    backend=BROKER_URL,
    include=[
        "app.workers.ingestion",
        "app.workers.writeback",
        "app.workers.notifications",
    ],
)

app.conf.task_routes = {
    "app.workers.ingestion.*": {"queue": "ingestion_queue"},
    "app.workers.writeback.*": {"queue": "writeback_queue"},
    # Sans cette route, les tâches de relance partaient dans la file par
    # défaut `celery` — qu'aucun conteneur ne consomme : le beat les publiait
    # chaque jour et personne ne les exécutait jamais.
    "app.workers.notifications.*": {"queue": "notifications_queue"},
}

app.conf.update(
    # Fuseau explicite : sans ça, `crontab(hour=8)` s'entend en UTC, soit 11 h
    # à Antananarivo (UTC+3) — les relances partaient en milieu de matinée.
    timezone="Indian/Antananarivo",
    enable_utc=True,
    # L'accusé de réception après exécution évite de perdre une tâche si le
    # worker est tué en plein import Excel : elle est redistribuée.
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # Un import Excel qui part en boucle ne doit pas bloquer la file
    # indéfiniment.
    task_soft_time_limit=600,
    task_time_limit=900,
    result_expires=86400,
    # Celery 5.3 émet un avertissement de dépréciation sans ce réglage
    # explicite ; il conditionne aussi la reconnexion si Redis démarre après
    # le worker.
    broker_connection_retry_on_startup=True,
)

app.conf.beat_schedule = {
    "check-relances-quotidiennes": {
        "task": "app.workers.notifications.check_and_send",
        # `schedule: 86400.0` déclenchait la tâche 24 h après le démarrage du
        # beat, donc à une heure qui dépendait du dernier redéploiement.
        "schedule": crontab(hour=8, minute=0),
    },
    "marquer-actions-en-retard": {
        "task": "app.workers.notifications.mark_overdue_actions",
        # Juste avant les relances, pour que les statuts soient à jour.
        "schedule": crontab(hour=7, minute=45),
    },
}
