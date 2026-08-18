"""
Règles métier partagées sur le cycle de vie d'une action.

Le calcul du statut existait en double — dans le routeur `core` et dans le
worker d'ingestion — avec deux comportements différents : le worker
rétrogradait une action en `EN_RETARD`, le routeur non. Une même action
changeait donc de statut selon qu'elle était modifiée à la main ou
resynchronisée depuis Excel.

La règle « en retard » reprend celle déjà portée par `Action.is_overdue` :
échéance atteinte (`deadline <= aujourd'hui`) et avancement < 100 %.
"""

from datetime import date, datetime, timezone

from app.models.project import Action, ActionStatus


def today_utc() -> date:
    return datetime.now(timezone.utc).date()


def compute_status(
    progress: float,
    deadline: date | None,
    current: ActionStatus | None = None,
    today: date | None = None,
) -> ActionStatus:
    """Statut dérivé de l'avancement et de l'échéance."""
    today = today or today_utc()

    if progress >= 100.0:
        return ActionStatus.TERMINE
    if current is ActionStatus.BLOQUE:
        # `BLOQUE` est un constat humain — un blocage fournisseur, une
        # validation qui n'arrive pas. Le laisser basculer en EN_RETARD ferait
        # disparaître l'information la plus utile au pilotage : *pourquoi*
        # l'action n'avance pas. Le retard reste visible par la date, que le
        # filtre `overdue` calcule sur `deadline` et non sur le statut.
        return ActionStatus.BLOQUE
    if deadline is not None and deadline <= today:
        return ActionStatus.EN_RETARD
    if current in (ActionStatus.EN_COURS, ActionStatus.A_FAIRE):
        # Statut positionné à la main : on ne l'écrase pas.
        return current
    return ActionStatus.EN_COURS if progress > 0.0 else ActionStatus.A_FAIRE


def apply_status(
    action: Action,
    today: date | None = None,
    *,
    manage_date_realisation: bool = True,
) -> None:
    """Recalcule `status` (et éventuellement `date_realisation`) en place.

    `manage_date_realisation=False` pour l'ingestion Excel : la date de
    réalisation y vient de la colonne J du fichier, qui fait autorité — la
    recalculer effacerait une donnée saisie par le chef de projet.
    """
    today = today or today_utc()
    action.status = compute_status(
        action.progress or 0.0, action.deadline, action.status, today
    )
    if not manage_date_realisation:
        return

    if action.status is ActionStatus.TERMINE:
        if action.date_realisation is None:
            action.date_realisation = today
    else:
        # Une action repassée sous les 100 % ne doit pas garder une date de
        # réalisation : les rapports la compteraient comme livrée.
        action.date_realisation = None
