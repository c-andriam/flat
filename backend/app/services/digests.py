"""
Conversion d'une action ORM en résumé exploitable par les emails et rapports.

Le calcul du nombre de jours restants vivait dans le worker de notification,
qui était donc le seul à savoir présenter une action. Les rapports et les
aperçus d'email en avaient besoin aussi.
"""

from datetime import date

from app.models.project import Action
from app.schemas.report_schema import ActionDigestOut
from app.services.action_rules import today_utc


def days_left(action: Action, today: date | None = None) -> int | None:
    """Jours avant l'échéance : négatif si dépassée, None sans échéance."""
    if action.deadline is None:
        return None
    return (action.deadline - (today or today_utc())).days


def to_digest(action: Action, today: date | None = None) -> ActionDigestOut:
    """Résumé d'une action.

    `action.project` et `action.responsables` doivent avoir été chargés en
    amont (`selectinload`) : y accéder ici sur une session asynchrone
    déclencherait un lazy-load hors contexte greenlet.
    """
    projet = action.project if "project" in action.__dict__ else None
    return ActionDigestOut(
        id=action.id,
        numero=action.numero,
        description=action.description,
        project_code=projet.code if projet else None,
        project_name=projet.name if projet else None,
        status=action.status,
        progress=action.progress or 0.0,
        deadline=action.deadline,
        days_left=days_left(action, today),
        resp_suivi=action.resp_suivi,
        responsables=[r.display_name for r in action.responsables],
    )


def echeance_lisible(digest: ActionDigestOut) -> str:
    """Formule l'échéance en clair : « en retard de 4 jours », « demain »…"""
    if digest.deadline is None:
        return "sans échéance"
    jours = digest.days_left
    if jours is None:
        return digest.deadline.strftime("%d/%m/%Y")
    if jours < -1:
        return f"en retard de {abs(jours)} jours"
    if jours == -1:
        return "en retard d'un jour"
    if jours == 0:
        return "aujourd'hui"
    if jours == 1:
        return "demain"
    return f"dans {jours} jours"
