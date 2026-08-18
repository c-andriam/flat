import uuid

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.database import get_async_db
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
from app.services.action_rules import apply_status, today_utc
from app.services.events import publish_event
from app.services.health import perform_health_check_async
from app.services.security import require_reader, require_writer

router = APIRouter(tags=["core"])

AUTH_RESPONSES = {
    401: {"description": "Jeton absent, invalide ou expiré."},
    403: {"description": "Rôle insuffisant pour cette opération."},
}

# Limite de sécurité : sans plafond, un `GET /actions` sur un gros portefeuille
# projet ramènerait toute la table dans la réponse HTTP.
MAX_PAGE_SIZE = 1000


def _limit_param(default: int = MAX_PAGE_SIZE):
    return Query(
        default,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="Nombre maximum d'éléments retournés.",
    )


_OFFSET_PARAM = Query(0, ge=0, description="Nombre d'éléments à ignorer (pagination).")


async def _count(db: AsyncSession, stmt) -> int:
    """Total de lignes correspondant aux filtres, hors limit/offset."""
    subquery = stmt.order_by(None).limit(None).offset(None).subquery()
    result = await db.execute(select(func.count()).select_from(subquery))
    return int(result.scalar_one())


async def _load_action(db: AsyncSession, action_id: uuid.UUID) -> Action | None:
    """Recharge une action avec ses responsables.

    Indispensable après un commit : sérialiser `ActionOut.responsables` sur un
    objet dont la collection n'est pas chargée déclencherait un lazy-load hors
    contexte greenlet (MissingGreenlet) en SQLAlchemy asynchrone.
    """
    result = await db.execute(
        select(Action)
        .options(selectinload(Action.responsables))
        .filter(Action.id == action_id)
    )
    return result.scalars().first()


# ---------------------------------------------------------------------------
# Projects — CRUD complet
# ---------------------------------------------------------------------------

@router.get(
    "/projects",
    response_model=list[ProjectOut],
    dependencies=[require_reader],
    tags=["projects"],
    summary="Lister les projets",
    description=(
        "Retourne les projets suivis, triés par code projet. Le nombre total "
        "de projets correspondant aux filtres est renvoyé dans l'en-tête "
        "`X-Total-Count`."
    ),
    response_description="Liste des projets.",
    responses=AUTH_RESPONSES,
)
async def list_projects(
    response: Response,
    is_active: bool | None = Query(None, description="Filtrer sur les projets actifs/archivés."),
    limit: int = _limit_param(),
    offset: int = _OFFSET_PARAM,
    db: AsyncSession = Depends(get_async_db),
):
    stmt = select(Project)
    if is_active is not None:
        stmt = stmt.filter(Project.is_active.is_(is_active))

    response.headers["X-Total-Count"] = str(await _count(db, stmt))
    result = await db.execute(stmt.order_by(Project.code).limit(limit).offset(offset))
    return result.scalars().all()


@router.get(
    "/projects/{project_id}",
    response_model=ProjectWithActionsOut,
    dependencies=[require_reader],
    tags=["projects"],
    summary="Détail d'un projet",
    description=(
        "Retourne un projet avec l'ensemble de ses actions et, pour chaque "
        "action, ses responsables associés."
    ),
    response_description="Projet avec ses actions imbriquées.",
    responses={**AUTH_RESPONSES, 404: {"description": "Aucun projet avec cet identifiant."}},
)
async def get_project(
    project_id: uuid.UUID = Path(..., description="Identifiant unique (UUID) du projet."),
    db: AsyncSession = Depends(get_async_db),
):
    result = await db.execute(
        select(Project)
        .options(selectinload(Project.actions).selectinload(Action.responsables))
        .filter(Project.id == project_id)
    )
    project = result.scalars().first()
    if not project:
        raise HTTPException(status_code=404, detail="Projet introuvable")
    return project


