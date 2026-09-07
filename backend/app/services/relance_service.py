"""
Exécution du récapitulatif de relance, en session synchrone comme asynchrone.

`services/relance_digest` décide *ce que* contient un récapitulatif ; ce module
l'exécute. La séparation vient d'une contrainte concrète : le worker Celery
travaille sur une session SQLAlchemy synchrone et les routes d'API sur une
session asynchrone. Deux implémentations complètes finissaient toujours par
diverger — l'aperçu affiché à l'écran ne montrait alors plus le message
réellement expédié. Ici, seule l'exécution des requêtes est dédoublée ; la
sélection, le gabarit et la trace sont communs.
"""

import uuid
from datetime import date, datetime, time, timezone

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models.project import (
    DEFAULT_HEURE_ENVOI,
    Action,
    RelanceLog,
    RelancePreference,
    Responsable,
)
from app.services import outlook
from app.services.action_rules import today_utc
from app.services.digests import to_digest
from app.services.email_templates import EmailMessage, build_digest_email
from app.services.relance_digest import Reglage, SectionSpec, requetes
from app.schemas.report_schema import ActionDigestOut

#: Nature inscrite dans `RelanceLog.kind` pour un récapitulatif.
KIND_DIGEST = "digest"

#: Relations à charger avec les actions. `to_digest` lit `responsables` et
#: `project` ; y accéder sans préchargement déclencherait un lazy-load hors
#: contexte greenlet sur session asynchrone (MissingGreenlet).
_CHARGEMENTS = (selectinload(Action.responsables), selectinload(Action.project))

#: Sections = list[(spec, actions)] — le type circule entre les trois couches.
Sections = list[tuple[SectionSpec, list[ActionDigestOut]]]


# ---------------------------------------------------------------------------
# Réglages
# ---------------------------------------------------------------------------

def reglage_sync(db, responsable_id: uuid.UUID) -> Reglage:
    preference = db.execute(
        select(RelancePreference).filter(
            RelancePreference.responsable_id == responsable_id
        )
    ).scalars().first()
    return Reglage.depuis(preference)


async def reglage_async(db, responsable_id: uuid.UUID) -> Reglage:
    result = await db.execute(
        select(RelancePreference).filter(
            RelancePreference.responsable_id == responsable_id
        )
    )
    return Reglage.depuis(result.scalars().first())


# ---------------------------------------------------------------------------
# Destinataires
# ---------------------------------------------------------------------------

def _requete_candidats(heure: int | None):
    """Responsables joignables, avec leur réglage éventuel, en une requête.

    Le `outerjoin` est ce qui évite un N+1 : la tâche planifiée s'exécute
    toutes les heures, et interroger la table des préférences une fois par
    personne y multipliait les allers-retours vers une base distante — le coût
    dominant, à ~250 ms l'aller-retour.

    Args:
        heure: ne retenir que les personnes dont le créneau tombe à cette
            heure. `None` les retient toutes (campagne immédiate).
    """
    stmt = (
        select(Responsable, RelancePreference)
        .outerjoin(
            RelancePreference, RelancePreference.responsable_id == Responsable.id
        )
        .where(Responsable.is_mapped.is_(True), Responsable.email.isnot(None))
        .order_by(Responsable.display_name)
    )
    if heure is None:
        return stmt

    conditions = [
        and_(
            RelancePreference.enabled.is_(True),
            RelancePreference.send_hour == heure,
        )
    ]
    # Une personne sans ligne de préférence suit les valeurs par défaut : elle
    # n'est candidate qu'à l'heure par défaut. Le test porte sur une constante
    # Python, il n'a donc pas à traverser SQL.
    if heure == DEFAULT_HEURE_ENVOI:
        conditions.append(RelancePreference.id.is_(None))
    return stmt.where(or_(*conditions))


def _apparier(lignes) -> list[tuple[Responsable, Reglage]]:
    return [(responsable, Reglage.depuis(pref)) for responsable, pref in lignes]


def candidats_sync(db, heure: int | None) -> list[tuple[Responsable, Reglage]]:
    return _apparier(db.execute(_requete_candidats(heure)).all())


async def candidats_async(db, heure: int | None) -> list[tuple[Responsable, Reglage]]:
    result = await db.execute(_requete_candidats(heure))
    return _apparier(result.all())


# ---------------------------------------------------------------------------
# Sélection des actions
# ---------------------------------------------------------------------------

def sections_sync(
    db, reglage: Reglage, responsable_id: uuid.UUID, today: date | None = None
) -> Sections:
    today = today or today_utc()
    resultat: Sections = []
    for spec, stmt in requetes(reglage, responsable_id, today):
        actions = db.execute(stmt.options(*_CHARGEMENTS)).scalars().unique().all()
        resultat.append((spec, [to_digest(a, today) for a in actions]))
    return resultat


async def sections_async(
    db, reglage: Reglage, responsable_id: uuid.UUID, today: date | None = None
) -> Sections:
    today = today or today_utc()
    resultat: Sections = []
    for spec, stmt in requetes(reglage, responsable_id, today):
        result = await db.execute(stmt.options(*_CHARGEMENTS))
        actions = result.scalars().unique().all()
        resultat.append((spec, [to_digest(a, today) for a in actions]))
    return resultat


def total_actions(sections: Sections) -> int:
    return sum(len(actions) for _, actions in sections)


