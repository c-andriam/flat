import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User, UserRole
from app.schemas.user_schema import UserOut, UserUpdate
from app.services.security import require_role

router = APIRouter(prefix="/users", tags=["users"])

ADMIN_ONLY_RESPONSES = {
    401: {"description": "Jeton absent, invalide ou expiré."},
    403: {"description": "Le compte connecté n'a pas le rôle `admin`."},
}


@router.get(
    "",
    response_model=list[UserOut],
    dependencies=[Depends(require_role("admin"))],
    summary="Lister les comptes utilisateurs",
    description="Retourne tous les comptes applicatifs, triés par nom affiché. Réservé aux administrateurs.",
    response_description="Liste des utilisateurs.",
    responses=ADMIN_ONLY_RESPONSES,
)
def list_users(db: Session = Depends(get_db)):
    return db.query(User).order_by(User.display_name).all()


@router.get(
    "/{user_id}",
    response_model=UserOut,
    dependencies=[Depends(require_role("admin"))],
    summary="Détail d'un utilisateur",
    description="Retourne un compte applicatif par son identifiant. Réservé aux administrateurs.",
    response_description="L'utilisateur demandé.",
    responses={**ADMIN_ONLY_RESPONSES, 404: {"description": "Aucun utilisateur avec cet identifiant."}},
)
def get_user(user_id: uuid.UUID, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    return user


@router.patch(
    "/{user_id}",
    response_model=UserOut,
    dependencies=[Depends(require_role("admin"))],
    summary="Modifier un utilisateur",
    description=(
        "Un admin peut changer le rôle (RBAC) ou désactiver un compte "
        "(mise à jour partielle — seuls les champs fournis sont modifiés)."
    ),
    response_description="L'utilisateur mis à jour.",
    responses={
        **ADMIN_ONLY_RESPONSES,
        404: {"description": "Aucun utilisateur avec cet identifiant."},
        422: {"description": "Valeur de `role` invalide."},
    },
)
def update_user(user_id: uuid.UUID, payload: UserUpdate, db: Session = Depends(get_db)):
    """Un admin peut changer le rôle (RBAC) ou désactiver un compte."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")

    update_data = payload.model_dump(exclude_unset=True)

    if "role" in update_data:
        try:
            update_data["role"] = UserRole(update_data["role"])
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Rôle invalide: {update_data['role']}")

    for field, value in update_data.items():
        setattr(user, field, value)

    db.commit()
    db.refresh(user)
    return user


@router.delete(
    "/{user_id}",
    status_code=204,
    dependencies=[Depends(require_role("admin"))],
    summary="Supprimer un utilisateur",
    description=(
        "Supprime le compte applicatif. Le compte Azure AD sous-jacent n'est "
        "pas touché (géré par l'IT côté Entra ID) — l'utilisateur pourrait "
        "techniquement se reconnecter et recréer un compte ; combiner avec "
        "`is_active` si un blocage d'accès sans perte d'historique est requis."
    ),
    response_description="Aucun contenu — suppression effectuée.",
    responses={**ADMIN_ONLY_RESPONSES, 404: {"description": "Aucun utilisateur avec cet identifiant."}},
)
def delete_user(user_id: uuid.UUID, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")

    db.delete(user)
    db.commit()