@router.post(
    "/projects",
    response_model=ProjectOut,
    status_code=201,
    dependencies=[require_writer],
    tags=["projects"],
    summary="Créer un projet",
    description="Crée un nouveau projet. Le `code` projet doit être unique.",
    response_description="Le projet créé.",
    responses={**AUTH_RESPONSES, 409: {"description": "Un projet avec ce code existe déjà."}},
)
async def create_project(payload: ProjectCreate, db: AsyncSession = Depends(get_async_db)):
    project = Project(**payload.model_dump())
    db.add(project)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"Le projet '{payload.code}' existe déjà")

    await db.refresh(project)
    await publish_event(
        "project_created",
        {"id": project.id, "code": project.code, "name": project.name},
    )
    return project


@router.patch(
    "/projects/{project_id}",
    response_model=ProjectOut,
    dependencies=[require_writer],
    tags=["projects"],
    summary="Mettre à jour un projet",
    description=(
        "Mise à jour partielle (seuls les champs fournis sont modifiés). "
        "`has_phases` ne peut plus être basculé une fois que le projet porte "
        "des actions : le numéro d'action encode la phase (`P01-02-05`), le "
        "changer a posteriori désynchroniserait toute la numérotation."
    ),
    response_description="Le projet mis à jour.",
    responses={
        **AUTH_RESPONSES,
        404: {"description": "Aucun projet avec cet identifiant."},
        409: {
            "description": (
                "Conflit : code déjà pris, ou bascule de `has_phases` sur un "
                "projet qui porte déjà des actions."
            )
        },
    },
)
async def update_project(
    payload: ProjectUpdate,
    project_id: uuid.UUID = Path(..., description="Identifiant unique (UUID) du projet à modifier."),
    db: AsyncSession = Depends(get_async_db),
):
    result = await db.execute(select(Project).filter(Project.id == project_id))
    project = result.scalars().first()
    if not project:
        raise HTTPException(status_code=404, detail="Projet introuvable")

    update_data = payload.model_dump(exclude_unset=True)

    new_has_phases = update_data.get("has_phases")
    if new_has_phases is not None and new_has_phases != project.has_phases:
        existing = await db.execute(
            select(func.count()).select_from(Action).filter(Action.project_id == project.id)
        )
        if existing.scalar_one() > 0:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Impossible de modifier `has_phases` : le projet porte déjà "
                    "des actions dont le numéro encode (ou non) la phase. "
                    "Supprimer les actions ou créer un nouveau projet."
                ),
            )

    for field, value in update_data.items():
        setattr(project, field, value)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Conflit lors de la mise à jour (ex: code déjà utilisé)",
        )

    await db.refresh(project)
    await publish_event("project_updated", {"id": project.id, "code": project.code})
    return project


@router.delete(
    "/projects/{project_id}",
    status_code=204,
    dependencies=[require_writer],
    tags=["projects"],
    summary="Supprimer un projet",
    description="Supprime le projet ainsi que toutes ses actions rattachées (cascade).",
    response_description="Aucun contenu — suppression effectuée.",
    responses={**AUTH_RESPONSES, 404: {"description": "Aucun projet avec cet identifiant."}},
)
async def delete_project(
    project_id: uuid.UUID = Path(..., description="Identifiant unique (UUID) du projet à supprimer."),
    db: AsyncSession = Depends(get_async_db),
):
    result = await db.execute(select(Project).filter(Project.id == project_id))
    project = result.scalars().first()
    if not project:
        raise HTTPException(status_code=404, detail="Projet introuvable")

    await db.delete(project)  # cascade -> supprime aussi les actions liées
    await db.commit()
    await publish_event("project_deleted", {"id": project_id})


# ---------------------------------------------------------------------------
# Actions — CRUD complet
# ---------------------------------------------------------------------------

