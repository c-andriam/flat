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
import tempfile
from pathlib import Path
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
from app.models.user import User
from app.services.action_rules import apply_indicators
from app.services.events import publish_event_sync
from app.services.names import dedupe, normalize_key
from app.services.excel_parser import ParsedAction, parse_workbook
from app.services import graph_files
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
        # Emails connus : ils départagent les libellés à tiret. « Jean-Pierre »
        # est une personne si une adresse au même nom existe, deux sinon —
        # information que le classeur ne porte pas.
        emails_connus = {
            email
            for (email,) in db.query(Responsable.email).filter(Responsable.email.isnot(None))
        }
        emails_connus.update(
            email for (email,) in db.query(User.email).filter(User.email.isnot(None))
        )

        lecture = parse_workbook(
            file_path, project_code=project.code, emails_connus=emails_connus
        )
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
        # Les deux collections sont réécrites plus bas : sans préchargement,
        # chaque action du classeur déclencherait deux requêtes de plus.
        .options(selectinload(Action.responsables), selectinload(Action.suiveurs))
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

    _sync_responsables(db, action.responsables, row.responsable_names)
    # Colonne E. Elle n'était conservée que sous forme de texte : le
    # responsable de suivi, celui qui pilote réellement l'action, n'avait donc
    # aucune adresse et ne pouvait pas être relancé. La résoudre en fiches
    # applique les mêmes règles de rapprochement qu'à la colonne D.
    _sync_responsables(db, action.suiveurs, row.resp_suivi_names)
    return is_new


def _sync_responsables(db, collection, names: list[str]) -> None:
    """Aligne une collection de responsables sur la liste lue dans le fichier.

    `collection` est `action.responsables` (colonne D) ou `action.suiveurs`
    (colonne E) : les deux se rapprochent selon les mêmes règles, et deux
    implémentations auraient fini par diverger.

    Le `clear()` systématique d'avant produisait un DELETE + INSERT de toutes
    les associations à chaque synchronisation, même quand rien n'avait changé —
    inutilement coûteux, et bruyant dans les journaux de réplication.
    """
    voulus = dedupe(names)
    cles_voulues = {normalize_key(n) for n in voulus}

    for responsable in list(collection):
        if normalize_key(responsable.display_name) not in cles_voulues:
            collection.remove(responsable)

    deja = {normalize_key(r.display_name): r for r in collection}

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
        collection.append(resp)
        deja[cle] = resp


@app.task(name="app.workers.ingestion.sync_sharepoint", bind=True, max_retries=2)
def sync_sharepoint(self, only: str | None = None, dry_run: bool = False):
    """Importe les classeurs de suivi depuis SharePoint.

    Parcourt le dossier racine, retient les dossiers respectant la convention
    « P01 - Nom », télécharge le classeur le plus récent de chacun et le passe
    au même chemin d'import que `sync_project_file`. Le parseur et les règles
    de rapprochement sont donc rigoureusement identiques à ceux de l'import
    depuis un dossier local — deux implémentations auraient fini par diverger.

    Sens unique : rien n'est écrit dans SharePoint.

    Args:
        only: ne traiter qu'un projet, par son code (ex. « P10 »).
        dry_run: parcourir et télécharger sans rien écrire en base.
    """
    if not graph_files.is_configured():
        detail = graph_files.configuration_explanation()
        logger.warning("sync_sharepoint ignoré : %s", detail)
        return {"status": "not_configured", "detail": detail}

    try:
        dossiers = graph_files.list_project_folders()
    except graph_files.GraphFilesError as erreur:
        logger.error("Parcours SharePoint impossible : %s", erreur)
        raise self.retry(exc=erreur, countdown=300)

    if only:
        dossiers = [d for d in dossiers if d.code.upper() == only.upper()]

    resultats: list[dict] = []
    # Répertoire temporaire supprimé à la sortie : conserver les classeurs
    # téléchargés ferait grossir le conteneur sans que personne ne le remarque.
    with tempfile.TemporaryDirectory(prefix="dsio-sharepoint-") as tampon:
        racine = Path(tampon)
        for dossier in dossiers:
            if not dossier.has_workbook:
                logger.warning("%s : aucun classeur exploitable", dossier.code)
                resultats.append({"code": dossier.code, "status": "no_workbook"})
                continue

            try:
                local = graph_files.download_item(
                    dossier.workbook, racine / dossier.code / dossier.workbook.name
                )
            except graph_files.GraphFilesError as erreur:
                logger.error("%s : téléchargement échoué — %s", dossier.code, erreur)
                resultats.append({"code": dossier.code, "status": "download_failed"})
                continue

            projet_id = _resoudre_projet(dossier, str(dossier.workbook.web_url or ""), dry_run)
            if projet_id is None:
                resultats.append({"code": dossier.code, "status": "project_missing"})
                continue

            if dry_run:
                resultats.append(
                    {"code": dossier.code, "status": "downloaded", "file": dossier.workbook.name}
                )
                continue

            try:
                # Appel direct plutôt que `.delay()` : la tâche courante tient
                # déjà le fichier téléchargé, qui disparaît avec le répertoire
                # temporaire dès son retour.
                sortie = sync_project_file(projet_id, str(local))
                resultats.append({"code": dossier.code, "status": "synced", "detail": sortie})
            except Exception:
                logger.exception("%s : import échoué", dossier.code)
                resultats.append({"code": dossier.code, "status": "import_failed"})

    return {
        "status": "ok",
        "folders": len(dossiers),
        "results": resultats,
    }


def _resoudre_projet(dossier, source_url: str, dry_run: bool) -> str | None:
    """Projet correspondant au dossier, créé s'il n'existe pas encore.

    Le code fait foi, pas le nom : les dossiers sont renommés au fil des
    réorganisations, alors que « P01 » reste « P01 ».
    """
    db = SessionLocal()
    try:
        projet = db.query(Project).filter(Project.code == dossier.code).first()
        if projet is None:
            if dry_run:
                logger.info("%s : projet à créer (%s)", dossier.code, dossier.name)
                return None
            projet = Project(
                code=dossier.code,
                name=dossier.name,
                source_file_path=source_url or f"{dossier.code}/{dossier.folder.name}",
            )
            db.add(projet)
            db.commit()
            db.refresh(projet)
            logger.info("Projet créé depuis SharePoint : %s — %s", projet.code, projet.name)
        elif not dry_run and source_url and projet.source_file_path != source_url:
            # L'ancre suit le fichier : un classeur déplacé ou renommé ne doit
            # pas laisser le projet pointer vers une adresse morte.
            projet.source_file_path = source_url
            db.commit()
        return str(projet.id)
    finally:
        db.close()
