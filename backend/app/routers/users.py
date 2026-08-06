import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User, UserRole
from app.schemas.user_schema import UserOut, UserUpdate
from app.services.security import require_role

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserOut], dependencies=[Depends(require_role("admin"))])
def list_users(db: Session = Depends(get_db)):
    return db.query(User).order_by(User.display_name).all()


@router.get("/{user_id}", response_model=UserOut, dependencies=[Depends(require_role("admin"))])
def get_user(user_id: uuid.UUID, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    return user


@router.patch("/{user_id}", response_model=UserOut, dependencies=[Depends(require_role("admin"))])
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


@router.delete("/{user_id}", status_code=204, dependencies=[Depends(require_role("admin"))])
def delete_user(user_id: uuid.UUID, db: Session = Depends(get_db)):
    """
    Supprime le compte applicatif. Le compte Azure AD sous-jacent n'est pas
    touché (géré par l'IT côté Entra ID) — l'utilisateur pourrait techniquement
    se reconnecter et recréer un compte, à combiner avec is_active si besoin
    de bloquer l'accès sans supprimer l'historique.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")

    db.delete(user)
    db.commit()