@router.get(
    "/actions",
    response_model=list[ActionOut],
    dependencies=[require_reader],
    tags=["actions"],
    summary="Lister les actions",
    description=(
        "Vue synthétique des actions, filtrable par projet, par responsable, "
        "par statut, ou uniquement les actions en retard (échéance atteinte "
        "et avancement < 100). Total dans l'en-tête `X-Total-Count`."
    ),
    response_description="Liste des actions correspondant aux filtres.",
    responses=AUTH_RESPONSES,
)
async def list_actions(
    response: Response,
    project_id: uuid.UUID | None = Query(None, description="Filtrer par identifiant de projet."),
    responsable: str | None = Query(None, description="Filtrer par nom affiché du responsable."),
    status: ActionStatus | None = Query(None, description="Filtrer par statut."),
    overdue_only: bool = Query(False, description="Ne retourner que les actions en retard."),
    limit: int = _limit_param(),
    offset: int = _OFFSET_PARAM,
    db: AsyncSession = Depends(get_async_db),
):
    stmt = select(Action).options(selectinload(Action.responsables))

    if project_id is not None:
        stmt = stmt.filter(Action.project_id == project_id)

    if responsable is not None:
        # EXISTS plutôt qu'un JOIN : un JOIN sur une relation many-to-many
        # duplique la ligne action une fois par responsable, ce qui fausse
        # à la fois le LIMIT et le total.
        stmt = stmt.filter(
            Action.responsables.any(Responsable.display_name == responsable)
        )

    if status is not None:
        stmt = stmt.filter(Action.status == status)

    if overdue_only:
        # Filtré en SQL : appliqué en Python après un LIMIT 1000, ce critère
        # ratait toutes les actions en retard au-delà du millième résultat.
        stmt = stmt.filter(
            Action.deadline.isnot(None),
            Action.deadline <= today_utc(),
            Action.progress < 100.0,
        )

    response.headers["X-Total-Count"] = str(await _count(db, stmt))
    stmt = (
        stmt.order_by(Action.deadline.nulls_last(), Action.numero)
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    return result.scalars().unique().all()


@router.get(
    "/actions/{action_id}",
    response_model=ActionOut,
    dependencies=[require_reader],
    tags=["actions"],
    summary="Détail d'une action",
    description="Retourne une action avec la liste de ses responsables.",
    response_description="L'action demandée.",
    responses={**AUTH_RESPONSES, 404: {"description": "Aucune action avec cet identifiant."}},
)
async def get_action(
    action_id: uuid.UUID = Path(..., description="Identifiant unique (UUID) de l'action."),
    db: AsyncSession = Depends(get_async_db),
):
    action = await _load_action(db, action_id)
    if not action:
        raise HTTPException(status_code=404, detail="Action introuvable")
    return action


async def _generate_numero(db: AsyncSession, project: Project, phase: str | None) -> str:
    """Prochain numéro libre pour un projet (et une phase le cas échéant)."""
    stmt = select(Action.numero).filter(Action.project_id == project.id)
    if phase is not None:
        stmt = stmt.filter(Action.phase == phase)
    else:
        stmt = stmt.filter(Action.phase.is_(None))

    result = await db.execute(stmt)
    max_num = 0
    for (numero_str,) in result.all():
        if numero_str and "-" in numero_str:
            try:
                max_num = max(max_num, int(numero_str.rsplit("-", 1)[-1]))
            except ValueError:
                continue

    if phase is not None:
        return f"{project.code}-{phase}-{max_num + 1:02d}"
    return f"{project.code}-{max_num + 1:02d}"


@router.post(
    "/actions",
    response_model=ActionOut,
    status_code=201,
    dependencies=[require_writer],
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
    responses={**AUTH_RESPONSES, 404: {"description": "Le projet référencé est introuvable."}},
)
async def create_action(payload: ActionCreate, db: AsyncSession = Depends(get_async_db)):
    result = await db.execute(select(Project).filter(Project.id == payload.project_id))
    project = result.scalars().first()
    if not project:
        raise HTTPException(status_code=404, detail="Projet introuvable")

    if project.has_phases and not payload.phase:
        raise HTTPException(
            status_code=422,
            detail=(
                "Ce projet utilise les phases (has_phases=True) : le champ "
                "'phase' est obligatoire."
            ),
        )
    if not project.has_phases and payload.phase:
        raise HTTPException(
            status_code=422,
            detail=(
                "Ce projet n'utilise pas les phases (has_phases=False) : le "
                "champ 'phase' doit rester vide."
            ),
        )

    phase = payload.phase if project.has_phases else None
    data = payload.model_dump(exclude={"responsable_names", "phase"})

    # Retry en cas de conflit sur numero (deux créations concurrentes ayant lu
    # le même max_num avant de committer). La contrainte unique en base
    # (project_id, numero) garantit qu'aucun doublon ne peut passer ; on se
    # contente ici de régénérer un numero frais et de réessayer.
    max_attempts = 5
    for attempt in range(1, max_attempts + 1):
        generated_numero = await _generate_numero(db, project, phase)
        action = Action(**data, numero=generated_numero, phase=phase)
        apply_status(action)

        for name in payload.responsable_names:
            res_result = await db.execute(
                select(Responsable).filter(Responsable.display_name == name)
            )
            responsable = res_result.scalars().first()
            if not responsable:
                responsable = Responsable(display_name=name, is_mapped=False)
                db.add(responsable)
            action.responsables.append(responsable)

        db.add(action)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            if attempt == max_attempts:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Impossible de générer un numéro d'action unique après "
                        "plusieurs tentatives, réessaie."
                    ),
                )
            continue

        created = await _load_action(db, action.id)
        await publish_event(
            "action_created",
            {
                "id": created.id,
                "numero": created.numero,
                "project_id": created.project_id,
            },
        )
        return created


