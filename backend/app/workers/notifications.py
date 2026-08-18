"""
Worker Celery pour les notifications et relances.

Prépare des emails consolidés (via Outlook/Graph API) pour les actions en
retard ou proches de l'échéance.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import SessionLocal
from app.models.project import Action, ActionStatus, Project, RelanceLog
from app.workers.celery_app import app

logger = logging.getLogger("worker-notifications")


@app.task(name="app.workers.notifications.check_and_send")
def check_and_send():
    """
    Tâche périodique (Celery Beat).
    Vérifie les actions en retard ou proches de l'échéance (J-3 par défaut).
    Génère un email consolidé pour chaque responsable concerné.
    """
    db = SessionLocal()
    try:
        today = datetime.now(timezone.utc).date()
        horizon = today + timedelta(days=settings.relance_horizon_days)

        # Filtrage en SQL. L'implémentation précédente chargeait *toutes* les
        # actions non terminées de toute la base, puis écartait en Python
        # celles sans échéance ou hors fenêtre : le coût grandissait avec
        # l'historique, pas avec le nombre d'actions réellement à relancer.
        actions = (
            db.query(Action)
            .join(Project, Action.project_id == Project.id)
            .options(selectinload(Action.responsables))
            .filter(
                Action.status != ActionStatus.TERMINE,
                Action.progress < 100.0,
                Action.deadline.isnot(None),
                Action.deadline <= horizon,
                # Un projet archivé ne doit plus générer de relance.
                Project.is_active.is_(True),
            )
            .all()
        )

        if not actions:
            logger.info("Aucune action à relancer aujourd'hui.")
            return {"status": "success", "sent": 0, "skipped_cooldown": 0}

        # Date de dernière relance par responsable, pour ne pas réexpédier le
        # même rappel tous les jours : le beat tourne quotidiennement, sans
        # ce garde-fou chaque responsable recevait un mail par jour tant que
        # l'action restait ouverte.
        cooldown_start = datetime.now(timezone.utc) - timedelta(
            days=settings.relance_cooldown_days
        )
        recently_notified = {
            resp_id
            for (resp_id,) in db.query(RelanceLog.responsable_id)
            .filter(RelanceLog.sent_at >= cooldown_start)
            .distinct()
            .all()
        }

        to_notify: dict = {}
        for action in actions:
            days_left = (action.deadline - today).days
            for resp in action.responsables:
                # On ne notifie que si on a un email mappé.
                if not (resp.is_mapped and resp.email):
                    continue
                if resp.id in recently_notified:
                    continue
                entry = to_notify.setdefault(
                    resp.id, {"responsable": resp, "actions": []}
                )
                entry["actions"].append((action, days_left))

        sent_count = 0
        for data in to_notify.values():
            resp = data["responsable"]
            action_items = sorted(data["actions"], key=lambda item: item[1])

            # TODO: Intégration Microsoft Graph API pour envoyer le mail
            # _send_outlook_email(resp.email, action_items)

            logger.info(
                "Notification générée pour %s (%s) : %d actions (la plus urgente à J%+d)",
                resp.display_name, resp.email, len(action_items), action_items[0][1],
            )

            db.add(
                RelanceLog(
                    responsable_id=resp.id,
                    action_ids=",".join(str(item[0].id) for item in action_items),
                    email_status="sent_simulated",  # Stub avant implé API Graph
                )
            )
            sent_count += 1

        db.commit()
        skipped = len(recently_notified)
        logger.info(
            "Relances terminées : %d notifications, %d responsables en période de "
            "silence (%d jours).",
            sent_count, skipped, settings.relance_cooldown_days,
        )
        return {"status": "success", "sent": sent_count, "skipped_cooldown": skipped}

    except Exception:
        db.rollback()
        logger.exception("Erreur lors de l'envoi des notifications")
        raise
    finally:
        db.close()


@app.task(name="app.workers.notifications.mark_overdue_actions")
def mark_overdue_actions():
    """Bascule en `EN_RETARD` les actions dont l'échéance est atteinte.

    Le statut n'était recalculé qu'à l'écriture (API ou import Excel) : une
    action créée en avance et jamais retouchée restait « à faire » des mois
    après son échéance, et n'apparaissait donc dans aucun tableau de bord de
    retard basé sur le statut.
    """
    db = SessionLocal()
    try:
        today = datetime.now(timezone.utc).date()
        updated = (
            db.query(Action)
            .filter(
                Action.deadline.isnot(None),
                Action.deadline <= today,
                Action.progress < 100.0,
                Action.status.notin_([ActionStatus.EN_RETARD, ActionStatus.TERMINE]),
            )
            .update(
                {
                    Action.status: ActionStatus.EN_RETARD,
                    Action.updated_at: func.now(),
                },
                synchronize_session=False,
            )
        )
        db.commit()
        logger.info("Actions basculées en retard : %d", updated)
        return {"status": "success", "updated": updated}
    except Exception:
        db.rollback()
        logger.exception("Erreur lors du marquage des actions en retard")
        raise
    finally:
        db.close()
