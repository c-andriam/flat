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


# ---------------------------------------------------------------------------
# Indicateurs SPI et OTD
#
# Les formules sont celles que les classeurs de suivi appliquent déjà, telles
# que constatées sur les 555 actions de `07_Projets_DSIO/Projet encours` :
#
#   SPI == %Progress                              547 / 555 actions (98,6 %)
#   OTD == 100 si livrée au plus tard à l'échéance 227 / 248 actions datées
#
# Les écarts restants sont des ajustements manuels sur quelques lignes, pas
# une autre règle : les recalculer automatiquement supprime la dérive entre
# les trois KPI d'une même ligne, qui étaient jusqu'ici saisis à la main.
# ---------------------------------------------------------------------------

def compute_spi(progress: float | None) -> float:
    """Schedule Performance Index, sur une échelle 0-100.

    L'objectif d'une action est d'être à 100 % à son échéance : l'avancement
    rapporté à cet objectif *est* l'indice de performance planning. Le retard,
    lui, est porté par l'OTD — les deux indicateurs restent ainsi
    complémentaires plutôt que redondants.

    Un SPI au sens strict de l'Earned Value (valeur acquise / valeur planifiée
    à ce jour) demanderait une date de *début* planifiée, que le modèle ne
    porte pas : seule l'échéance est saisie dans les classeurs.
    """
    return round(max(0.0, min(100.0, progress or 0.0)), 2)


def compute_otd(
    progress: float | None,
    deadline: date | None,
    date_realisation: date | None,
) -> float:
    """Taux de respect de la deadline, sur une échelle 0-100.

    Binaire par action : une échéance est tenue ou elle ne l'est pas. La
    moyenne sur un projet ou un responsable redonne un pourcentage lisible,
    qui est la façon dont la colonne est utilisée dans les tableaux de bord.

    Le jour de l'échéance compte comme tenu, conformément aux fichiers
    (P01-02-04 : livrée le 05/03, échéance le 05/03, OTD 100 %).
    """
    if (progress or 0.0) < 100.0 or date_realisation is None:
        # Tant que l'action n'est pas livrée, il n'y a pas d'échéance tenue.
        return 0.0
    if deadline is None:
        # Aucune date à respecter : rien n'a été manqué.
        return 100.0
    return 100.0 if date_realisation <= deadline else 0.0


def apply_indicators(
    action: Action,
    today: date | None = None,
    *,
    manage_date_realisation: bool = True,
    recompute_spi: bool = True,
    recompute_otd: bool = True,
) -> None:
    """Recalcule statut, date de réalisation, SPI et OTD d'une action.

    L'ordre compte : le statut fixe éventuellement `date_realisation`, dont
    l'OTD dépend directement.

    `recompute_spi` / `recompute_otd` à False lorsque l'appelant fournit une
    valeur explicite — un chef de projet doit pouvoir corriger un indicateur
    à la main sans que l'enregistrement suivant l'écrase.
    """
    apply_status(action, today, manage_date_realisation=manage_date_realisation)
    if recompute_spi:
        action.spi = compute_spi(action.progress)
    if recompute_otd:
        action.otd = compute_otd(action.progress, action.deadline, action.date_realisation)
