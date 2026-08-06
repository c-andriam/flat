import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

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
    ResponsableCreate,
    ResponsableOut,
    ResponsableUpdate,
)

router = APIRouter(tags=["core"])


# ---------------------------------------------------------------------------
# Projects — CRUD complet
# ---------------------------------------------------------------------------

@router.get("/projects", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db)):
    return db.query(Project).order_by(Project.code).all()


@router.get("/projects/{project_id}", response_model=ProjectWithActionsOut)
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


@router.post("/projects", response_model=ProjectOut, status_code=201)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)):
    existing = db.query(Project).filter(Project.code == payload.code).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Le projet '{payload.code}' existe déjà")

    project = Project(**payload.model_dump())
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.patch("/projects/{project_id}", response_model=ProjectOut)
def update_project(project_id: uuid.UUID, payload: ProjectUpdate, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Projet introuvable")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(project, field, value)

    db.commit()
    db.refresh(project)
    return project


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: uuid.UUID, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Projet introuvable")

    db.delete(project)  # cascade -> supprime aussi les actions liées
    db.commit()


# ---------------------------------------------------------------------------
# Actions — CRUD complet
# ---------------------------------------------------------------------------

@router.get("/actions", response_model=list[ActionOut])
def list_actions(
    project_id: uuid.UUID | None = None,
    responsable: str | None = None,
    overdue_only: bool = False,
    db: Session = Depends(get_db),
):
    """
    Vue synthétique des actions, filtrable par projet, par responsable,
    ou uniquement les actions en retard (deadline <= aujourd'hui ET progress < 100).
    """
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


@router.get("/actions/{action_id}", response_model=ActionOut)
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


@router.post("/actions", response_model=ActionOut, status_code=201)
def create_action(payload: ActionCreate, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == payload.project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Projet introuvable")

    data = payload.model_dump(exclude={"responsable_names"})
    action = Action(**data)

    for name in payload.responsable_names:
        responsable = db.query(Responsable).filter(Responsable.display_name == name).first()
        if not responsable:
            # nouveau nom détecté dans Excel -> créé non-mappé, à associer à un email ensuite
            responsable = Responsable(display_name=name, is_mapped=False)
            db.add(responsable)
        action.responsables.append(responsable)

    db.add(action)
    db.commit()
    db.refresh(action)
    return action


@router.patch("/actions/{action_id}", response_model=ActionOut)
def update_action(action_id: uuid.UUID, payload: ActionUpdate, db: Session = Depends(get_db)):
    """Permet de cocher/valider une action depuis le logiciel (ex: %progress)."""
    action = db.query(Action).filter(Action.id == action_id).first()
    if not action:
        raise HTTPException(status_code=404, detail="Action introuvable")

    update_data = payload.model_dump(exclude_unset=True)

    if "status" in update_data:
        try:
            update_data["status"] = ActionStatus(update_data["status"])
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Statut invalide: {update_data['status']}")

    for field, value in update_data.items():
        setattr(action, field, value)

    if "progress" in update_data and update_data["progress"] >= 100.0:
        action.status = ActionStatus.TERMINE

    db.commit()
    db.refresh(action)
    return action


@router.delete("/actions/{action_id}", status_code=204)
def delete_action(action_id: uuid.UUID, db: Session = Depends(get_db)):
    action = db.query(Action).filter(Action.id == action_id).first()
    if not action:
        raise HTTPException(status_code=404, detail="Action introuvable")

    db.delete(action)
    db.commit()


# ---------------------------------------------------------------------------
# Responsables — CRUD complet (mapping nom Excel <-> email)
# ---------------------------------------------------------------------------

@router.get("/responsables", response_model=list[ResponsableOut])
def list_responsables(unmapped_only: bool = False, db: Session = Depends(get_db)):
    query = db.query(Responsable)
    if unmapped_only:
        query = query.filter(Responsable.is_mapped.is_(False))
    return query.order_by(Responsable.display_name).all()


@router.get("/responsables/{responsable_id}", response_model=ResponsableOut)
def get_responsable(responsable_id: uuid.UUID, db: Session = Depends(get_db)):
    responsable = db.query(Responsable).filter(Responsable.id == responsable_id).first()
    if not responsable:
        raise HTTPException(status_code=404, detail="Responsable introuvable")
    return responsable


@router.post("/responsables", response_model=ResponsableOut, status_code=201)
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


@router.patch("/responsables/{responsable_id}", response_model=ResponsableOut)
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


@router.delete("/responsables/{responsable_id}", status_code=204)
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

@router.get("/sync-logs")
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


@router.get("/relance-logs")
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
