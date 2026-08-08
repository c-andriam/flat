"""
Worker Celery pour les notifications et relances.
Envoie des emails (via Outlook/Graph API) pour les actions en retard ou proches de l'échéance.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import joinedload

from app.database import SessionLocal
from app.models.project import Action, ActionStatus, RelanceLog, Responsable
from app.workers.celery_app import app

logger = logging.getLogger("worker-notifications")


@app.task(name="app.workers.notifications.check_and_send")
def check_and_send():
    """
    Tâche périodique (Celery Beat).
    Vérifie les actions en retard ou proches de l'échéance (ex: J-3).
    Génère un email consolidé pour chaque responsable concerné.
    """
    db = SessionLocal()
    try:
        # Trouver toutes les actions non terminées
        actions = (
            db.query(Action)
            .options(joinedload(Action.responsables))
            .filter(Action.status != ActionStatus.TERMINE)
            .all()
        )

        today = datetime.now(timezone.utc).date()
        to_notify = {}

        for action in actions:
            if not action.deadline:
                continue

            days_left = (action.deadline - today).days

            # Règle d'alerte : En retard (< 0) ou proche de l'échéance (<= 3 jours)
            if days_left <= 3:
                for resp in action.responsables:
                    # On ne notifie que si on a un email mappé
                    if resp.is_mapped and resp.email:
                        if resp.id not in to_notify:
                            to_notify[resp.id] = {"responsable": resp, "actions": []}
                        to_notify[resp.id]["actions"].append((action, days_left))

        sent_count = 0
        for resp_id, data in to_notify.items():
            resp = data["responsable"]
            action_items = data["actions"]
            
            # TODO: Intégration Microsoft Graph API pour envoyer le mail
            # _send_outlook_email(resp.email, action_items)
            
            logger.info("Notification générée pour %s (%s) : %d actions", resp.display_name, resp.email, len(action_items))

            # Historisation
            action_ids = ",".join([str(a[0].id) for a in action_items])
            log = RelanceLog(
                responsable_id=resp.id,
                action_ids=action_ids,
                email_status="sent_simulated",  # Stub avant implé API Graph
            )
            db.add(log)
            sent_count += 1

        db.commit()
        logger.info("Relances terminées : %d emails envoyés.", sent_count)
        return {"status": "success", "sent": sent_count}

    except Exception as e:
        db.rollback()
        logger.exception("Erreur lors de l'envoi des notifications")
        raise
    finally:
        db.close()
