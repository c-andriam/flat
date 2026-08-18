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

# Les trois rappels sont espacés pour ne pas empiler trois messages dans la
# même minute chez un responsable concerné par plusieurs natures — et parce
# que la période de silence les rendrait de toute façon mutuellement
# exclusifs s'ils partaient ensemble.
app.conf.beat_schedule = {
    "marquer-actions-en-retard": {
        "task": "app.workers.notifications.mark_overdue_actions",
        # En premier, pour que les statuts soient à jour avant les relances.
        "schedule": crontab(hour=7, minute=45),
    },
    "relance-actions-en-retard": {
        "task": "app.workers.notifications.check_and_send",
        # `schedule: 86400.0` déclenchait la tâche 24 h après le démarrage du
        # beat, donc à une heure qui dépendait du dernier redéploiement.
        "schedule": crontab(hour=8, minute=0),
        "kwargs": {"kind": "overdue"},
    },
    "rappel-jour-j": {
        "task": "app.workers.notifications.check_and_send",
        "schedule": crontab(hour=8, minute=10),
        "kwargs": {"kind": "today"},
    },
    "rappel-echeances-proches": {
        "task": "app.workers.notifications.check_and_send",
        # Une fois par semaine seulement : ce rappel est de l'anticipation,
        # pas une alerte. Le lundi matin, avant la réunion de suivi.
        "schedule": crontab(hour=8, minute=20, day_of_week="mon"),
        "kwargs": {"kind": "due_soon"},
    },
}
