import uuid
from datetime import datetime, timezone

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
    ActionReplace,
    ActionUpdate,
    ProjectCreate,
    ProjectOut,
    ProjectReplace,
    ProjectUpdate,
    ProjectWithActionsOut,
    RelanceLogOut,
    ResponsableCreate,
    ResponsableOut,
    ResponsableReplace,
    ResponsableUpdate,
    SyncLogOut,
)
from app.schemas.report_schema import ActionSummaryOut
from app.services.action_queries import (
    ActionView,
    build_actions_query,
    default_order,
)
from app.services.action_rules import apply_status, compute_status, today_utc
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
# PATCH et PUT
#
# HTTP ne définit pas de verbe « UPDATE » : la modification s'exprime avec
# PATCH (partiel) ou PUT (remplacement complet). Les deux sont exposés côté
# à côté, sur les mêmes règles métier :
#
#   PATCH  n'applique que les champs présents dans la charge utile — un seul
#          champ comme dix. Un champ absent n'est pas touché.
#   PUT    remplace la ressource entière : un champ modifiable absent est
#          remis à sa valeur vide, il n'est pas conservé.
#
# En faire des alias l'un de l'autre serait le piège classique : un client qui
# envoie un PUT partiel effacerait des données sans s'en rendre compte, ou au
# contraire croirait avoir réinitialisé un champ qui resterait renseigné.
# ---------------------------------------------------------------------------

async def _verifier_bascule_phases(db: AsyncSession, project: Project, nouveau: bool | None) -> None:
    """Refuse de basculer `has_phases` sur un projet qui porte des actions.

    Le numéro d'action encode la phase (`P01-02-05`) : changer le mode après
    coup désynchroniserait toute la numérotation existante.
    """
    if nouveau is None or nouveau == project.has_phases:
        return
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


async def _sync_action_responsables(db: AsyncSession, action: Action, noms: list[str]) -> None:
    """Aligne les responsables d'une action sur la liste fournie.

    Les noms inconnus sont créés en `is_mapped=False`, à associer ensuite à un
    email. On ne vide pas la collection pour la reconstruire : un DELETE +
    INSERT complet à chaque enregistrement est inutilement coûteux et bruyant
    quand rien n'a changé.
    """
    voulus: list[str] = []
    for nom in noms:
        nom = (nom or "").strip()
        if nom and nom not in voulus:
            voulus.append(nom)

    courants = {r.display_name: r for r in action.responsables}
    for nom, responsable in courants.items():
        if nom not in voulus:
            action.responsables.remove(responsable)

    for nom in voulus:
        if nom in courants:
            continue
        result = await db.execute(
            select(Responsable).filter(Responsable.display_name == nom)
        )
        responsable = result.scalars().first()
        if responsable is None:
            responsable = Responsable(display_name=nom, is_mapped=False)
            db.add(responsable)
        action.responsables.append(responsable)


def _valider_phase(project: Project, phase: str | None) -> str | None:
    """Cohérence entre la phase fournie et le mode du projet."""
    if project.has_phases and not phase:
        raise HTTPException(
            status_code=422,
            detail=(
                "Ce projet utilise les phases (has_phases=True) : le champ "
                "'phase' est obligatoire."
            ),
        )
    if not project.has_phases and phase:
        raise HTTPException(
            status_code=422,
            detail=(
                "Ce projet n'utilise pas les phases (has_phases=False) : le "
                "champ 'phase' doit rester vide."
            ),
        )
    return phase if project.has_phases else None


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

    await _verifier_bascule_phases(db, project, update_data.get("has_phases"))

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


@router.put(
    "/projects/{project_id}",
    response_model=ProjectOut,
    dependencies=[require_writer],
    tags=["projects"],
    summary="Remplacer un projet",
    description=(
        "Remplacement complet : tous les champs modifiables doivent être "
        "fournis, et ceux qui ne le sont pas reprennent leur valeur par "
        "défaut. Pour ne modifier qu'un ou deux champs, utiliser `PATCH` sur "
        "la même URL."
    ),
    response_description="Le projet remplacé.",
    responses={
        **AUTH_RESPONSES,
        404: {"description": "Aucun projet avec cet identifiant."},
        409: {"description": "Code déjà pris, ou bascule de `has_phases` interdite."},
    },
)
async def replace_project(
    payload: ProjectReplace,
    project_id: uuid.UUID = Path(..., description="Identifiant unique (UUID) du projet."),
    db: AsyncSession = Depends(get_async_db),
):
    result = await db.execute(select(Project).filter(Project.id == project_id))
    project = result.scalars().first()
    if not project:
        raise HTTPException(status_code=404, detail="Projet introuvable")

    await _verifier_bascule_phases(db, project, payload.has_phases)

    for field, value in payload.model_dump().items():
        setattr(project, field, value)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Conflit lors du remplacement (ex: code déjà utilisé)",
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

