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

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.database import SessionLocal
from app.models.project import (
    Action,
    Project,
    Responsable,
    SyncLog,
    SyncStatus,
)
from app.services.action_rules import apply_indicators
from app.services.events import publish_event_sync
from app.services.names import dedupe, normalize_key
from app.services.excel_parser import ParsedAction, parse_workbook
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
    except Exception as exc:
        db.rollback()
        db.close()
        logger.exception("Impossible de créer le SyncLog initial pour %s", project_id)
        raise self.retry(exc=exc, countdown=60)

    try:
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise ValueError(f"Projet introuvable : {project_id}")

        # 1. Parser le fichier Excel.
        #    Le code projet vient de la base et non du fichier : les numéros y
        #    sont saisis à la main, avec des préfixes parfois erronés (dans le
        #    classeur de P10, des actions sont numérotées « P02 -13 - 1 »).
        lecture = parse_workbook(file_path, project_code=project.code)
        parsed_actions = lecture.actions
        if not parsed_actions:
            logger.warning("Aucune action trouvée dans %s", file_path)

        created, updated, errors = 0, 0, 0

        for row in parsed_actions:
            try:
                # `_upsert_action` renvoie l'information création/mise à jour.
                # Elle était auparavant redéduite par une requête exécutée
                # *après* le commit : l'action existait alors toujours, et
                # toute création était comptée comme une mise à jour — le
                # rapport de synchronisation affichait systématiquement
                # « 0 créées ».
                was_created = _upsert_action(db, project, row)
                db.commit()
                if was_created:
                    created += 1
                else:
                    updated += 1
            except IntegrityError:
                db.rollback()
                errors += 1
                logger.exception("Erreur d'intégrité pour l'action %s", row.numero)
            except Exception:
                db.rollback()
                errors += 1
                logger.exception("Erreur lors du traitement de l'action %s", row.numero)

        # 2. Mettre à jour le projet
        project.last_synced_at = datetime.now(timezone.utc)
        db.commit()

        # 3. Finaliser le SyncLog
        sync_log.finished_at = datetime.now(timezone.utc)
        sync_log.status = SyncStatus.SUCCESS
        sync_log.files_processed = 1
        # Les avertissements de lecture sont conservés dans le journal : une
        # échéance illisible ou un numéro en double n'interrompt pas l'import
        # mais doit rester consultable depuis `/api/v1/sync-logs`.
        diagnostics = list(lecture.warnings)
        if errors:
            diagnostics.append(f"{errors} ligne(s) en erreur, voir les logs du worker.")
        if diagnostics:
            sync_log.error_message = " | ".join(diagnostics)[:2000]
        db.commit()

        logger.info(
            "Sync terminée pour %s : %d créées, %d mises à jour, %d erreurs "
            "(feuille %r, en-tête L%s, phases %s, %d lignes de section)",
            project.code, created, updated, errors,
            lecture.sheet_name, lecture.header_row,
            lecture.phases or "aucune", lecture.section_rows,
        )
        for avertissement in lecture.warnings:
            logger.warning("[%s] %s", project.code, avertissement)

        # 4. Notifier les clients connectés (dashboard temps réel)
        publish_event_sync(
            "project_synced",
            {
                "project_id": str(project.id),
                "code": project.code,
                "created": created,
                "updated": updated,
                "errors": errors,
            },
        )

        return {
            "status": "success",
            "project_code": project.code,
            "created": created,
            "updated": updated,
            "errors": errors,
        }

    except Exception as exc:
        try:
            db.rollback()
            sync_log.finished_at = datetime.now(timezone.utc)
            sync_log.status = SyncStatus.FAILED
            sync_log.error_message = str(exc)[:500]
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Impossible d'enregistrer l'échec du SyncLog pour %s", project_id)
        logger.exception("Sync échouée pour le projet %s", project_id)
        raise self.retry(exc=exc, countdown=60)

    finally:
        db.close()


def _upsert_action(db, project: Project, row: ParsedAction) -> bool:
    """Crée ou met à jour une action à partir d'une ligne Excel parsée.

    Returns:
        True si l'action a été créée, False si elle a été mise à jour.
    """
    existing = (
        db.query(Action)
        .options(selectinload(Action.responsables))
        .filter(Action.project_id == project.id, Action.numero == row.numero)
        .first()
    )

    # La phase vient du parseur, qui la lit dans la colonne « Projets » ou dans
    # la hiérarchie des sections. Elle n'est conservée que si le projet est
    # configuré en mode phases : sinon les actions arriveraient avec un numéro
    # à trois segments et une colonne `phase` vide, incohérence que la
    # génération de numéro côté API ne saurait pas rattraper.
    phase = row.phase if project.has_phases else None

    action = existing or Action(project_id=project.id, numero=row.numero)
    is_new = existing is None

    action.phase = phase
    action.description = row.description
    action.resp_suivi = row.resp_suivi
    action.progress = row.progress
    # Le classeur fait autorité quand la cellule est renseignée ; laissée vide,
    # la valeur est déduite de l'avancement et des dates plutôt que d'être
    # stockée à 0, ce qui ferait chuter les moyennes des rapports.
    if row.spi is not None:
        action.spi = row.spi
    if row.otd is not None:
        action.otd = row.otd
    action.deadline = row.deadline
    action.date_realisation = row.date_realisation
    action.charges_hj = row.charges_hj
    action.commentaire = row.commentaire

    # Le fichier Excel fait autorité sur la date de réalisation (colonne J) :
    # on recalcule le statut sans y toucher.
    apply_indicators(
        action,
        manage_date_realisation=False,
        recompute_spi=row.spi is None,
        recompute_otd=row.otd is None,
    )

    if is_new:
        db.add(action)
        db.flush()  # Obtenir l'ID avant d'ajouter les responsables

    _sync_responsables(db, action, row.responsable_names)
    return is_new


def _sync_responsables(db, action: Action, names: list[str]) -> None:
    """Aligne la liste des responsables d'une action sur celle du fichier.

    Le `clear()` systématique d'avant produisait un DELETE + INSERT de toutes
    les associations à chaque synchronisation, même quand rien n'avait changé —
    inutilement coûteux, et bruyant dans les journaux de réplication.
    """
    voulus = dedupe(names)
    cles_voulues = {normalize_key(n) for n in voulus}

    for responsable in list(action.responsables):
        if normalize_key(responsable.display_name) not in cles_voulues:
            action.responsables.remove(responsable)

    deja = {normalize_key(r.display_name): r for r in action.responsables}

    for nom in voulus:
        cle = normalize_key(nom)
        if cle in deja:
            continue
        # Rapprochement sur la clé : les classeurs écrivent « AndryII »,
        # « Andry II » et « andry ii » pour la même personne. Une fiche par
        # graphie, c'est une charge éclatée et plusieurs relances par agent.
        resp = db.query(Responsable).filter(Responsable.name_key == cle).first()
        if not resp:
            resp = Responsable(display_name=nom, name_key=cle, is_mapped=False)
            db.add(resp)
            db.flush()
        action.responsables.append(resp)
        deja[cle] = resp


@app.task(name="app.workers.ingestion.sync_sharepoint")
def sync_sharepoint():
    """Placeholder pour la synchronisation automatique depuis SharePoint."""
    logger.info("sync_sharepoint appelé — utilisez sync_project_file pour un import ciblé")
    return {"status": "use_sync_project_file"}
