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

from sqlalchemy import ColumnElement, Select, and_, func, or_, select

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
    ActionView.IN_PROGRESS: "Actions entamees",
    ActionView.BLOCKED: "Actions bloquées",
    ActionView.DONE: "Actions terminées",
    ActionView.UNASSIGNED: "Actions sans responsable",
    ActionView.NO_DEADLINE: "Actions sans échéance",
}


# ---------------------------------------------------------------------------
# Prédicats élémentaires
# ---------------------------------------------------------------------------

def is_open():
    """Action non terminée : le statut seul ne suffit pas.

    Publique parce que le moteur de relance compose ses propres sections à
    partir de ce prédicat, sans passer par une `ActionView`.

    Une action peut afficher 100 % sans que son statut ait été rafraîchi, et
    inversement. On croise les deux pour ne jamais relancer quelqu'un sur une
    action déjà livrée.
    """
    return and_(Action.status != ActionStatus.TERMINE, Action.progress < 100.0)


def is_overdue(today: date | None = None):
    """Échéance dépassée et action non terminée.

    Le retard commence le lendemain de l'échéance : livrer le jour J compte
    comme tenu — c'est déjà la règle appliquée par l'OTD, sur 108 actions de
    la base — donc ne pas avoir fini le jour J n'est pas encore un retard.
    Cette borne rend `/actions/overdue` et `/actions/today` strictement
    disjointes : chaque action ouverte à échéance datée tombe dans une seule
    des trois vues `overdue` / `today` / `due_soon`.
    """
    today = today or today_utc()
    return and_(Action.deadline.isnot(None), Action.deadline < today, is_open())


def is_due_today(today: date | None = None):
    today = today or today_utc()
    return and_(Action.deadline == today, is_open())


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
        is_open(),
    )