# Paramètres partagés par toutes les vues d'actions.
_DUE_SOON_PARAM = Query(
    3, ge=1, le=90,
    description="Horizon en jours de la vue « échéance proche ».",
)
_WEEKS_AHEAD_PARAM = Query(
    1, ge=0, le=52,
    description=(
        "Décalage en semaines de la vue « à venir » : 0 = semaine courante, "
        "1 = semaine prochaine, 2 = la suivante."
    ),
)


async def _run_actions_query(db: AsyncSession, response: Response, stmt, limit: int, offset: int):
    """Compte, trie, pagine et charge les responsables en une seule fois."""
    response.headers["X-Total-Count"] = str(await _count(db, stmt))
    stmt = default_order(stmt).options(selectinload(Action.responsables))
    result = await db.execute(stmt.limit(limit).offset(offset))
    return result.scalars().unique().all()


@router.get(
    "/actions",
    response_model=list[ActionOut],
    dependencies=[require_reader],
    tags=["actions"],
    summary="Lister les actions",
    description=(
        "Vue synthétique des actions. Le paramètre `view` applique une des "
        "vues métier prédéfinies — les mêmes que celles utilisées par les "
        "relances et les rapports, afin qu'un mail et un tableau de bord ne "
        "puissent jamais compter des actions différentes :\n\n"
        "- `open` : non terminées ;\n"
        "- `overdue` : échéance atteinte et non terminées ;\n"
        "- `today` : à rendre aujourd'hui ;\n"
        "- `due_soon` : échéance dans les `due_soon_days` jours (aujourd'hui exclu) ;\n"
        "- `upcoming` : échéance dans la semaine décalée de `weeks_ahead` ;\n"
        "- `in_progress`, `blocked`, `done`, `unassigned`, `no_deadline`.\n\n"
        "Les filtres se cumulent, et le total avant pagination est renvoyé "
        "dans l'en-tête `X-Total-Count`. Chaque vue dispose aussi d'une route "
        "raccourcie (`/actions/overdue`, `/actions/upcoming`, …)."
    ),
    response_description="Liste des actions correspondant aux filtres.",
    responses=AUTH_RESPONSES,
)
async def list_actions(
    response: Response,
    view: ActionView = Query(ActionView.ALL, description="Vue métier à appliquer."),
    project_id: uuid.UUID | None = Query(None, description="Filtrer par identifiant de projet."),
    responsable_id: uuid.UUID | None = Query(None, description="Filtrer par identifiant de responsable."),
    responsable: str | None = Query(None, description="Filtrer par nom affiché du responsable."),
    status: ActionStatus | None = Query(None, description="Filtrer par statut."),
    search: str | None = Query(None, min_length=1, max_length=200, description="Recherche dans le numéro, la description et le commentaire."),
    active_projects_only: bool = Query(False, description="Ignorer les actions des projets archivés."),
    overdue_only: bool = Query(False, description="Raccourci historique équivalent à `view=overdue`."),
    due_soon_days: int = _DUE_SOON_PARAM,
    weeks_ahead: int = _WEEKS_AHEAD_PARAM,
    limit: int = _limit_param(),
    offset: int = _OFFSET_PARAM,
    db: AsyncSession = Depends(get_async_db),
):
    # `overdue_only` est conservé pour ne pas casser les clients écrits avant
    # l'arrivée de `view`.
    if overdue_only and view is ActionView.ALL:
        view = ActionView.OVERDUE

    stmt = build_actions_query(
        view=view,
        project_id=project_id,
        responsable_id=responsable_id,
        responsable_name=responsable,
        status=status,
        search=search,
        active_projects_only=active_projects_only,
        due_soon_days=due_soon_days,
        weeks_ahead=weeks_ahead,
    )
    return await _run_actions_query(db, response, stmt, limit, offset)


