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
    # Même réglage que `settings.relance_timezone`, dont dépendent les heures
    # d'envoi choisies par les utilisateurs : les désaligner décalerait chaque
    # récapitulatif du delta entre les deux fuseaux.
    timezone=settings.relance_timezone,
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

# Trois rappels distincts partaient auparavant à heure fixe — retard à 8 h 00,
# jour J à 8 h 10, échéances proches le lundi à 8 h 20 — pour tout le monde à
# la même cadence. Un responsable concerné par les trois recevait donc trois
# messages, ou plutôt un seul : la période de silence éliminait les deux
# suivants, sans qu'il sache lequel avait été retenu.
#
# Ils sont remplacés par un récapitulatif unique dont la cadence appartient à
# chaque destinataire (`relance_preferences`). Le planificateur ne sait plus à
# quelle heure envoyer : il déclenche la tâche à chaque heure ronde, et
# celle-ci ne retient que les personnes dont c'est le créneau. Coût d'un
# passage à vide : une requête indexée.
app.conf.beat_schedule = {
    "marquer-actions-en-retard": {
        "task": "app.workers.notifications.mark_overdue_actions",
        # En premier, pour que les statuts soient à jour avant les relances —
        # d'où 7 h 45, avant le premier créneau d'envoi possible.
        "schedule": crontab(hour=7, minute=45),
    },
    "recapitulatifs-planifies": {
        "task": "app.workers.notifications.send_scheduled_digests",
        # `minute=0` et non `minute="*/15"` : `Reglage.doit_envoyer` compare
        # l'heure, pas la minute, et quatre passages par heure enverraient
        # quatre fois le même message si le garde-fou d'idempotence venait à
        # céder.
        "schedule": crontab(minute=0),
    },
}
