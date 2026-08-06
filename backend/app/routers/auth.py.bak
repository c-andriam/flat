import secrets

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.services import microsoft
from app.services.security import create_access_token, get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/login")
def login():
    """Redirige le navigateur vers la page de connexion Microsoft."""
    state = secrets.token_urlsafe(16)
    # TODO: stocker `state` (session/redis) et le vérifier au callback pour se
    # prémunir des attaques CSRF sur le flow OAuth. Squelette minimal pour l'instant.
    return RedirectResponse(url=microsoft.get_auth_url(state))


@router.get("/callback")
def callback(code: str, db: Session = Depends(get_db)):
    """
    Microsoft redirige ici après connexion avec ?code=...
    On échange le code contre les infos utilisateur, on crée/met à jour le
    compte en base, et on émet notre propre JWT applicatif.
    """
    try:
        result = microsoft.acquire_token_by_code(code)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    claims = result.get("id_token_claims", {})
    azure_object_id = claims.get("oid")
    email = claims.get("preferred_username") or claims.get("email")
    display_name = claims.get("name", email)

    if not azure_object_id or not email:
        raise HTTPException(status_code=400, detail="Claims Microsoft incomplets")

    user = db.query(User).filter(User.azure_object_id == azure_object_id).first()
    if not user:
        user = User(azure_object_id=azure_object_id, email=email, display_name=display_name)
        db.add(user)
    else:
        user.email = email
        user.display_name = display_name

    from datetime import datetime
    user.last_login_at = datetime.utcnow()
    db.commit()
    db.refresh(user)

    token = create_access_token(user)

    # TODO: rediriger vers le frontend avec le token (ex: cookie httpOnly ou
    # fragment d'URL) plutôt que de le renvoyer brut en JSON.
    return {"access_token": token, "token_type": "bearer"}


@router.get("/me")
def me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "email": current_user.email,
        "display_name": current_user.display_name,
        "role": current_user.role.value,
    }
