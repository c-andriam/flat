"""
Worker Celery d'ingestion : lit les fichiers Excel de suivi et synchronise
les actions vers PostgreSQL.

Flux :
1. Reçoit le chemin d'un fichier Excel + l'ID du projet associé
2. Parse le fichier via excel_parser
3. Pour chaque action :
   - Si le numéro existe déjà → met à jour les champs modifiés
   - Sinon → crée l'action + les responsables inconnus
4. Enregistre un SyncLog (succès ou échec)
5. Publie un événement temps réel sur Redis
"""

import logging
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.models.project import (
    Action,
    ActionStatus,
    Project,
    Responsable,
    SyncLog,
    SyncStatus,
    action_responsables,
)
from app.services.excel_parser import parse_excel_file
from app.workers.celery_app import app

logger = logging.getLogger("worker-ingestion")


@app.task(name="app.workers.ingestion.sync_project_file", bind=True, max_retries=3)
def sync_project_file(self, project_id: str, file_path: str):
    """
    Synchronise un fichier Excel vers la base de données pour un projet donné.

    Args:
        project_id: UUID du projet (str)
        file_path: Chemin absolu vers le fichier .xlsx
    """
    db = SessionLocal()
    sync_log = SyncLog(status=SyncStatus.RUNNING)
    db.add(sync_log)
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        logger.exception("Impossible de créer le SyncLog initial pour %s", project_id)
        raise self.retry(exc=e, countdown=60)

    try:
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise ValueError(f"Projet introuvable : {project_id}")

        # 1. Parser le fichier Excel
        parsed_actions = parse_excel_file(file_path)
        if not parsed_actions:
            logger.warning("Aucune action trouvée dans %s", file_path)

        created, updated, errors = 0, 0, 0

        for row in parsed_actions:
            try:
                _upsert_action(db, project, row)
                db.commit()

                # Déterminer si c'était une création ou une mise à jour
                existing = (
                    db.query(Action)
                    .filter(Action.project_id == project.id, Action.numero == row["numero"])
                    .first()
                )
                if existing:
                    updated += 1
                else:
                    created += 1
            except IntegrityError:
                db.rollback()
                errors += 1
                logger.error("Erreur d'intégrité pour l'action %s", row.get("numero"))
            except Exception as e:
                db.rollback()
                errors += 1
                logger.error("Erreur lors du traitement de l'action %s : %s", row.get("numero"), e)

        # 2. Mettre à jour le projet
        project.last_synced_at = datetime.now(timezone.utc)
        db.commit()

        # 3. Finaliser le SyncLog
        sync_log.finished_at = datetime.now(timezone.utc)
        sync_log.status = SyncStatus.SUCCESS
        sync_log.files_processed = 1
        db.commit()

        logger.info(
            "Sync terminée pour %s : %d créées, %d mises à jour, %d erreurs",
            project.code, created, updated, errors,
        )
        return {
            "status": "success",
            "project_code": project.code,
            "created": created,
            "updated": updated,
            "errors": errors,
        }

    except Exception as e:
        try:
            db.rollback()
            sync_log.finished_at = datetime.now(timezone.utc)
            sync_log.status = SyncStatus.FAILED
            sync_log.error_message = str(e)[:500]
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Impossible d'enregistrer l'échec du SyncLog pour %s", project_id)
        logger.exception("Sync échouée pour le projet %s", project_id)
        raise self.retry(exc=e, countdown=60)

    finally:
        db.close()


def _upsert_action(db, project: Project, row: dict):
    """Crée ou met à jour une action à partir d'une ligne Excel parsée."""
    existing = (
        db.query(Action)
        .filter(Action.project_id == project.id, Action.numero == row["numero"])
        .first()
    )

    if existing:
        # Mise à jour des champs modifiables
        existing.description = row["description"]
        existing.resp_suivi = row["resp_suivi"]
        existing.progress = row["progress"]
        existing.spi = row["spi"]
        existing.otd = row["otd"]
        existing.deadline = row["deadline"]
        existing.date_realisation = row["date_realisation"]
        existing.charges_hj = row["charges_hj"]
        existing.commentaire = row["commentaire"]

        # Mise à jour automatique du statut
        if existing.progress >= 100.0:
            existing.status = ActionStatus.TERMINE
        elif existing.deadline and existing.deadline <= datetime.now(timezone.utc).date() and existing.progress < 100.0:
            existing.status = ActionStatus.EN_RETARD

        # Synchroniser les responsables
        _sync_responsables(db, existing, row["responsable_names"])
    else:
        # Création
        action = Action(
            project_id=project.id,
            numero=row["numero"],
            description=row["description"],
            resp_suivi=row["resp_suivi"],
            progress=row["progress"],
            spi=row["spi"],
            otd=row["otd"],
            deadline=row["deadline"],
            date_realisation=row["date_realisation"],
            charges_hj=row["charges_hj"],
            commentaire=row["commentaire"],
        )

        # Statut automatique
        if action.progress >= 100.0:
            action.status = ActionStatus.TERMINE
        elif action.deadline and action.deadline <= datetime.now(timezone.utc).date():
            action.status = ActionStatus.EN_RETARD

        db.add(action)
        db.flush()  # Obtenir l'ID avant d'ajouter les responsables

        _sync_responsables(db, action, row["responsable_names"])


def _sync_responsables(db, action: Action, names: list[str]):
    """Synchronise la liste des responsables d'une action."""
    action.responsables.clear()

    for name in names:
        resp = db.query(Responsable).filter(Responsable.display_name == name).first()
        if not resp:
            resp = Responsable(display_name=name, is_mapped=False)
            db.add(resp)
            db.flush()
        action.responsables.append(resp)


@app.task(name="app.workers.ingestion.sync_sharepoint")
def sync_sharepoint():
    """Placeholder pour la synchronisation automatique depuis SharePoint."""
    logger.info("sync_sharepoint appelé — utilisez sync_project_file pour un import ciblé")
    return {"status": "use_sync_project_file"}
