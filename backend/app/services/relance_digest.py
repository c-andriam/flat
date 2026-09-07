"""
Composition du récapitulatif de relance : qui reçoit quoi, et quand.

Le moteur envoyait trois messages distincts — retard, jour J, échéance proche —
à heure fixe pour tout le monde, et toujours aux responsables de réalisation.
Trois défauts en découlaient :

  - une personne concernée par les trois natures recevait trois emails, que la
    période de silence rendait de surcroît mutuellement exclusifs — donc en
    pratique un seul, choisi par l'ordre du planificateur ;
  - le responsable de *suivi*, celui qui pilote, n'était jamais destinataire :
    la colonne E n'était qu'un texte libre, sans adresse ;
  - la cadence était la même pour un chef de projet qui suit quarante actions
    et pour un intervenant qui en porte deux.

Ce module remplace les trois envois par un récapitulatif unique, découpé en
sections disjointes, dont le contenu et la cadence sont propres à chaque
personne.

Il ne fait aucun accès à la base : il construit des `Select` que l'appelant
exécute. C'est ce qui permet au worker Celery (session synchrone) et aux
routes d'API (session asynchrone) de partager exactement la même définition —
sans elle, un aperçu à l'écran finirait par montrer autre chose que le mail
réellement parti.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum

from sqlalchemy import ColumnElement, Select, and_, or_

from app.models.project import (
    DEFAULT_HEURE_ENVOI,
    DEFAULT_JOURS_ENVOI,
    Action,
    RelancePerimetre,
    RelancePreference,
    Responsable,
    parse_jours,
)
from app.services.action_queries import (
    ActionView,
    build_actions_query,
    default_order,
    is_pending,
)
from app.services.action_rules import today_utc

#: Horizon par défaut de la section « échéance proche », en jours.
DEFAULT_HORIZON_DAYS = 3

#: Noms des jours, indexés comme `date.weekday()` (0 = lundi).
JOURS_FR = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")


class SectionKey(str, Enum):
    """Sections du récapitulatif, dans l'ordre d'apparition dans le mail."""

    OVERDUE = "overdue"
    TODAY = "today"
    DUE_SOON = "due_soon"
    PENDING = "pending"


@dataclass(frozen=True)
class SectionSpec:
    """Ce qu'est une section, indépendamment de son rendu.

    La couleur et la mise en page vivent dans `services/email_templates` : ce
    module décide *quelles* actions sont dans le message, pas à quoi il
    ressemble.
    """

    key: SectionKey
    label: str
    #: Phrase d'introduction de la section dans le message.
    intro: str
    #: Ce que la colonne de droite affiche pour cette section.
    colonne: str


SECTIONS: dict[SectionKey, SectionSpec] = {
    SectionKey.OVERDUE: SectionSpec(
        key=SectionKey.OVERDUE,
        label="En retard",
        intro="Échéance dépassée, action non terminée.",
        colonne="Retard",
    ),
    SectionKey.TODAY: SectionSpec(
        key=SectionKey.TODAY,
        label="À rendre aujourd'hui",
        intro="Ces actions arrivent à échéance aujourd'hui.",
        colonne="Échéance",
    ),
    SectionKey.DUE_SOON: SectionSpec(
        key=SectionKey.DUE_SOON,
        label="Échéances proches",
        intro="Rappel d'anticipation : aucune n'est encore en retard.",
        colonne="Échéance",
    ),
    SectionKey.PENDING: SectionSpec(
        key=SectionKey.PENDING,
        label="En attente",
        intro="Actions ouvertes sans urgence immédiate, pour mémoire.",
        colonne="Échéance",
    ),
}


@dataclass(frozen=True)
class Reglage:
    """Préférences d'envoi d'une personne, valeurs par défaut comprises.

    L'absence de ligne en base vaut acceptation des valeurs par défaut :
    personne n'a besoin de configurer quoi que ce soit pour être relancé. Ce
    type existe pour que cette règle soit écrite une fois — le worker, l'API
    et l'aperçu la lisaient sinon chacun à leur façon.
    """

    enabled: bool = True
    perimeter: RelancePerimetre = RelancePerimetre.SUIVI
    days_of_week: tuple[int, ...] = tuple(parse_jours(DEFAULT_JOURS_ENVOI))
    send_hour: int = DEFAULT_HEURE_ENVOI
    include_overdue: bool = True
    include_today: bool = True
    include_due_soon: bool = True
    include_pending: bool = True
    horizon_days: int = DEFAULT_HORIZON_DAYS
    #: Faux quand aucune ligne n'existe : l'API le signale pour distinguer
    #: « réglé ainsi » de « jamais configuré ».
    personnalise: bool = False

    @classmethod
    def depuis(cls, preference: RelancePreference | None) -> "Reglage":
        if preference is None:
            return cls()
        return cls(
            enabled=preference.enabled,
            perimeter=preference.perimeter,
            # Un réglage vide ou illisible ne doit pas supprimer les relances
            # en silence : on retombe sur la cadence par défaut.
            days_of_week=tuple(preference.jours) or tuple(parse_jours(DEFAULT_JOURS_ENVOI)),
            send_hour=preference.send_hour,
            include_overdue=preference.include_overdue,
            include_today=preference.include_today,
            include_due_soon=preference.include_due_soon,
            include_pending=preference.include_pending,
            horizon_days=preference.horizon_days,
            personnalise=True,
        )

    @property
    def frequence_hebdomadaire(self) -> int:
        return len(self.days_of_week)

    @property
    def sections_actives(self) -> tuple[SectionKey, ...]:
        """Sections retenues, dans l'ordre du message."""
        drapeaux = {
            SectionKey.OVERDUE: self.include_overdue,
            SectionKey.TODAY: self.include_today,
            SectionKey.DUE_SOON: self.include_due_soon,
            SectionKey.PENDING: self.include_pending,
        }
        return tuple(cle for cle in SectionKey if drapeaux[cle])

    @property
    def jours_lisibles(self) -> str:
        """« lundi et jeudi », pour l'affichage et les journaux."""
        noms = [JOURS_FR[j] for j in self.days_of_week]
        if not noms:
            return "jamais"
        if len(noms) == 1:
            return noms[0]
        return f"{', '.join(noms[:-1])} et {noms[-1]}"

    def prochain_creneau(self, maintenant: datetime) -> datetime | None:
        """Prochain envoi automatique après `maintenant`, ou None si aucun.

        Affiché tel quel dans l'interface : sans cette date, un réglage
        modifié un mardi pour un envoi le lundi laisse croire à une panne
        pendant six jours.
        """
        if not self.enabled or not self.days_of_week or not self.sections_actives:
            return None
        # Sept jours suffisent : la cadence est hebdomadaire, donc tout jour
        # retenu se represente au plus tard dans une semaine. Le huitième tour
        # couvre le cas où le créneau du jour même est déjà passé.
        base = maintenant.replace(minute=0, second=0, microsecond=0)
        for decalage in range(8):
            candidat = base.replace(hour=self.send_hour) + timedelta(days=decalage)
            if candidat > maintenant and candidat.weekday() in self.days_of_week:
                return candidat
        return None

    def doit_envoyer(self, maintenant: datetime) -> bool:
        """Ce moment précis est-il un créneau d'envoi ?

        Comparaison à l'heure pleine, pas à la minute : le planificateur
        déclenche la tâche en début d'heure, et exiger l'égalité des minutes
        ferait dépendre l'envoi de la ponctualité du worker.
        """
        if not self.enabled or not self.sections_actives:
            return False
        return (
            maintenant.weekday() in self.days_of_week
            and maintenant.hour == self.send_hour
        )


