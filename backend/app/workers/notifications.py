"""
Worker Celery des relances par email.

Le worker construisait sa propre sélection d'actions et se contentait de
journaliser « Notification générée » — rien ne partait, et sa définition du
retard pouvait diverger de celle de l'API. Il s'appuie désormais sur les mêmes
vues métier (`services/action_queries`), les mêmes gabarits
(`services/email_templates`) et le même émetteur (`services/outlook`) que les
routes `/relances` : un rappel quotidien et un aperçu déclenché à la main
produisent exactement le même message.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import SessionLocal
from app.models.project import Action, ActionStatus, RelanceLog, Responsable
from app.services import outlook
from app.services.action_queries import ActionView, build_actions_query, default_order
from app.services.digests import to_digest
from app.services.email_templates import RelanceKind, build_email
from app.workers.celery_app import app

logger = logging.getLogger("worker-notifications")

_VUE_PAR_NATURE = {
    RelanceKind.OVERDUE: ActionView.OVERDUE,
    RelanceKind.TODAY: ActionView.TODAY,
    RelanceKind.DUE_SOON: ActionView.DUE_SOON,
}


def _responsables_notifiables(db) -> list[Responsable]:
    """Responsables disposant d'une adresse email exploitable."""
    return list(
        db.execute(
            select(Responsable)
            .filter(Responsable.is_mapped.is_(True), Responsable.email.isnot(None))
            .order_by(Responsable.display_name)
        )
        .scalars()
        .all()
    )


def _en_periode_de_silence(db, responsable_id) -> bool:
    """Le beat tourne chaque jour ; sans ce délai, un responsable recevrait un
    rappel quotidien tant qu'une action reste ouverte."""
    if settings.relance_cooldown_days <= 0:
        return False
    seuil = datetime.now(timezone.utc) - timedelta(days=settings.relance_cooldown_days)
    derniere = db.execute(
        select(func.max(RelanceLog.sent_at)).filter(
            RelanceLog.responsable_id == responsable_id
        )
    ).scalar_one_or_none()
    if derniere is None:
        return False
    if derniere.tzinfo is None:
        derniere = derniere.replace(tzinfo=timezone.utc)
    return derniere >= seuil


@app.task(name="app.workers.notifications.check_and_send", bind=True, max_retries=2)
def check_and_send(self, kind: str = RelanceKind.OVERDUE.value):
    """
    Tâche périodique (Celery Beat).

    Args:
        kind: `overdue`, `today` ou `due_soon` — détermine la sélection des
            actions et le gabarit d'email utilisés.
    """
    try:
        nature = RelanceKind(kind)
    except ValueError:
        raise ValueError(
            f"Nature de relance inconnue : {kind!r} "
            f"(attendu : {', '.join(k.value for k in RelanceKind)})"
        )

    db = SessionLocal()
    envoyes = simules = echecs = ignores = 0
    try:
        for responsable in _responsables_notifiables(db):
            stmt = build_actions_query(
                view=_VUE_PAR_NATURE[nature],
                responsable_id=responsable.id,
                active_projects_only=True,
                due_soon_days=settings.relance_horizon_days,
            )
            stmt = default_order(stmt).options(
                selectinload(Action.responsables), selectinload(Action.project)
            )
            actions = list(db.execute(stmt).scalars().unique().all())
            if not actions:
                continue

            if _en_periode_de_silence(db, responsable.id):
                ignores += 1
                continue

            message = build_email(
                nature,
                responsable.display_name,
                [to_digest(a) for a in actions],
                app_url=f"{settings.frontend_url}/actions",
            )
            resultat = outlook.send_email(
                to=responsable.email,
                subject=message.subject,
                html_body=message.html,
                text_body=message.text,
            )

            if resultat.ok:
                db.add(
                    RelanceLog(
                        responsable_id=responsable.id,
                        action_ids=",".join(str(a.id) for a in actions),
                        email_status=resultat.status.value,
                    )
                )
                db.commit()
                if resultat.status is outlook.SendStatus.SENT:
                    envoyes += 1
                else:
                    simules += 1
            else:
                echecs += 1
                logger.error(
                    "Relance %s non envoyée à %s : %s",
                    nature.value, responsable.email, resultat.detail,
                )

        logger.info(
            "Relances %s terminées — %d envoyées, %d simulées, %d en échec, "
            "%d en période de silence (mode : %s)",
            nature.value, envoyes, simules, echecs, ignores, outlook.send_mode().value,
        )
        return {
            "status": "success",
            "kind": nature.value,
            "mode": outlook.send_mode().value,
            "sent": envoyes,
            "simulated": simules,
            "failed": echecs,
            "skipped_cooldown": ignores,
        }

    except Exception as exc:
        db.rollback()
        logger.exception("Erreur lors de l'envoi des relances %s", kind)
        raise self.retry(exc=exc, countdown=300)
    finally:
        db.close()


@app.task(name="app.workers.notifications.mark_overdue_actions")
def mark_overdue_actions():
    """Bascule en `EN_RETARD` les actions dont l'échéance est dépassée.

    Le statut n'était recalculé qu'à l'écriture (API ou import Excel) : une
    action créée en avance et jamais retouchée restait « à faire » des mois
    après son échéance, et n'apparaissait donc dans aucun tableau de bord de
    retard fondé sur le statut.

    `BLOQUE` est exclu volontairement : c'est un constat humain, le remplacer
    par « en retard » ferait perdre l'information utile au pilotage. Le retard
    de ces actions reste visible par la date.
    """
    db = SessionLocal()
    try:
        today = datetime.now(timezone.utc).date()
        modifiees = (
            db.query(Action)
            .filter(
                Action.deadline.isnot(None),
                # Strictement antérieure : le jour de l'échéance, l'action a
                # encore sa journée. Le beat tourne à 7 h 45, il basculerait
                # sinon des actions que leur responsable a jusqu'au soir pour
                # livrer.
                Action.deadline < today,
                Action.progress < 100.0,
                Action.status.notin_(
                    [ActionStatus.EN_RETARD, ActionStatus.TERMINE, ActionStatus.BLOQUE]
                ),
            )
            .update(
                {Action.status: ActionStatus.EN_RETARD, Action.updated_at: func.now()},
                synchronize_session=False,
            )
        )
        db.commit()
        logger.info("Actions basculées en retard : %d", modifiees)
        return {"status": "success", "updated": modifiees}
    except Exception:
        db.rollback()
        logger.exception("Erreur lors du marquage des actions en retard")
        raise
    finally:
        db.close()