@router.patch(
    "/actions/{action_id}",
    response_model=ActionOut,
    dependencies=[require_writer],
    tags=["actions"],
    summary="Mettre à jour une action",
    description=(
        "Permet de cocher/valider une action depuis le logiciel (ex: "
        "`progress`). Le statut et la date de réalisation sont recalculés "
        "automatiquement : 100 % bascule sur `TERMINE` et date le jour même, "
        "une échéance atteinte bascule sur `EN_RETARD`. Fournir `status` "
        "explicitement force la valeur."
    ),
    response_description="L'action mise à jour.",
    responses={
        **AUTH_RESPONSES,
        404: {"description": "Aucune action avec cet identifiant."},
        422: {"description": "Valeur de `status` ou de `phase` invalide."},
    },
)
async def update_action(
    payload: ActionUpdate,
    action_id: uuid.UUID = Path(..., description="Identifiant unique (UUID) de l'action à modifier."),
    db: AsyncSession = Depends(get_async_db),
):
    result = await db.execute(
        select(Action)
        .options(selectinload(Action.responsables), selectinload(Action.project))
        .filter(Action.id == action_id)
    )
    action = result.scalars().first()
    if not action:
        raise HTTPException(status_code=404, detail="Action introuvable")

    update_data = payload.model_dump(exclude_unset=True)

    if "status" in update_data:
        try:
            update_data["status"] = ActionStatus(update_data["status"])
        except ValueError:
            raise HTTPException(
                status_code=422, detail=f"Statut invalide: {update_data['status']}"
            )

    # Changer la phase doit rester cohérent avec has_phases du projet, et
    # regénérer numero (qui encode la phase, ex: P01-02-05) pour éviter
    # qu'il reste désynchronisé de la vraie phase de l'action.
    if "phase" in update_data:
        project = action.project
        new_phase = update_data["phase"]

        if project.has_phases and not new_phase:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Ce projet utilise les phases (has_phases=True) : le champ "
                    "'phase' est obligatoire."
                ),
            )
        if not project.has_phases and new_phase:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Ce projet n'utilise pas les phases (has_phases=False) : le "
                    "champ 'phase' doit rester vide."
                ),
            )

        if new_phase != action.phase:
            update_data["numero"] = await _generate_numero(db, project, new_phase)

    for field, value in update_data.items():
        setattr(action, field, value)

    # Un `status` explicite dans la charge utile fait autorité ; sinon on
    # dérive statut et date de réalisation de l'avancement et de l'échéance.
    if "status" not in update_data:
        apply_status(
            action,
            manage_date_realisation="date_realisation" not in update_data,
        )

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Conflit lors de la mise à jour de l'action (numéro déjà utilisé ?)",
        )

    updated = await _load_action(db, action_id)
    await publish_event(
        "action_updated",
        {"id": updated.id, "numero": updated.numero, "status": updated.status},
    )
    return updated


