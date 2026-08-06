from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models.project import Action, ActionStatus, Project, Responsable
from app.schemas.project_schema import (
    ActionOut,
    ActionUpdate,
    ProjectCreate,
    ProjectOut,
    ProjectWithActionsOut,
    ResponsableOut,
)

router = APIRouter(tags=["core"])


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

@router.get("/projects", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db)):
    return db.query(Project).order_by(Project.code).all()


@router.get("/projects/{project_id}", response_model=ProjectWithActionsOut)
def get_project(project_id: int, db: Session = Depends(get_db)):
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


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

@router.get("/actions", response_model=list[ActionOut])
def list_actions(
    project_id: int | None = None,
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
def get_action(action_id: int, db: Session = Depends(get_db)):
    action = (
        db.query(Action)
        .options(joinedload(Action.responsables))
        .filter(Action.id == action_id)
        .first()
    )
    if not action:
        raise HTTPException(status_code=404, detail="Action introuvable")
    return action


@router.patch("/actions/{action_id}", response_model=ActionOut)
def update_action(action_id: int, payload: ActionUpdate, db: Session = Depends(get_db)):
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


# ---------------------------------------------------------------------------
# Responsables (mapping nom Excel <-> email)
# ---------------------------------------------------------------------------

@router.get("/responsables", response_model=list[ResponsableOut])
def list_responsables(unmapped_only: bool = False, db: Session = Depends(get_db)):
    query = db.query(Responsable)
    if unmapped_only:
        query = query.filter(Responsable.is_mapped.is_(False))
    return query.order_by(Responsable.display_name).all()


@router.patch("/responsables/{responsable_id}", response_model=ResponsableOut)
def map_responsable_email(responsable_id: int, email: str, db: Session = Depends(get_db)):
    responsable = db.query(Responsable).filter(Responsable.id == responsable_id).first()
    if not responsable:
        raise HTTPException(status_code=404, detail="Responsable introuvable")

    responsable.email = email
    responsable.is_mapped = True
    db.commit()
    db.refresh(responsable)
    return responsable