@router.get(
    "/actions/summary",
    response_model=ActionSummaryOut,
    dependencies=[require_reader],
    tags=["actions"],
    summary="Compteurs par vue (tableau de bord)",
    description=(
        "Renvoie en une requête le nombre d'actions de chaque vue. Destiné "
        "aux bandeaux de tête d'écran : sans lui, un tableau de bord devrait "
        "enchaîner dix appels pour afficher dix compteurs."
    ),
    response_description="Compteurs par vue.",
    responses=AUTH_RESPONSES,
)
async def actions_summary(
    project_id: uuid.UUID | None = Query(None, description="Restreindre à un projet."),
    responsable_id: uuid.UUID | None = Query(None, description="Restreindre à un responsable."),
    active_projects_only: bool = Query(True, description="Ignorer les projets archivés."),
    due_soon_days: int = _DUE_SOON_PARAM,
    weeks_ahead: int = _WEEKS_AHEAD_PARAM,
    db: AsyncSession = Depends(get_async_db),
):
    compteurs: dict[str, int] = {}
    for vue in ActionView:
        stmt = build_actions_query(
            view=vue,
            project_id=project_id,
            responsable_id=responsable_id,
            active_projects_only=active_projects_only,
            due_soon_days=due_soon_days,
            weeks_ahead=weeks_ahead,
        )
        compteurs[vue.value] = await _count(db, stmt)

    ouvertes = compteurs[ActionView.OPEN.value]
    en_retard = compteurs[ActionView.OVERDUE.value]
    return ActionSummaryOut(
        generated_at=datetime.now(timezone.utc),
        counts=compteurs,
        # Part des actions ouvertes qui sont en retard : l'indicateur que
        # regarde un chef de projet avant tout le reste.
        overdue_ratio=round(en_retard / ouvertes * 100, 1) if ouvertes else 0.0,
    )


def _enregistrer_vue(chemin: str, vue: ActionView, resume: str, details: str) -> None:
    """Déclare une route raccourcie pour une vue métier.

    Ces routes doivent être déclarées AVANT `/actions/{action_id}` : FastAPI
    résout dans l'ordre de déclaration, et `/actions/overdue` serait sinon
    capté par la route paramétrée puis rejeté comme UUID invalide.
    """

    @router.get(
        f"/actions/{chemin}",
        response_model=list[ActionOut],
        dependencies=[require_reader],
        tags=["actions"],
        summary=resume,
        description=details,
        response_description="Liste des actions de cette vue.",
        responses=AUTH_RESPONSES,
        name=f"list_actions_{vue.value}",
    )
    async def _route(
        response: Response,
        project_id: uuid.UUID | None = Query(None, description="Restreindre à un projet."),
        responsable_id: uuid.UUID | None = Query(None, description="Restreindre à un responsable."),
        active_projects_only: bool = Query(True, description="Ignorer les projets archivés."),
        due_soon_days: int = _DUE_SOON_PARAM,
        weeks_ahead: int = _WEEKS_AHEAD_PARAM,
        limit: int = _limit_param(),
        offset: int = _OFFSET_PARAM,
        db: AsyncSession = Depends(get_async_db),
        _vue: ActionView = vue,
    ):
        stmt = build_actions_query(
            view=_vue,
            project_id=project_id,
            responsable_id=responsable_id,
            active_projects_only=active_projects_only,
            due_soon_days=due_soon_days,
            weeks_ahead=weeks_ahead,
        )
        return await _run_actions_query(db, response, stmt, limit, offset)


_VUES_RACCOURCIES = [
    ("open", ActionView.OPEN, "Actions ouvertes",
     "Toutes les actions non terminées, tous projets actifs confondus."),
    ("overdue", ActionView.OVERDUE, "Actions en retard",
     "Échéance atteinte ou dépassée et avancement inférieur à 100 %."),
    ("today", ActionView.TODAY, "Actions à rendre aujourd'hui",
     "Échéance au jour même — la liste du rappel « jour J »."),
    ("due-soon", ActionView.DUE_SOON, "Actions dont l'échéance approche",
     "Échéance dans les `due_soon_days` jours à venir, aujourd'hui exclu. "
     "Volontairement disjoint de `/actions/overdue` : une action ne peut pas "
     "apparaître dans les deux, sinon son responsable reçoit deux rappels."),
    ("upcoming", ActionView.UPCOMING, "Actions de la semaine à venir",
     "Échéance comprise dans la semaine décalée de `weeks_ahead` "
     "(0 = semaine courante, 1 = semaine prochaine)."),
    ("in-progress", ActionView.IN_PROGRESS, "Actions en cours",
     "Actions dont le statut a été positionné à `en_cours`."),
    ("blocked", ActionView.BLOCKED, "Actions bloquées",
     "Actions marquées `bloque`. Ce statut est conservé tel quel par le "
     "recalcul automatique : un blocage est un constat humain, l'écraser en "
     "« en retard » ferait perdre l'information utile au pilotage."),
    ("done", ActionView.DONE, "Actions terminées",
     "Actions à 100 % ou dont le statut est `termine`."),
    ("unassigned", ActionView.UNASSIGNED, "Actions sans responsable",
     "Actions ouvertes qu'aucun responsable ne porte — typiquement une "
     "colonne D vide dans le fichier Excel source. Personne ne sera relancé "
     "dessus tant qu'elles restent dans cet état."),
    ("no-deadline", ActionView.NO_DEADLINE, "Actions sans échéance",
     "Actions ouvertes sans date cible : invisibles de tous les indicateurs "
     "de retard, donc à corriger en priorité."),
]

