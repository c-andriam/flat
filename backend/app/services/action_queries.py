"""
Vues métier sur les actions — une seule définition par notion.

« En retard », « échéance proche », « à venir » sont utilisés à trois endroits :
les routes de consultation, le moteur de relance et les rapports. Les définir
en un seul endroit garantit qu'un mail de relance et le tableau de bord
comptent exactement les mêmes actions — sans quoi un responsable reçoit un
rappel pour une action que l'interface lui affiche comme dans les temps.

Chaque fonction renvoie un `Select` SQLAlchemy que l'appelant complète
(tri, pagination, chargement des relations). Aucun filtrage en Python : tout
reste dans la requête, y compris quand le portefeuille grossit.
"""

from datetime import date, timedelta
from enum import Enum

from sqlalchemy import Select, and_, or_, select

from app.models.project import Action, ActionStatus, Project, Responsable
from app.services.action_rules import today_utc


class ActionView(str, Enum):
    """Vues prédéfinies, exposées telles quelles dans l'API et les rapports."""

    ALL = "all"
    OPEN = "open"
    OVERDUE = "overdue"
    TODAY = "today"
    DUE_SOON = "due_soon"
    UPCOMING = "upcoming"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    DONE = "done"
    UNASSIGNED = "unassigned"
    NO_DEADLINE = "no_deadline"


#: Libellés destinés aux emails et aux rapports.
VIEW_LABELS: dict[ActionView, str] = {
    ActionView.ALL: "Toutes les actions",
    ActionView.OPEN: "Actions ouvertes",
    ActionView.OVERDUE: "Actions en retard",
    ActionView.TODAY: "Actions à échéance aujourd'hui",
    ActionView.DUE_SOON: "Actions dont l'échéance approche",
    ActionView.UPCOMING: "Actions à venir",
    ActionView.IN_PROGRESS: "Actions en cours",
    ActionView.BLOCKED: "Actions bloquées",
    ActionView.DONE: "Actions terminées",
    ActionView.UNASSIGNED: "Actions sans responsable",
    ActionView.NO_DEADLINE: "Actions sans échéance",
}


# ---------------------------------------------------------------------------
# Prédicats élémentaires
# ---------------------------------------------------------------------------

def _open():
    """Action non terminée : le statut seul ne suffit pas.

    Une action peut afficher 100 % sans que son statut ait été rafraîchi, et
    inversement. On croise les deux pour ne jamais relancer quelqu'un sur une
    action déjà livrée.
    """
    return and_(Action.status != ActionStatus.TERMINE, Action.progress < 100.0)


def is_overdue(today: date | None = None):
    """Échéance atteinte et action non terminée.

    Le seuil est `deadline <= today`, cohérent avec `Action.is_overdue` : une
    action due aujourd'hui et non faite compte comme en retard.
    """
    today = today or today_utc()
    return and_(Action.deadline.isnot(None), Action.deadline <= today, _open())


def is_due_today(today: date | None = None):
    today = today or today_utc()
    return and_(Action.deadline == today, _open())


def is_due_soon(days: int = 3, today: date | None = None):
    """Échéance dans les `days` jours à venir, aujourd'hui exclu.

    Volontairement disjoint de `is_overdue` : une action ne doit pas apparaître
    à la fois dans la relance « en retard » et dans le rappel « échéance
    proche », sinon le responsable reçoit deux mails pour la même ligne.
    """
    today = today or today_utc()
    return and_(
        Action.deadline > today,
        Action.deadline <= today + timedelta(days=days),
        _open(),
    )


def week_bounds(weeks_ahead: int = 1, today: date | None = None) -> tuple[date, date]:
    """Lundi et dimanche de la semaine décalée de `weeks_ahead`.

    `weeks_ahead=0` renvoie la semaine courante, `1` la semaine prochaine.
    """
    today = today or today_utc()
    monday = today - timedelta(days=today.weekday()) + timedelta(weeks=weeks_ahead)
    return monday, monday + timedelta(days=6)


def is_upcoming(weeks_ahead: int = 1, today: date | None = None):
    """Actions dont l'échéance tombe dans la semaine visée."""
    start, end = week_bounds(weeks_ahead, today)
    return and_(Action.deadline >= start, Action.deadline <= end, _open())


# ---------------------------------------------------------------------------
# Construction de la requête
# ---------------------------------------------------------------------------

def _view_condition(view: ActionView, today: date, days: int, weeks_ahead: int):
    if view is ActionView.OPEN:
        return _open()
    if view is ActionView.OVERDUE:
        return is_overdue(today)
    if view is ActionView.TODAY:
        return is_due_today(today)
    if view is ActionView.DUE_SOON:
        return is_due_soon(days, today)
    if view is ActionView.UPCOMING:
        return is_upcoming(weeks_ahead, today)
    if view is ActionView.IN_PROGRESS:
        return and_(Action.status == ActionStatus.EN_COURS, _open())
    if view is ActionView.BLOCKED:
        return Action.status == ActionStatus.BLOQUE
    if view is ActionView.DONE:
        return or_(Action.status == ActionStatus.TERMINE, Action.progress >= 100.0)
    if view is ActionView.UNASSIGNED:
        return and_(~Action.responsables.any(), _open())
    if view is ActionView.NO_DEADLINE:
        return and_(Action.deadline.is_(None), _open())
    return None  # ActionView.ALL


def build_actions_query(
    *,
    view: ActionView = ActionView.ALL,
    project_id=None,
    responsable_id=None,
    responsable_name: str | None = None,
    status: ActionStatus | None = None,
    search: str | None = None,
    active_projects_only: bool = False,
    due_soon_days: int = 3,
    weeks_ahead: int = 1,
    today: date | None = None,
) -> Select:
    """Requête `Select(Action)` correspondant aux filtres demandés."""
    today = today or today_utc()
    stmt = select(Action)

    condition = _view_condition(view, today, due_soon_days, weeks_ahead)
    if condition is not None:
        stmt = stmt.where(condition)

    if project_id is not None:
        stmt = stmt.where(Action.project_id == project_id)

    if active_projects_only:
        # Un projet archivé ne doit plus peser dans les tableaux de bord ni
        # déclencher de relance.
        stmt = stmt.where(
            Action.project_id.in_(select(Project.id).where(Project.is_active.is_(True)))
        )

    # `any()` produit un EXISTS : un JOIN dupliquerait la ligne action une fois
    # par responsable et fausserait à la fois le LIMIT et les totaux.
    if responsable_id is not None:
        stmt = stmt.where(Action.responsables.any(Responsable.id == responsable_id))
    if responsable_name is not None:
        stmt = stmt.where(
            Action.responsables.any(Responsable.display_name == responsable_name)
        )

    if status is not None:
        stmt = stmt.where(Action.status == status)

    if search:
        motif = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                Action.description.ilike(motif),
                Action.numero.ilike(motif),
                Action.commentaire.ilike(motif),
            )
        )

    return stmt


def default_order(stmt: Select) -> Select:
    """Tri par urgence : échéance croissante, sans échéance en dernier."""
    return stmt.order_by(Action.deadline.nulls_last(), Action.numero)