def ids_actions(sections: Sections) -> list[uuid.UUID]:
    """Identifiants de toutes les actions du message, sans doublon.

    Les sections sont disjointes par construction, mais la trace d'audit ne
    doit pas dépendre de cette propriété : une régression sur les prédicats
    inscrirait sinon deux fois la même action dans `RelanceLog`.
    """
    vus: list[uuid.UUID] = []
    connus: set[uuid.UUID] = set()
    for _, actions in sections:
        for action in actions:
            if action.id not in connus:
                connus.add(action.id)
                vus.append(action.id)
    return vus


# ---------------------------------------------------------------------------
# Message
# ---------------------------------------------------------------------------

def cadence_lisible(reglage: Reglage) -> str:
    """« 2 fois par semaine (lundi et jeudi), vers 8 h »."""
    return (
        f"{reglage.frequence_hebdomadaire} fois par semaine "
        f"({reglage.jours_lisibles}), vers {reglage.send_hour} h"
    )


def construire_message(
    responsable: Responsable, reglage: Reglage, sections: Sections
) -> EmailMessage:
    return build_digest_email(
        responsable.display_name,
        sections,
        app_url=f"{settings.frontend_url}/actions",
        cadence=cadence_lisible(reglage),
        reglages_url=f"{settings.frontend_url}/relances",
    )


# ---------------------------------------------------------------------------
# Garde-fous d'envoi
# ---------------------------------------------------------------------------

def _debut_du_jour(today: date | None = None) -> datetime:
    """Minuit UTC du jour courant, pour borner « déjà envoyé aujourd'hui ».

    La journée est calculée en UTC comme partout ailleurs dans l'application
    (`today_utc`). Le décalage d'Antananarivo (UTC+3) ne change rien au
    résultat pour un envoi matinal, et une double définition du « jour » aurait
    coûté plus cher qu'elle ne rapporte.
    """
    return datetime.combine(today or today_utc(), time.min, tzinfo=timezone.utc)


def _deja_envoye(derniere: datetime | None, today: date | None = None) -> bool:
    if derniere is None:
        return False
    if derniere.tzinfo is None:
        derniere = derniere.replace(tzinfo=timezone.utc)
    return derniere >= _debut_du_jour(today)


def _requete_dernier_envoi(responsable_id: uuid.UUID, kind: str):
    return select(func.max(RelanceLog.sent_at)).filter(
        RelanceLog.responsable_id == responsable_id, RelanceLog.kind == kind
    )


def deja_envoye_sync(
    db, responsable_id: uuid.UUID, kind: str = KIND_DIGEST, today: date | None = None
) -> bool:
    """Un message de cette nature est-il déjà parti aujourd'hui ?

    C'est ce qui rend la tâche planifiée idempotente. Elle s'exécute toutes
    les heures pour honorer les heures d'envoi choisies par chacun ; sans ce
    garde-fou, un worker redémarré ou une tâche redistribuée après un
    `acks_late` renverrait le même récapitulatif.
    """
    derniere = db.execute(_requete_dernier_envoi(responsable_id, kind)).scalar_one_or_none()
    return _deja_envoye(derniere, today)


def motif_de_blocage(
    responsable: Responsable,
    reglage: Reglage,
    sections: Sections,
    *,
    ignorer_desactivation: bool = False,
) -> str | None:
    """Pourquoi ce récapitulatif ne partirait pas — ou None s'il peut partir.

    Les motifs sont ordonnés du plus structurel au plus conjoncturel : c'est
    l'ordre dans lequel on veut les corriger, et celui qui rend le message
    d'erreur actionnable.

    Args:
        ignorer_desactivation: passer outre le choix d'une personne ayant
            coupé ses relances. Réservé à une campagne exceptionnelle décidée
            par un administrateur ; les autres motifs restent bloquants, eux
            ne relèvent pas d'un arbitrage mais d'un envoi impossible.
    """
    if not reglage.enabled and not ignorer_desactivation:
        return "Relances désactivées pour ce responsable."
    if not reglage.sections_actives:
        return (
            "Aucune section retenue : le récapitulatif serait vide. "
            "Activer au moins une catégorie d'actions."
        )
    if not (responsable.is_mapped and responsable.email):
        return (
            "Responsable non mappé : aucune adresse email associée. "
            "Renseigner l'email via PUT /responsables/{id}."
        )
    if total_actions(sections) == 0:
        return "Aucune action ne correspond à ce récapitulatif."
    return None


# ---------------------------------------------------------------------------
# Envoi
# ---------------------------------------------------------------------------

def envoyer_sync(
    db,
    responsable: Responsable,
    message: EmailMessage,
    sections: Sections,
    kind: str = KIND_DIGEST,
) -> outlook.SendResult:
    """Expédie le message et enregistre la trace, en session synchrone.

    La trace n'est écrite que si l'envoi a abouti — un `RelanceLog` posé sur un
    échec ferait croire au garde-fou d'idempotence qu'un message est parti, et
    la personne ne serait jamais relancée.
    """
    resultat = outlook.send_email(
        to=responsable.email,
        subject=message.subject,
        html_body=message.html,
        text_body=message.text,
    )
    if resultat.ok:
        ids = ids_actions(sections)
        db.add(
            RelanceLog(
                responsable_id=responsable.id,
                action_ids=",".join(str(i) for i in ids),
                email_status=resultat.status.value,
                kind=kind,
                action_count=len(ids),
            )
        )
        db.commit()
    return resultat
