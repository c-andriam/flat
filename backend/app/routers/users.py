import uuid

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.database import get_async_db
from app.models.user import User, UserRole
from app.schemas.user_schema import UserOut, UserUpdate
from app.services.security import require_admin
from app.services.security import purger_profil

router = APIRouter(prefix="/users", tags=["users"])

ADMIN_ONLY_RESPONSES = {
    401: {"description": "Jeton absent, invalide ou expiré."},
    403: {"description": "Le compte connecté n'a pas le rôle `admin`."},
}


async def _count_active_admins(db: AsyncSession, excluding: uuid.UUID | None = None) -> int:
    stmt = (
        select(func.count())
        .select_from(User)
        .filter(User.role == UserRole.ADMIN, User.is_active.is_(True))
    )
    if excluding is not None:
        stmt = stmt.filter(User.id != excluding)
    result = await db.execute(stmt)
    return int(result.scalar_one())


@router.get(
    "",
    response_model=list[UserOut],
    summary="Lister les comptes utilisateurs",
    description="Retourne tous les comptes applicatifs, triés par nom affiché. Réservé aux administrateurs.",
    response_description="Liste des utilisateurs.",
    responses=ADMIN_ONLY_RESPONSES,
)
async def list_users(
    _admin: User = require_admin,
    db: AsyncSession = Depends(get_async_db),
):
    result = await db.execute(select(User).order_by(User.display_name).limit(1000))
    return result.scalars().all()


@router.get(
    "/{user_id}",
    response_model=UserOut,
    summary="Détail d'un utilisateur",
    description="Retourne un compte applicatif par son identifiant. Réservé aux administrateurs.",
    response_description="L'utilisateur demandé.",
    responses={**ADMIN_ONLY_RESPONSES, 404: {"description": "Aucun utilisateur avec cet identifiant."}},
)
async def get_user(
    user_id: uuid.UUID = Path(..., description="Identifiant unique (UUID) du compte utilisateur."),
    _admin: User = require_admin,
    db: AsyncSession = Depends(get_async_db),
):
    result = await db.execute(select(User).filter(User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    return user


@router.put(
    "/{user_id}",
    response_model=UserOut,
    summary="Modifier un utilisateur",
    description=(
        "Un admin peut changer le rôle (RBAC) ou désactiver un compte "
        "(mise à jour partielle — seuls les champs fournis sont modifiés).\n\n"
        "Deux garde-fous empêchent de se verrouiller hors de l'application : "
        "un admin ne peut ni se rétrograder ni se désactiver lui-même, et le "
        "dernier admin actif ne peut pas être rétrogradé."
    ),
    response_description="L'utilisateur mis à jour.",
    responses={
        **ADMIN_ONLY_RESPONSES,
        404: {"description": "Aucun utilisateur avec cet identifiant."},
        409: {"description": "L'opération supprimerait le dernier administrateur actif."},
        422: {"description": "Valeur de `role` invalide."},
    },
)
async def update_user(
    payload: UserUpdate,
    user_id: uuid.UUID = Path(..., description="Identifiant unique (UUID) du compte utilisateur à modifier."),
    current_user: User = require_admin,
    db: AsyncSession = Depends(get_async_db),
):
    result = await db.execute(select(User).filter(User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")

    update_data = payload.model_dump(exclude_unset=True)

    loses_admin = (
        update_data.get("role") is not None and update_data["role"] is not UserRole.ADMIN
    ) or update_data.get("is_active") is False

    if loses_admin and user.role is UserRole.ADMIN:
        if user.id == current_user.id:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Un administrateur ne peut pas se rétrograder ni se "
                    "désactiver lui-même. Demander à un autre admin."
                ),
            )
        if await _count_active_admins(db, excluding=user.id) == 0:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Opération refusée : ce compte est le dernier administrateur "
                    "actif, l'application deviendrait inadministrable."
                ),
            )

    for field, value in update_data.items():
        setattr(user, field, value)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Conflit lors de la mise à jour")

    await db.refresh(user)
    # Le profil est mis en cache quelques secondes : sans cette purge, une
    # rétrogradation resterait sans effet pendant la durée de vie de l'entrée.
    await purger_profil(user.id)
    return user


@router.delete(
    "/{user_id}",
    status_code=204,
    summary="Supprimer un utilisateur",
    description=(
        "Supprime le compte applicatif. Le compte Azure AD sous-jacent n'est "
        "pas touché (géré par l'IT côté Entra ID) — l'utilisateur pourrait "
        "techniquement se reconnecter et recréer un compte ; combiner avec "
        "`is_active` si un blocage d'accès sans perte d'historique est requis."
    ),
    response_description="Aucun contenu — suppression effectuée.",
    responses={
        **ADMIN_ONLY_RESPONSES,
        404: {"description": "Aucun utilisateur avec cet identifiant."},
        409: {"description": "Suppression de soi-même ou du dernier administrateur actif."},
    },
)
async def delete_user(
    user_id: uuid.UUID = Path(..., description="Identifiant unique (UUID) du compte utilisateur à supprimer."),
    current_user: User = require_admin,
    db: AsyncSession = Depends(get_async_db),
):
    result = await db.execute(select(User).filter(User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")

    if user.id == current_user.id:
        raise HTTPException(
            status_code=409,
            detail="Un administrateur ne peut pas supprimer son propre compte.",
        )
    if user.role is UserRole.ADMIN and await _count_active_admins(db, excluding=user.id) == 0:
        raise HTTPException(
            status_code=409,
            detail=(
                "Opération refusée : ce compte est le dernier administrateur "
                "actif, l'application deviendrait inadministrable."
            ),
        )

    await db.delete(user)
    await db.commit()
    await purger_profil(user.id)