@router.delete(
    "/actions/{action_id}",
    status_code=204,
    dependencies=[require_writer],
    tags=["actions"],
    summary="Supprimer une action",
    description="Supprime définitivement une action.",
    response_description="Aucun contenu — suppression effectuée.",
    responses={**AUTH_RESPONSES, 404: {"description": "Aucune action avec cet identifiant."}},
)
async def delete_action(
    action_id: uuid.UUID = Path(..., description="Identifiant unique (UUID) de l'action à supprimer."),
    db: AsyncSession = Depends(get_async_db),
):
    result = await db.execute(select(Action).filter(Action.id == action_id))
    action = result.scalars().first()
    if not action:
        raise HTTPException(status_code=404, detail="Action introuvable")

    await db.delete(action)
    await db.commit()
    await publish_event("action_deleted", {"id": action_id})


# ---------------------------------------------------------------------------
# Responsables — CRUD complet (mapping nom Excel <-> email)
# ---------------------------------------------------------------------------

@router.get(
    "/responsables",
    response_model=list[ResponsableOut],
    dependencies=[require_reader],
    tags=["responsables"],
    summary="Lister les responsables",
    description=(
        "Retourne les responsables, avec option pour ne lister que ceux non "
        "encore mappés à un email."
    ),
    response_description="Liste des responsables.",
    responses=AUTH_RESPONSES,
)
async def list_responsables(
    response: Response,
    unmapped_only: bool = Query(False, description="Ne retourner que les responsables sans email associé."),
    limit: int = _limit_param(),
    offset: int = _OFFSET_PARAM,
    db: AsyncSession = Depends(get_async_db),
):
    stmt = select(Responsable)
    if unmapped_only:
        stmt = stmt.filter(Responsable.is_mapped.is_(False))

    response.headers["X-Total-Count"] = str(await _count(db, stmt))
    result = await db.execute(
        stmt.order_by(Responsable.display_name).limit(limit).offset(offset)
    )
    return result.scalars().all()


@router.get(
    "/responsables/{responsable_id}",
    response_model=ResponsableOut,
    dependencies=[require_reader],
    tags=["responsables"],
    summary="Détail d'un responsable",
    response_description="Le responsable demandé.",
    responses={**AUTH_RESPONSES, 404: {"description": "Aucun responsable avec cet identifiant."}},
)
async def get_responsable(
    responsable_id: uuid.UUID = Path(..., description="Identifiant unique (UUID) du responsable."),
    db: AsyncSession = Depends(get_async_db),
):
    result = await db.execute(select(Responsable).filter(Responsable.id == responsable_id))
    responsable = result.scalars().first()
    if not responsable:
        raise HTTPException(status_code=404, detail="Responsable introuvable")
    return responsable


@router.post(
    "/responsables",
    response_model=ResponsableOut,
    status_code=201,
    dependencies=[require_writer],
    tags=["responsables"],
    summary="Créer un responsable",
    description=(
        "Crée un responsable. `is_mapped` est déduit automatiquement selon la "
        "présence d'un email."
    ),
    response_description="Le responsable créé.",
    responses={**AUTH_RESPONSES, 409: {"description": "Un responsable avec ce nom affiché existe déjà."}},
)
async def create_responsable(payload: ResponsableCreate, db: AsyncSession = Depends(get_async_db)):
    responsable = Responsable(
        display_name=payload.display_name,
        email=payload.email,
        is_mapped=payload.email is not None,
    )
    db.add(responsable)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Ce responsable existe déjà")

    await db.refresh(responsable)
    await publish_event(
        "responsable_created",
        {"id": responsable.id, "display_name": responsable.display_name},
    )
    return responsable


@router.patch(
    "/responsables/{responsable_id}",
    response_model=ResponsableOut,
    dependencies=[require_writer],
    tags=["responsables"],
    summary="Associer/mettre à jour l'email d'un responsable",
    description=(
        "Renseigner `email` marque automatiquement le responsable comme mappé "
        "(`is_mapped=True`) ; envoyer `email: null` explicitement le démappe."
    ),
    response_description="Le responsable mis à jour.",
    responses={**AUTH_RESPONSES, 404: {"description": "Aucun responsable avec cet identifiant."}},
)
async def update_responsable(
    payload: ResponsableUpdate,
    responsable_id: uuid.UUID = Path(..., description="Identifiant unique (UUID) du responsable."),
    db: AsyncSession = Depends(get_async_db),
):
    result = await db.execute(select(Responsable).filter(Responsable.id == responsable_id))
    responsable = result.scalars().first()
    if not responsable:
        raise HTTPException(status_code=404, detail="Responsable introuvable")

    update_data = payload.model_dump(exclude_unset=True)
    # `exclude_unset` distingue "email non fourni" (on ne touche à rien) de
    # "email: null" (démappage explicite). Avec l'ancien `if email is not
    # None` il était impossible de retirer un email saisi par erreur.
    if "email" in update_data:
        responsable.email = update_data["email"]
        responsable.is_mapped = update_data["email"] is not None
    if update_data.get("display_name"):
        responsable.display_name = update_data["display_name"]

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Conflit lors de la mise à jour (ex: nom déjà pris)",
        )

    await db.refresh(responsable)
    await publish_event(
        "responsable_updated",
        {"id": responsable.id, "display_name": responsable.display_name},
    )
    return responsable