for _chemin, _vue, _resume, _details in _VUES_RACCOURCIES:
    _enregistrer_vue(_chemin, _vue, _resume, _details)


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

    phase = _valider_phase(project, payload.phase)
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

        await _sync_action_responsables(db, action, payload.responsable_names)

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
        new_phase = _valider_phase(project, update_data["phase"])

        if new_phase != action.phase:
            update_data["numero"] = await _generate_numero(db, project, new_phase)

    # `responsable_names` n'est pas un attribut de l'ORM : il pilote la
    # relation many-to-many et doit être traité à part.
    noms = update_data.pop("responsable_names", None)

    for field, value in update_data.items():
        setattr(action, field, value)

    if noms is not None:
        await _sync_action_responsables(db, action, noms)

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


@router.put(
    "/actions/{action_id}",
    response_model=ActionOut,
    dependencies=[require_writer],
    tags=["actions"],
    summary="Remplacer une action",
    description=(
        "Remplacement complet de l'action. Tout champ modifiable absent de la "
        "charge utile est remis à sa valeur vide — `commentaire`, "
        "`charges_hj` ou `date_realisation` omis sont effacés, et "
        "`responsable_names` remplace intégralement la liste des "
        "responsables.\n\n"
        "Omettre `status` demande son recalcul complet à partir de "
        "l'avancement et de l'échéance, sans tenir compte du statut "
        "précédent : c'est la différence avec `PATCH`, qui conserve un "
        "`en_cours` ou un `bloque` positionné à la main.\n\n"
        "`project_id` et `numero` ne sont pas modifiables : le numéro encode "
        "le code projet et la phase, déplacer une action le rendrait faux."
    ),
    response_description="L'action remplacée.",
    responses={
        **AUTH_RESPONSES,
        404: {"description": "Aucune action avec cet identifiant."},
        422: {"description": "Phase incohérente avec le mode du projet."},
        409: {"description": "Conflit de numérotation."},
    },
)
async def replace_action(
    payload: ActionReplace,
    action_id: uuid.UUID = Path(..., description="Identifiant unique (UUID) de l'action."),
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

    project = action.project
    nouvelle_phase = _valider_phase(project, payload.phase)

    donnees = payload.model_dump(exclude={"responsable_names", "phase", "status"})
    for field, value in donnees.items():
        setattr(action, field, value)

    if nouvelle_phase != action.phase:
        action.phase = nouvelle_phase
        action.numero = await _generate_numero(db, project, nouvelle_phase)

    await _sync_action_responsables(db, action, payload.responsable_names)

    if payload.status is not None:
        action.status = payload.status
    else:
        # `current=None` : le remplacement complet repart des seules données
        # fournies, il ne reconduit pas le statut manuel précédent.
        action.status = compute_status(action.progress, action.deadline, None)
    if action.status is ActionStatus.TERMINE and action.date_realisation is None:
        action.date_realisation = today_utc()

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Conflit lors du remplacement de l'action (numéro déjà utilisé ?)",
        )

    remplacee = await _load_action(db, action_id)
    await publish_event(
        "action_updated",
        {"id": remplacee.id, "numero": remplacee.numero, "status": remplacee.status},
    )
    return remplacee


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


@router.put(
    "/responsables/{responsable_id}",
    response_model=ResponsableOut,
    dependencies=[require_writer],
    tags=["responsables"],
    summary="Remplacer un responsable",
    description=(
        "Remplacement complet. Omettre `email` l'efface et repasse le "
        "responsable en non mappé — il cessera donc de recevoir les relances. "
        "Pour ne changer qu'un champ, utiliser `PATCH`."
    ),
    response_description="Le responsable remplacé.",
    responses={
        **AUTH_RESPONSES,
        404: {"description": "Aucun responsable avec cet identifiant."},
        409: {"description": "Ce nom affiché est déjà pris."},
    },
)
async def replace_responsable(
    payload: ResponsableReplace,
    responsable_id: uuid.UUID = Path(..., description="Identifiant unique (UUID) du responsable."),
    db: AsyncSession = Depends(get_async_db),
):
    result = await db.execute(select(Responsable).filter(Responsable.id == responsable_id))
    responsable = result.scalars().first()
    if not responsable:
        raise HTTPException(status_code=404, detail="Responsable introuvable")

    responsable.display_name = payload.display_name
    responsable.email = payload.email
    responsable.is_mapped = payload.email is not None

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Conflit lors du remplacement (ex: nom déjà pris)",
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