def is_in_progress():
    """Action entamee mais pas terminee.

    Defini sur l'avancement, pas sur le statut. Le statut est une valeur
    unique : une action a 95 % dont l'echeance est passee porte `en_retard`,
    car c'est l'information la plus urgente — elle disparaissait alors de la
    vue « en cours » alors qu'elle est bel et bien en cours. Sur le
    portefeuille, les onze actions entamees etaient toutes dans ce cas et la
    vue renvoyait une liste vide.

    Le statut `en_cours` reste pris en compte : un chef de projet peut
    declarer un travail demarre avant d'avoir chiffre son avancement.

    Cette vue recoupe volontairement `overdue` — une action peut etre entamee
    *et* en retard. Seules les trois vues de temps (`overdue`, `today`,
    `due_soon`) forment une partition.
    """
    return and_(
        or_(
            and_(Action.progress > 0.0, Action.progress < 100.0),
            Action.status == ActionStatus.EN_COURS,
        ),
        is_open(),
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
    return and_(Action.deadline >= start, Action.deadline <= end, is_open())


def is_pending(horizon_days: int = 3, today: date | None = None):
    """Action ouverte que rien ne rend urgente aujourd'hui.

    C'est le complément exact des trois fenêtres de temps : ni en retard, ni
    due aujourd'hui, ni dans l'horizon d'alerte. Soit une action sans échéance,
    soit une échéance encore lointaine.

    Le complément est calculé sur la date plutôt qu'en niant les trois
    prédicats : une négation de `AND` sur des colonnes nullables laisse passer
    les `NULL` en `UNKNOWN`, et les actions sans échéance — celles qui
    justifient précisément cette vue — disparaîtraient du résultat.
    """
    today = today or today_utc()
    return and_(
        or_(
            Action.deadline.is_(None),
            Action.deadline > today + timedelta(days=horizon_days),
        ),
        is_open(),
    )


def not_standby():
    """Action qui n'est pas mise en veille, ni elle ni son projet.

    La veille ne retire rien des tableaux de bord : elle dit seulement « ne
    relancez personne là-dessus ». Un projet suspendu accumule des retards que
    personne ne peut solder ; sans cette sortie, ils gonflent chaque rappel
    jusqu'à noyer les actions sur lesquelles quelqu'un peut réellement agir.

    Le projet est testé par sous-requête plutôt que par jointure : la même
    requête est construite par six routes, dont une qui compte via
    `COUNT(*) OVER ()`, et changer son `FROM` fausserait ce décompte.
    """
    return and_(
        Action.is_standby.is_(False),
        Action.project_id.notin_(
            select(Project.id).where(Project.is_standby.is_(True))
        ),
    )


# ---------------------------------------------------------------------------
# Construction de la requête
# ---------------------------------------------------------------------------

def _view_condition(view: ActionView, today: date, days: int, weeks_ahead: int):
    if view is ActionView.OPEN:
        return is_open()
    if view is ActionView.OVERDUE:
        return is_overdue(today)
    if view is ActionView.TODAY:
        return is_due_today(today)
    if view is ActionView.DUE_SOON:
        return is_due_soon(days, today)
    if view is ActionView.UPCOMING:
        return is_upcoming(weeks_ahead, today)
    if view is ActionView.IN_PROGRESS:
        return is_in_progress()
    if view is ActionView.BLOCKED:
        return Action.status == ActionStatus.BLOQUE
    if view is ActionView.DONE:
        return or_(Action.status == ActionStatus.TERMINE, Action.progress >= 100.0)
    if view is ActionView.UNASSIGNED:
        return and_(~Action.responsables.any(), is_open())
    if view is ActionView.NO_DEADLINE:
        return and_(Action.deadline.is_(None), is_open())
    return None  # ActionView.ALL


def count_all_views(
    *,
    project_id=None,
    responsable_id=None,
    resp_suivi_id=None,
    active_projects_only: bool = False,
    exclude_standby: bool = False,
    due_soon_days: int = 3,
    weeks_ahead: int = 1,
    extra_condition: "ColumnElement[bool] | None" = None,
    today: date | None = None,
) -> Select:
    """Compte les actions de **toutes** les vues en une seule requête.

    Onze `COUNT` séquentiels — un par vue — coûtaient onze allers-retours vers
    la base. Sur une instance distante à ~250 ms de latence, le bandeau de
    compteurs du tableau de bord mettait près de trois secondes à s'afficher
    alors que le travail SQL réel est négligeable.

    `COUNT(*) FILTER (WHERE …)` fait le même décompte en une passe sur la
    table : une requête, un aller-retour, les onze compteurs.
    """
    today = today or today_utc()

    colonnes = []
    for vue in ActionView:
        condition = _view_condition(vue, today, due_soon_days, weeks_ahead)
        compteur = func.count() if condition is None else func.count().filter(condition)
        colonnes.append(compteur.label(vue.value))

    stmt = select(*colonnes).select_from(Action)

    if project_id is not None:
        stmt = stmt.where(Action.project_id == project_id)
    if active_projects_only:
        stmt = stmt.where(
            Action.project_id.in_(select(Project.id).where(Project.is_active.is_(True)))
        )
    if responsable_id is not None:
        stmt = stmt.where(Action.responsables.any(Responsable.id == responsable_id))
    if resp_suivi_id is not None:
        stmt = stmt.where(Action.suiveurs.any(Responsable.id == resp_suivi_id))
    if exclude_standby:
        stmt = stmt.where(not_standby())
    if extra_condition is not None:
        stmt = stmt.where(extra_condition)

    return stmt


def build_actions_query(
    *,
    view: ActionView = ActionView.ALL,
    project_id=None,
    responsable_id=None,
    resp_suivi_id=None,
    responsable_name: str | None = None,
    status: ActionStatus | None = None,
    search: str | None = None,
    active_projects_only: bool = False,
    exclude_standby: bool = False,
    due_soon_days: int = 3,
    weeks_ahead: int = 1,
    extra_condition: "ColumnElement[bool] | None" = None,
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
    if resp_suivi_id is not None:
        # Colonne E. Elle passe par la table de liaison, jamais par le texte
        # brut `Action.resp_suivi` : celui-ci est composite (« Andry, Xavier »)
        # et une comparaison de chaînes y raterait une personne sur deux.
        stmt = stmt.where(Action.suiveurs.any(Responsable.id == resp_suivi_id))
    if responsable_name is not None:
        stmt = stmt.where(
            Action.responsables.any(Responsable.display_name == responsable_name)
        )

    if exclude_standby:
        stmt = stmt.where(not_standby())

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

    # Échappatoire pour les conditions que les paramètres nommés ne savent pas
    # exprimer — le périmètre « suivi *ou* réalisation » du moteur de relance,
    # qui est une disjonction et non un filtre supplémentaire.
    if extra_condition is not None:
        stmt = stmt.where(extra_condition)

    return stmt


def default_order(stmt: Select) -> Select:
    """Tri par urgence : échéance croissante, sans échéance en dernier."""
    return stmt.order_by(Action.deadline.nulls_last(), Action.numero)


# ---------------------------------------------------------------------------
# Tri demandé par l'appelant
# ---------------------------------------------------------------------------

class ActionSort(str, Enum):
    """Colonnes sur lesquelles l'API accepte de trier.

    Une énumération plutôt qu'un nom de colonne libre : le tri se termine dans
    un `ORDER BY`, et la liste fermée est ce qui garantit qu'aucune chaîne
    venue de la requête n'y arrive.
    """

    DEADLINE = "deadline"
    PROJECT = "project"
    NUMERO = "numero"
    PROGRESS = "progress"
    STATUS = "status"


class SortOrder(str, Enum):
    ASC = "asc"
    DESC = "desc"


def _project_code_expr():
    """Code du projet porteur, en sous-requête corrélée.

    Une jointure ferait le même travail, mais changerait le `FROM` d'une
    requête que six routes construisent par ailleurs — dont une qui compte via
    `COUNT(*) OVER ()`. La sous-requête laisse cette forme intacte.
    """
    return select(Project.code).where(Project.id == Action.project_id).scalar_subquery()


_SORT_EXPRESSIONS = {
    ActionSort.DEADLINE: lambda: Action.deadline,
    ActionSort.PROJECT: _project_code_expr,
    ActionSort.NUMERO: lambda: Action.numero,
    ActionSort.PROGRESS: lambda: Action.progress,
    ActionSort.STATUS: lambda: Action.status,
}


def apply_order(
    stmt: Select,
    sort: ActionSort | None = None,
    order: SortOrder = SortOrder.ASC,
) -> Select:
    """Applique le tri demandé, ou le tri par urgence par défaut.

    Un tri secondaire est toujours ajouté. Sans lui, deux actions de même
    valeur — 64 actions en retard partagent le même projet, des dizaines le
    même avancement — n'ont pas d'ordre défini : PostgreSQL est libre de les
    renvoyer différemment d'une requête à l'autre, et une pagination par
    `LIMIT/OFFSET` afficherait alors la même action sur deux pages, ou aucune.
    """
    if sort is None:
        return default_order(stmt)

    colonne = _SORT_EXPRESSIONS[sort]()
    principal = colonne.desc() if order is SortOrder.DESC else colonne.asc()

    # Les actions sans échéance restent en fin de liste dans les deux sens :
    # « sans date » n'est ni la plus urgente ni la plus lointaine.
    if sort is ActionSort.DEADLINE:
        return stmt.order_by(principal.nulls_last(), Action.numero)

    # Le numéro est déjà quasi unique ; seul le projet peut encore départager
    # deux lignes homonymes, la contrainte d'unicité portant sur le couple.
    if sort is ActionSort.NUMERO:
        return stmt.order_by(principal, Action.project_id)

    return stmt.order_by(principal, Action.deadline.nulls_last(), Action.numero)