@router.delete(
    "/responsables/{responsable_id}",
    status_code=204,
    dependencies=[require_writer],
    tags=["responsables"],
    summary="Supprimer un responsable",
    response_description="Aucun contenu — suppression effectuée.",
    responses={**AUTH_RESPONSES, 404: {"description": "Aucun responsable avec cet identifiant."}},
)
async def delete_responsable(
    responsable_id: uuid.UUID = Path(..., description="Identifiant unique (UUID) du responsable à supprimer."),
    db: AsyncSession = Depends(get_async_db),
):
    result = await db.execute(select(Responsable).filter(Responsable.id == responsable_id))
    responsable = result.scalars().first()
    if not responsable:
        raise HTTPException(status_code=404, detail="Responsable introuvable")

    await db.delete(responsable)
    await db.commit()
    await publish_event("responsable_deleted", {"id": responsable_id})


# ---------------------------------------------------------------------------
# Logs — lecture seule (SyncLog, RelanceLog)
# Pas de create/update/delete manuel : ce sont des traces générées par le
# système (worker d'ingestion / moteur d'alertes) — un audit trail modifiable
# n'aurait plus de valeur de preuve.
# ---------------------------------------------------------------------------

@router.get(
    "/sync-logs",
    response_model=list[SyncLogOut],
    dependencies=[require_writer],
    tags=["logs"],
    summary="Historique des synchronisations Excel",
    description="Synchronisations d'import Excel, les plus récentes en premier. Lecture seule.",
    response_description="Liste des journaux de synchronisation.",
    responses=AUTH_RESPONSES,
)
async def list_sync_logs(
    limit: int = _limit_param(50),
    offset: int = _OFFSET_PARAM,
    db: AsyncSession = Depends(get_async_db),
):
    result = await db.execute(
        select(SyncLog).order_by(SyncLog.started_at.desc()).limit(limit).offset(offset)
    )
    return result.scalars().all()


@router.get(
    "/relance-logs",
    response_model=list[RelanceLogOut],
    dependencies=[require_writer],
    tags=["logs"],
    summary="Historique des relances email",
    description="Envois de relance aux responsables, les plus récents en premier. Lecture seule.",
    response_description="Liste des journaux de relance.",
    responses=AUTH_RESPONSES,
)
async def list_relance_logs(
    limit: int = _limit_param(50),
    offset: int = _OFFSET_PARAM,
    db: AsyncSession = Depends(get_async_db),
):
    result = await db.execute(
        select(RelanceLog).order_by(RelanceLog.sent_at.desc()).limit(limit).offset(offset)
    )
    return result.scalars().all()


# ---------------------------------------------------------------------------
# Monitoring — Health check API v1 (public : sondes de supervision)
# ---------------------------------------------------------------------------

@router.get(
    "/health",
    tags=["monitoring"],
    summary="Vérifier l'état du service core (API v1)",
    description=(
        "Health check accessible sur /api/v1/health. Renvoie 503 si "
        "PostgreSQL est injoignable, pour qu'un load balancer sorte "
        "l'instance du pool au lieu de continuer à lui envoyer du trafic."
    ),
    responses={503: {"description": "Base de données injoignable."}},
)
async def health_check_v1(response: Response, db: AsyncSession = Depends(get_async_db)):
    body, status_code = await perform_health_check_async(db, "core-api")
    response.status_code = status_code
    return body
