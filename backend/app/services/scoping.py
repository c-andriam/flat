"""
Cloisonnement des données par compte.

Les projets et les actions décrivent qui doit faire quoi : ce n'est pas une
information que tout porteur d'un compte a vocation à lire. Un collaborateur ne
voit donc que les actions qu'il porte, les projets où il en a au moins une, et
sa propre ligne dans les rapports. Seuls le DSIO et les administrateurs gardent
la vue complète.

Le lien entre un compte applicatif (`users`, alimenté par Entra ID) et une
fiche responsable (`responsables`, extraite des classeurs Excel) se fait par
l'adresse email — le même mappage dont dépendent déjà les relances Outlook.
Une même personne peut porter plusieurs fiches : les classeurs l'écrivent
parfois « AndryI » et parfois « Andry I ».

Un compte sans fiche correspondante ne voit rien. C'est délibéré : en cas de
doute sur l'identité, ne rien divulguer est le seul comportement sûr. Le
frontend affiche alors un bandeau expliquant qu'il faut demander l'association
à un administrateur, pour qu'une visibilité nulle ne passe pas pour une panne.
"""

import hashlib
import uuid

from fastapi import Depends
from sqlalchemy import ColumnElement, false, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_db
from app.models.project import Action, Project, Responsable
from app.models.user import User, UserRole
from app.services.security import get_current_user

#: Rôles qui conservent la vue complète du portefeuille.
FULL_SCOPE_ROLES = frozenset({UserRole.ADMIN, UserRole.DSIO})


def sees_all_data(user: User) -> bool:
    """Vrai si le compte échappe au cloisonnement."""
    return user.role in FULL_SCOPE_ROLES


async def responsable_ids_for(db: AsyncSession, user: User) -> list[uuid.UUID]:
    """Fiches responsable rattachées à ce compte, via l'email.

    Comparaison insensible à la casse : les emails viennent d'une saisie
    manuelle dans Excel d'un côté, d'Entra ID de l'autre.
    """
    if not user.email:
        return []
    result = await db.execute(
        select(Responsable.id).where(
            func.lower(Responsable.email) == user.email.strip().lower()
        )
    )
    return list(result.scalars().all())


def action_scope_condition(responsable_ids: list[uuid.UUID]) -> ColumnElement[bool]:
    """Condition « cette action me concerne ».

    `resp_suivi` n'entre pas dans le critère : c'est du texte libre, souvent
    composite (« Andry II, Xavier »), et le faire entrer rendrait la
    confidentialité dépendante d'une correspondance de chaînes approximative.
    Seule la table de liaison fait foi.
    """
    if not responsable_ids:
        # `false()` plutôt qu'une absence de filtre : sans fiche rattachée, le
        # périmètre est vide, pas universel.
        return false()
    return Action.responsables.any(Responsable.id.in_(responsable_ids))


def project_scope_condition(responsable_ids: list[uuid.UUID]) -> ColumnElement[bool]:
    """Condition « ce projet me concerne » — au moins une action portée."""
    if not responsable_ids:
        return false()
    return Project.actions.any(action_scope_condition(responsable_ids))


class Scope:
    """Périmètre de lecture d'un appelant, résolu une fois par requête."""

    def __init__(self, *, unrestricted: bool, responsable_ids: list[uuid.UUID]):
        self.unrestricted = unrestricted
        self.responsable_ids = responsable_ids

    @property
    def cache_token(self) -> str:
        """Identité du périmètre, pour cloisonner les clés de cache.

        Deux comptes rattachés aux mêmes fiches lisent rigoureusement les mêmes
        données : ils peuvent partager une entrée. Deux comptes différents ne
        le peuvent jamais — d'où la présence de ce jeton dans chaque clé.
        """
        if self.unrestricted:
            return "all"
        if not self.responsable_ids:
            return "none"
        empreinte = ",".join(sorted(str(value) for value in self.responsable_ids))
        return hashlib.sha1(empreinte.encode()).hexdigest()[:16]

    @property
    def is_linked(self) -> bool:
        """Le compte est rattaché à au moins une fiche responsable."""
        return bool(self.responsable_ids)

    @property
    def is_empty(self) -> bool:
        """Le compte ne peut rien voir : restreint et non rattaché."""
        return not self.unrestricted and not self.responsable_ids

    def actions(self) -> ColumnElement[bool] | None:
        """Condition à appliquer aux requêtes sur `actions`, ou None."""
        if self.unrestricted:
            return None
        return action_scope_condition(self.responsable_ids)

    def projects(self) -> ColumnElement[bool] | None:
        """Condition à appliquer aux requêtes sur `projects`, ou None."""
        if self.unrestricted:
            return None
        return project_scope_condition(self.responsable_ids)


async def resolve_scope(db: AsyncSession, user: User) -> Scope:
    if sees_all_data(user):
        return Scope(unrestricted=True, responsable_ids=[])
    return Scope(unrestricted=False, responsable_ids=await responsable_ids_for(db, user))


async def get_scope(
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user),
) -> Scope:
    """Dépendance FastAPI : résout le périmètre une fois par requête."""
    return await resolve_scope(db, user)
