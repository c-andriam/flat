import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.exc import IntegrityError
from app.database import get_db
from app.models.project import (
    Action,
    ActionStatus,
    Project,
    RelanceLog,
    Responsable,
    SyncLog,
)
from app.schemas.project_schema import (
    ActionCreate,
    ActionOut,
    ActionUpdate,
    ProjectCreate,
    ProjectOut,
    ProjectUpdate,
    ProjectWithActionsOut,
    RelanceLogOut,
    ResponsableCreate,
    ResponsableOut,
    ResponsableUpdate,
    SyncLogOut,
)
from app.services.health import perform_health_check

router = APIRouter(tags=["core"])


# ---------------------------------------------------------------------------
# Projects — CRUD complet
# ---------------------------------------------------------------------------

@router.get(
    "/projects",
    response_model=list[ProjectOut],
    tags=["projects"],
    summary="Lister les projets",
    description="Retourne tous les projets suivis, triés par code projet.",
    response_description="Liste des projets.",
)
def list_projects(db: Session = Depends(get_db)):
    return db.query(Project).order_by(Project.code).all()


@router.get(
    "/projects/{project_id}",
    response_model=ProjectWithActionsOut,
    tags=["projects"],
    summary="Détail d'un projet",
    description="Retourne un projet avec l'ensemble de ses actions et, pour chaque action, ses responsables associés.",
    response_description="Projet avec ses actions imbriquées.",
    responses={404: {"description": "Aucun projet avec cet identifiant."}},
)
def get_project(project_id: uuid.UUID, db: Session = Depends(get_db)):
    project = (
        db.query(Project)
        .options(joinedload(Project.actions).joinedload(Action.responsables))
        .filter(Project.id == project_id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Projet introuvable")
    return project


@router.post(
    "/projects",
    response_model=ProjectOut,
    status_code=201,
    tags=["projects"],
    summary="Créer un projet",
    description="Crée un nouveau projet. Le `code` projet doit être unique.",
    response_description="Le projet créé.",
    responses={409: {"description": "Un projet avec ce code existe déjà."}},
)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)):
    existing = db.query(Project).filter(Project.code == payload.code).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Le projet '{payload.code}' existe déjà")

    project = Project(**payload.model_dump())
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.patch(
    "/projects/{project_id}",
    response_model=ProjectOut,
    tags=["projects"],
    summary="Mettre à jour un projet",
    description="Mise à jour partielle (seuls les champs fournis sont modifiés).",
    response_description="Le projet mis à jour.",
    responses={404: {"description": "Aucun projet avec cet identifiant."}},
)
def update_project(project_id: uuid.UUID, payload: ProjectUpdate, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Projet introuvable")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(project, field, value)

    db.commit()
    db.refresh(project)
    return project


@router.delete(
    "/projects/{project_id}",
    status_code=204,
    tags=["projects"],
    summary="Supprimer un projet",
    description="Supprime le projet ainsi que toutes ses actions rattachées (cascade).",
    response_description="Aucun contenu — suppression effectuée.",
    responses={404: {"description": "Aucun projet avec cet identifiant."}},
)
def delete_project(project_id: uuid.UUID, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Projet introuvable")

    db.delete(project)  # cascade -> supprime aussi les actions liées
    db.commit()


# ---------------------------------------------------------------------------
# Actions — CRUD complet
# ---------------------------------------------------------------------------

@router.get(
    "/actions",
    response_model=list[ActionOut],
    tags=["actions"],
    summary="Lister les actions",
    description=(
        "Vue synthétique des actions, filtrable par projet, par responsable, "
        "ou uniquement les actions en retard (`deadline <= aujourd'hui` ET "
        "`progress < 100`)."
    ),
    response_description="Liste des actions correspondant aux filtres.",
)
def list_actions(
    project_id: uuid.UUID | None = Query(None, description="Filtrer par identifiant de projet."),
    responsable: str | None = Query(None, description="Filtrer par nom affiché du responsable."),
    overdue_only: bool = Query(False, description="Ne retourner que les actions en retard."),
    db: Session = Depends(get_db),
):
    query = db.query(Action).options(joinedload(Action.responsables))

    if project_id is not None:
        query = query.filter(Action.project_id == project_id)

    if responsable is not None:
        query = query.join(Action.responsables).filter(Responsable.display_name == responsable)

    actions = query.all()

    if overdue_only:
        today = date.today()
        actions = [a for a in actions if a.is_overdue(today)]

    return actions


@router.get(
    "/actions/{action_id}",
    response_model=ActionOut,
    tags=["actions"],
    summary="Détail d'une action",
    description="Retourne une action avec la liste de ses responsables.",
    response_description="L'action demandée.",
    responses={404: {"description": "Aucune action avec cet identifiant."}},
)
def get_action(action_id: uuid.UUID, db: Session = Depends(get_db)):
    action = (
        db.query(Action)
        .options(joinedload(Action.responsables))
        .filter(Action.id == action_id)
        .first()
    )
    if not action:
        raise HTTPException(status_code=404, detail="Action introuvable")
    return action


def _generate_numero(db, project, phase):
    query = db.query(Action.numero).filter(Action.project_id == project.id)
    if phase is not None:
        query = query.filter(Action.phase == phase)
    else:
        query = query.filter(Action.phase.is_(None))

    max_num = 0
    for (numero_str,) in query.all():
        if numero_str and "-" in numero_str:
            try:
                max_num = max(max_num, int(numero_str.split("-")[-1]))
            except ValueError:
                continue

    if phase is not None:
        return f"{project.code}-{phase}-{max_num + 1:02d}"
    return f"{project.code}-{max_num + 1:02d}"


@router.post(
    "/actions",
    response_model=ActionOut,
    status_code=201,
    tags=["actions"],
    summary="Créer une action",
    description=(
        "Crée une action rattachée à un projet existant. Le numéro d'action "
        "est généré automatiquement (ex: P01-01). Les responsables "
        "listés dans `responsable_names` sont associés par nom affiché ; tout "
        "nom inconnu est créé automatiquement comme `Responsable` non mappé "
        "(`is_mapped=False`), à associer ensuite à un email."
    ),
    response_description="L'action créée.",
    responses={404: {"description": "Le projet référencé est introuvable."}},
)
def create_action(payload: ActionCreate, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == payload.project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Projet introuvable")

    phase = payload.phase if project.has_phases else None

    if project.has_phases and not phase:
        raise HTTPException(
            status_code=422,
            detail="Ce projet utilise les phases (has_phases=True) : le champ 'phase' est obligatoire.",
        )

    data = payload.model_dump(exclude={"responsable_names", "phase"})

    # Retry en cas de conflit sur numero (deux créations concurrentes ayant lu
    # le même max_num avant de committer). La contrainte unique en base
    # (project_id, numero) garantit qu'aucun doublon ne peut passer ; on se
    # contente ici de régénérer un numero frais et de réessayer.
    max_attempts = 5
    for attempt in range(1, max_attempts + 1):
        generated_numero = _generate_numero(db, project, phase)
        action = Action(**data, numero=generated_numero, phase=phase)

        for name in payload.responsable_names:
            responsable = db.query(Responsable).filter(Responsable.display_name == name).first()
            if not responsable:
                responsable = Responsable(display_name=name, is_mapped=False)
                db.add(responsable)
            action.responsables.append(responsable)

        db.add(action)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            if attempt == max_attempts:
                raise HTTPException(
                    status_code=409,
                    detail="Impossible de générer un numéro d'action unique après plusieurs tentatives, réessaie.",
                )
            continue
        else:
            db.refresh(action)
            return action



@router.patch(
    "/actions/{action_id}",
    response_model=ActionOut,
    tags=["actions"],
    summary="Mettre à jour une action",
    description=(
        "Permet de cocher/valider une action depuis le logiciel (ex: "
        "`progress`). Passer `progress` à 100 ou plus bascule automatiquement "
        "le statut sur `TERMINE` et assigne une date de complétion."
    ),
    response_description="L'action mise à jour.",
    responses={
        404: {"description": "Aucune action avec cet identifiant."},
        422: {"description": "Valeur de `status` invalide."},
    },
)
def update_action(action_id: uuid.UUID, payload: ActionUpdate, db: Session = Depends(get_db)):
    action = db.query(Action).filter(Action.id == action_id).first()
    if not action:
        raise HTTPException(status_code=404, detail="Action introuvable")

    update_data = payload.model_dump(exclude_unset=True)

    if "status" in update_data:
        try:
            update_data["status"] = ActionStatus(update_data["status"])
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Statut invalide: {update_data['status']}")

    # Changer la phase doit rester cohérent avec has_phases du projet, et
    # regénérer numero (qui encode la phase, ex: P01-01-05) pour éviter
    # qu'il reste désynchronisé de la vraie phase de l'action.
    if "phase" in update_data:
        project = action.project
        new_phase = update_data["phase"]

        if project.has_phases and not new_phase:
            raise HTTPException(
                status_code=422,
                detail="Ce projet utilise les phases (has_phases=True) : le champ 'phase' est obligatoire.",
            )
        if not project.has_phases and new_phase:
            raise HTTPException(
                status_code=422,
                detail="Ce projet n'utilise pas les phases (has_phases=False) : le champ 'phase' doit rester vide.",
            )

        if new_phase != action.phase:
            update_data["numero"] = _generate_numero(db, project, new_phase)

    for field, value in update_data.items():
        setattr(action, field, value)

    if "progress" in update_data and update_data["progress"] >= 100.0:
        action.status = ActionStatus.TERMINE
        if action.date_realisation is None:
            action.date_realisation = date.today()

    db.commit()
    db.refresh(action)
    return action


@router.delete(
    "/actions/{action_id}",
    status_code=204,
    tags=["actions"],
    summary="Supprimer une action",
    description="Supprime définitivement une action.",
    response_description="Aucun contenu — suppression effectuée.",
    responses={404: {"description": "Aucune action avec cet identifiant."}},
)
def delete_action(action_id: uuid.UUID, db: Session = Depends(get_db)):
    action = db.query(Action).filter(Action.id == action_id).first()
    if not action:
        raise HTTPException(status_code=404, detail="Action introuvable")

    db.delete(action)
    db.commit()


# ---------------------------------------------------------------------------
# Responsables — CRUD complet (mapping nom Excel <-> email)
# ---------------------------------------------------------------------------

@router.get(
    "/responsables",
    response_model=list[ResponsableOut],
    tags=["responsables"],
    summary="Lister les responsables",
    description="Retourne les responsables, avec option pour ne lister que ceux non encore mappés à un email.",
    response_description="Liste des responsables.",
)
def list_responsables(
    unmapped_only: bool = Query(False, description="Ne retourner que les responsables sans email associé."),
    db: Session = Depends(get_db),
):
    query = db.query(Responsable)
    if unmapped_only:
        query = query.filter(Responsable.is_mapped.is_(False))
    return query.order_by(Responsable.display_name).all()


@router.get(
    "/responsables/{responsable_id}",
    response_model=ResponsableOut,
    tags=["responsables"],
    summary="Détail d'un responsable",
    response_description="Le responsable demandé.",
    responses={404: {"description": "Aucun responsable avec cet identifiant."}},
)
def get_responsable(responsable_id: uuid.UUID, db: Session = Depends(get_db)):
    responsable = db.query(Responsable).filter(Responsable.id == responsable_id).first()
    if not responsable:
        raise HTTPException(status_code=404, detail="Responsable introuvable")
    return responsable


@router.post(
    "/responsables",
    response_model=ResponsableOut,
    status_code=201,
    tags=["responsables"],
    summary="Créer un responsable",
    description="Crée un responsable. `is_mapped` est déduit automatiquement selon la présence d'un email.",
    response_description="Le responsable créé.",
    responses={409: {"description": "Un responsable avec ce nom affiché existe déjà."}},
)
def create_responsable(payload: ResponsableCreate, db: Session = Depends(get_db)):
    existing = db.query(Responsable).filter(Responsable.display_name == payload.display_name).first()
    if existing:
        raise HTTPException(status_code=409, detail="Ce responsable existe déjà")

    responsable = Responsable(
        display_name=payload.display_name,
        email=payload.email,
        is_mapped=payload.email is not None,
    )
    db.add(responsable)
    db.commit()
    db.refresh(responsable)
    return responsable


@router.patch(
    "/responsables/{responsable_id}",
    response_model=ResponsableOut,
    tags=["responsables"],
    summary="Associer/mettre à jour l'email d'un responsable",
    description="Renseigner `email` marque automatiquement le responsable comme mappé (`is_mapped=True`).",
    response_description="Le responsable mis à jour.",
    responses={404: {"description": "Aucun responsable avec cet identifiant."}},
)
def update_responsable(responsable_id: uuid.UUID, payload: ResponsableUpdate, db: Session = Depends(get_db)):
    responsable = db.query(Responsable).filter(Responsable.id == responsable_id).first()
    if not responsable:
        raise HTTPException(status_code=404, detail="Responsable introuvable")

    if payload.email is not None:
        responsable.email = payload.email
        responsable.is_mapped = True

    db.commit()
    db.refresh(responsable)
    return responsable


@router.delete(
    "/responsables/{responsable_id}",
    status_code=204,
    tags=["responsables"],
    summary="Supprimer un responsable",
    response_description="Aucun contenu — suppression effectuée.",
    responses={404: {"description": "Aucun responsable avec cet identifiant."}},
)
def delete_responsable(responsable_id: uuid.UUID, db: Session = Depends(get_db)):
    responsable = db.query(Responsable).filter(Responsable.id == responsable_id).first()
    if not responsable:
        raise HTTPException(status_code=404, detail="Responsable introuvable")

    db.delete(responsable)
    db.commit()


# ---------------------------------------------------------------------------
# Logs — lecture seule (SyncLog, RelanceLog)
# Pas de create/update/delete manuel : ce sont des traces générées par le
# système (worker d'ingestion / moteur d'alertes) — un audit trail modifiable
# n'aurait plus de valeur de preuve.
# ---------------------------------------------------------------------------

@router.get(
    "/sync-logs",
    response_model=list[SyncLogOut],
    tags=["logs"],
    summary="Historique des synchronisations Excel",
    description="Les 50 dernières synchronisations d'import Excel, les plus récentes en premier. Lecture seule.",
    response_description="Liste des journaux de synchronisation.",
)
def list_sync_logs(db: Session = Depends(get_db)):
    logs = db.query(SyncLog).order_by(SyncLog.started_at.desc()).limit(50).all()
    return [
        {
            "id": log.id,
            "started_at": log.started_at,
            "finished_at": log.finished_at,
            "status": log.status,
            "files_processed": log.files_processed,
            "error_message": log.error_message,
        }
        for log in logs
    ]


@router.get(
    "/relance-logs",
    response_model=list[RelanceLogOut],
    tags=["logs"],
    summary="Historique des relances email",
    description="Les 50 derniers envois de relance aux responsables, les plus récents en premier. Lecture seule.",
    response_description="Liste des journaux de relance.",
)
def list_relance_logs(db: Session = Depends(get_db)):
    logs = db.query(RelanceLog).order_by(RelanceLog.sent_at.desc()).limit(50).all()
    return [
        {
            "id": log.id,
            "responsable_id": log.responsable_id,
            "sent_at": log.sent_at,
            "email_status": log.email_status,
        }
        for log in logs
    ]

# ---------------------------------------------------------------------------
# Monitoring — Health check API v1
# ---------------------------------------------------------------------------

@router.get(
    "/health",
    tags=["monitoring"],
    summary="Vérifier l'état du service core (API v1)",
    description="Endpoint de health check accessible sur /api/v1/health.",
)
def health_check_v1(db: Session = Depends(get_db)):
    return perform_health_check(db)
