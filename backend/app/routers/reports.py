"""
Rapports consolidés : portefeuille, projet, charge par responsable, prévision.

Chaque rapport est calculé en une requête agrégée plutôt qu'en bouclant sur
les projets ou les responsables. Un rapport portefeuille écrit naïvement
enchaîne dix `COUNT` par projet : sur les vingt projets suivis par la DSI cela
fait deux cents allers-retours vers Supabase pour afficher un seul écran.
Les agrégats `COUNT(*) FILTER (WHERE …)` de PostgreSQL font le même travail
en une passe.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_async_db
from app.models.project import (
    Action,
    ActionStatus,
    Project,
    RelanceLog,
    Responsable,
    action_responsables,
)
from app.schemas.report_schema import (
    ActionSummaryOut,
    ForecastReportOut,
    PortfolioReportOut,
    ProjectReportOut,
    ResponsableReportOut,
    WeekBucketOut,
    WorkloadReportOut,
)
from app.services.action_queries import (
    ActionView,
    build_actions_query,
    default_order,
    is_due_soon,
    is_overdue,
    week_bounds,
)
from app.services.action_rules import today_utc
from app.services.digests import to_digest
from app.services.security import require_reader

router = APIRouter(prefix="/reports", tags=["reports"])

AUTH_RESPONSES = {
    401: {"description": "Jeton absent, invalide ou expiré."},
    403: {"description": "Rôle insuffisant pour cette opération."},
}

_MOIS_FR = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]


def _pct(numerateur: float, denominateur: float) -> float:
    return round(numerateur / denominateur * 100, 1) if denominateur else 0.0


def _sante(overdue: int, blocked: int, ouvertes: int) -> str:
    if overdue == 0 and blocked == 0:
        return "ok"
    if _pct(overdue, ouvertes) > 20:
        return "critique"
    return "attention"


def _colonnes_agregees(today, horizon_jours: int):
    """Compteurs par projet, calculés côté PostgreSQL."""
    ouverte = and_(Action.status != ActionStatus.TERMINE, Action.progress < 100.0)
    terminee = or_(Action.status == ActionStatus.TERMINE, Action.progress >= 100.0)
    return [
        func.count().label("total"),
        func.count().filter(terminee).label("done"),
        func.count().filter(ouverte).label("open"),
        func.count().filter(is_overdue(today)).label("overdue"),
        func.count().filter(Action.status == ActionStatus.BLOQUE).label("blocked"),
        func.count().filter(is_due_soon(horizon_jours, today)).label("due_soon"),
        func.count().filter(and_(~Action.responsables.any(), ouverte)).label("unassigned"),
        func.count().filter(and_(Action.deadline.is_(None), ouverte)).label("no_deadline"),
        func.coalesce(func.avg(Action.progress), 0.0).label("progress_avg"),
        func.coalesce(func.avg(Action.spi), 0.0).label("spi_avg"),
        func.coalesce(func.avg(Action.otd), 0.0).label("otd_avg"),
        func.coalesce(func.sum(Action.charges_hj), 0.0).label("charges_hj_total"),
    ]


def _projet_vers_rapport(projet: Project, ligne) -> ProjectReportOut:
    total = int(ligne.total or 0) if ligne else 0
    ouvertes = int(ligne.open or 0) if ligne else 0
    en_retard = int(ligne.overdue or 0) if ligne else 0
    bloquees = int(ligne.blocked or 0) if ligne else 0
    return ProjectReportOut(
        project_id=projet.id,
        code=projet.code,
        name=projet.name,
        is_active=projet.is_active,
        last_synced_at=projet.last_synced_at,
        total_actions=total,
        done=int(ligne.done or 0) if ligne else 0,
        open=ouvertes,
        overdue=en_retard,
        blocked=bloquees,
        due_soon=int(ligne.due_soon or 0) if ligne else 0,
        unassigned=int(ligne.unassigned or 0) if ligne else 0,
        no_deadline=int(ligne.no_deadline or 0) if ligne else 0,
        progress_avg=round(float(ligne.progress_avg or 0.0), 1) if ligne else 0.0,
        completion_rate=_pct(int(ligne.done or 0) if ligne else 0, total),
        overdue_rate=_pct(en_retard, ouvertes),
        spi_avg=round(float(ligne.spi_avg or 0.0), 1) if ligne else 0.0,
        otd_avg=round(float(ligne.otd_avg or 0.0), 1) if ligne else 0.0,
        charges_hj_total=round(float(ligne.charges_hj_total or 0.0), 2) if ligne else 0.0,
        health=_sante(en_retard, bloquees, ouvertes),
    )


async def _totaux(db: AsyncSession, actifs_seulement: bool) -> ActionSummaryOut:
    compteurs: dict[str, int] = {}
    for vue in ActionView:
        stmt = build_actions_query(
            view=vue,
            active_projects_only=actifs_seulement,
            due_soon_days=settings.relance_horizon_days,
        )
        sous_requete = stmt.order_by(None).subquery()
        result = await db.execute(select(func.count()).select_from(sous_requete))
        compteurs[vue.value] = int(result.scalar_one())

    ouvertes = compteurs[ActionView.OPEN.value]
    return ActionSummaryOut(
        generated_at=datetime.now(timezone.utc),
        counts=compteurs,
        overdue_ratio=_pct(compteurs[ActionView.OVERDUE.value], ouvertes),
    )


@router.get(
    "/portfolio",
    response_model=PortfolioReportOut,
    dependencies=[require_reader],
    summary="Rapport portefeuille",
    description=(
        "Indicateurs consolidés de tous les projets : volumétrie, avancement "
        "moyen, taux de retard, SPI et OTD moyens, charges cumulées, et une "
        "synthèse `health` par projet (`ok`, `attention`, `critique`).\n\n"
        "Par défaut seuls les projets actifs sont pris en compte — un projet "
        "archivé fausserait les moyennes avec des retards qui ne sont plus "
        "d'actualité."
    ),
    response_description="Le rapport portefeuille.",
    responses=AUTH_RESPONSES,
)
async def portfolio_report(
    scope: str = Query("active", pattern="^(active|all)$", description="`active` ou `all`."),
    db: AsyncSession = Depends(get_async_db),
):
    today = today_utc()
    actifs_seulement = scope == "active"

    stmt_projets = select(Project)
    if actifs_seulement:
        stmt_projets = stmt_projets.filter(Project.is_active.is_(True))
    projets = list((await db.execute(stmt_projets.order_by(Project.code))).scalars().all())

    # Une seule requête agrégée pour tous les projets.
    stmt_aggr = (
        select(Action.project_id, *_colonnes_agregees(today, settings.relance_horizon_days))
        .group_by(Action.project_id)
    )
    lignes = {row.project_id: row for row in (await db.execute(stmt_aggr)).all()}

    return PortfolioReportOut(
        generated_at=datetime.now(timezone.utc),
        scope=scope,
        project_count=len(projets),
        totals=await _totaux(db, actifs_seulement),
        projects=[_projet_vers_rapport(p, lignes.get(p.id)) for p in projets],
    )


@router.get(
    "/projects/{project_id}",
    response_model=ProjectReportOut,
    dependencies=[require_reader],
    summary="Rapport d'un projet",
    description="Mêmes indicateurs que le rapport portefeuille, pour un seul projet.",
    responses={**AUTH_RESPONSES, 404: {"description": "Aucun projet avec cet identifiant."}},
)
async def project_report(
    project_id: uuid.UUID = Path(..., description="Identifiant unique (UUID) du projet."),
    db: AsyncSession = Depends(get_async_db),
):
    result = await db.execute(select(Project).filter(Project.id == project_id))
    projet = result.scalars().first()
    if not projet:
        raise HTTPException(status_code=404, detail="Projet introuvable")

    stmt = (
        select(Action.project_id, *_colonnes_agregees(today_utc(), settings.relance_horizon_days))
        .filter(Action.project_id == project_id)
        .group_by(Action.project_id)
    )
    ligne = (await db.execute(stmt)).first()
    return _projet_vers_rapport(projet, ligne)


@router.get(
    "/workload",
    response_model=WorkloadReportOut,
    dependencies=[require_reader],
    summary="Charge par responsable",
    description=(
        "Répartition des actions entre responsables : volume, retards, "
        "prochaine échéance et date de la dernière relance reçue.\n\n"
        "Le champ `unassigned_actions` compte les actions ouvertes que "
        "personne ne porte : elles n'apparaissent dans aucune ligne du tableau "
        "et ne déclenchent aucune relance — ce sont celles qui se perdent."
    ),
    responses=AUTH_RESPONSES,
)
async def workload_report(
    active_projects_only: bool = Query(True, description="Ignorer les projets archivés."),
    db: AsyncSession = Depends(get_async_db),
):
    today = today_utc()
    ouverte = and_(Action.status != ActionStatus.TERMINE, Action.progress < 100.0)
    terminee = or_(Action.status == ActionStatus.TERMINE, Action.progress >= 100.0)

    projets_retenus = select(Project.id)
    if active_projects_only:
        projets_retenus = projets_retenus.where(Project.is_active.is_(True))

    # Dernière relance : sous-requête corrélée, pour éviter une seconde passe
    # applicative sur la table des journaux.
    derniere_relance = (
        select(func.max(RelanceLog.sent_at))
        .where(RelanceLog.responsable_id == Responsable.id)
        .correlate(Responsable)
        .scalar_subquery()
    )

    stmt = (
        select(
            Responsable.id,
            Responsable.display_name,
            Responsable.email,
            Responsable.is_mapped,
            func.count(Action.id).label("total"),
            func.count(Action.id).filter(ouverte).label("open"),
            func.count(Action.id).filter(is_overdue(today)).label("overdue"),
            func.count(Action.id)
            .filter(is_due_soon(settings.relance_horizon_days, today))
            .label("due_soon"),
            func.count(Action.id).filter(Action.status == ActionStatus.BLOQUE).label("blocked"),
            func.count(Action.id).filter(terminee).label("done"),
            func.coalesce(func.avg(Action.progress), 0.0).label("progress_avg"),
            func.min(Action.deadline).filter(ouverte).label("next_deadline"),
            derniere_relance.label("last_relance_at"),
        )
        .outerjoin(action_responsables, action_responsables.c.responsable_id == Responsable.id)
        .outerjoin(
            Action,
            and_(
                Action.id == action_responsables.c.action_id,
                Action.project_id.in_(projets_retenus),
            ),
        )
        .group_by(Responsable.id, Responsable.display_name, Responsable.email, Responsable.is_mapped)
        .order_by(func.count(Action.id).filter(is_overdue(today)).desc(), Responsable.display_name)
    )

    lignes = (await db.execute(stmt)).all()

    non_assignees = await db.execute(
        select(func.count()).select_from(
            build_actions_query(
                view=ActionView.UNASSIGNED, active_projects_only=active_projects_only
            )
            .order_by(None)
            .subquery()
        )
    )

    return WorkloadReportOut(
        generated_at=datetime.now(timezone.utc),
        responsable_count=len(lignes),
        unassigned_actions=int(non_assignees.scalar_one()),
        responsables=[
            ResponsableReportOut(
                responsable_id=ligne.id,
                display_name=ligne.display_name,
                email=ligne.email,
                is_mapped=ligne.is_mapped,
                total_actions=int(ligne.total or 0),
                open=int(ligne.open or 0),
                overdue=int(ligne.overdue or 0),
                due_soon=int(ligne.due_soon or 0),
                blocked=int(ligne.blocked or 0),
                done=int(ligne.done or 0),
                progress_avg=round(float(ligne.progress_avg or 0.0), 1),
                overdue_rate=_pct(int(ligne.overdue or 0), int(ligne.open or 0)),
                next_deadline=ligne.next_deadline,
                last_relance_at=ligne.last_relance_at,
            )
            for ligne in lignes
        ],
    )


@router.get(
    "/forecast",
    response_model=ForecastReportOut,
    dependencies=[require_reader],
    summary="Prévision des échéances, semaine par semaine",
    description=(
        "Découpe les échéances à venir en créneaux hebdomadaires (du lundi au "
        "dimanche) avec le nombre d'actions et les charges cumulées de chaque "
        "semaine — le plan de charge à venir.\n\n"
        "`overdue_backlog` rappelle les actions déjà en retard : elles "
        "n'apparaissent dans aucun créneau alors qu'elles consommeront bien de "
        "la capacité, et une prévision qui les ignore est systématiquement "
        "optimiste."
    ),
    responses=AUTH_RESPONSES,
)
async def forecast_report(
    weeks: int = Query(4, ge=1, le=26, description="Nombre de semaines à projeter."),
    start_offset: int = Query(0, ge=0, le=52, description="0 = à partir de la semaine courante."),
    include_actions: bool = Query(
        True, description="Inclure le détail des actions de chaque semaine."
    ),
    active_projects_only: bool = Query(True, description="Ignorer les projets archivés."),
    db: AsyncSession = Depends(get_async_db),
):
    today = today_utc()
    premier_lundi, _ = week_bounds(start_offset, today)
    _, dernier_dimanche = week_bounds(start_offset + weeks - 1, today)

    stmt = build_actions_query(
        view=ActionView.OPEN, active_projects_only=active_projects_only
    ).where(Action.deadline >= premier_lundi, Action.deadline <= dernier_dimanche)
    stmt = default_order(stmt).options(
        selectinload(Action.responsables), selectinload(Action.project)
    )
    actions = list((await db.execute(stmt)).scalars().unique().all())

    creneaux: list[WeekBucketOut] = []
    for decalage in range(start_offset, start_offset + weeks):
        debut, fin = week_bounds(decalage, today)
        de_la_semaine = [a for a in actions if debut <= a.deadline <= fin]
        creneaux.append(
            WeekBucketOut(
                week_start=debut,
                week_end=fin,
                label=f"semaine du {debut.day} {_MOIS_FR[debut.month - 1]}",
                action_count=len(de_la_semaine),
                charges_hj=round(sum(a.charges_hj or 0.0 for a in de_la_semaine), 2),
                actions=[to_digest(a, today) for a in de_la_semaine] if include_actions else [],
            )
        )

    retard = await db.execute(
        select(func.count()).select_from(
            build_actions_query(
                view=ActionView.OVERDUE, active_projects_only=active_projects_only
            )
            .order_by(None)
            .subquery()
        )
    )

    return ForecastReportOut(
        generated_at=datetime.now(timezone.utc),
        weeks=creneaux,
        overdue_backlog=int(retard.scalar_one()),
    )