def perimetre_condition(
    perimeter: RelancePerimetre, responsable_id
) -> ColumnElement[bool]:
    """Condition « cette action concerne cette personne », selon son rôle.

    Distinguer suivi et réalisation n'est pas cosmétique : une même personne
    pilote certaines actions et en exécute d'autres. Les confondre enverrait
    au suiveur des lignes qu'il ne conduit pas, et au réalisateur des lignes
    qu'il ne fait pas — dans les deux cas un message qu'on apprend à ignorer.
    """
    suivi = Action.suiveurs.any(Responsable.id == responsable_id)
    realisation = Action.responsables.any(Responsable.id == responsable_id)

    if perimeter is RelancePerimetre.SUIVI:
        return suivi
    if perimeter is RelancePerimetre.REALISATION:
        return realisation
    return or_(suivi, realisation)


def requete_section(
    section: SectionKey,
    reglage: Reglage,
    responsable_id,
    today: date | None = None,
) -> Select:
    """`Select(Action)` des actions d'une section, pour une personne.

    Les quatre sections forment une partition des actions ouvertes : chaque
    action tombe dans une seule. Sans cette disjonction, le total annoncé en
    objet du message compterait deux fois la même ligne.
    """
    today = today or today_utc()
    perimetre = perimetre_condition(reglage.perimeter, responsable_id)

    commun = {
        "extra_condition": perimetre,
        # Un projet archivé ne relance plus personne.
        "active_projects_only": True,
        # Ni un projet ou une action mis en veille.
        "exclude_standby": True,
        "due_soon_days": reglage.horizon_days,
        "today": today,
    }

    if section is SectionKey.PENDING:
        # Pas de vue prédéfinie : « en attente » est le complément des trois
        # fenêtres de temps, calculé sur la date pour ne pas perdre les
        # actions sans échéance.
        stmt = build_actions_query(
            view=ActionView.ALL,
            **{**commun, "extra_condition": and_(perimetre, is_pending(reglage.horizon_days, today))},
        )
    else:
        vue = {
            SectionKey.OVERDUE: ActionView.OVERDUE,
            SectionKey.TODAY: ActionView.TODAY,
            SectionKey.DUE_SOON: ActionView.DUE_SOON,
        }[section]
        stmt = build_actions_query(view=vue, **commun)

    return default_order(stmt)


def requetes(
    reglage: Reglage, responsable_id, today: date | None = None
) -> list[tuple[SectionSpec, Select]]:
    """Les requêtes du récapitulatif, dans l'ordre du message."""
    today = today or today_utc()
    return [
        (SECTIONS[cle], requete_section(cle, reglage, responsable_id, today))
        for cle in reglage.sections_actives
    ]
