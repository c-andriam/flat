import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.services import microsoft
from app.services.security import create_access_token, get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get(
    "/login",
    summary="Démarrer le flow d'authentification Microsoft",
    description=(
        "Redirige le navigateur vers la page de connexion Microsoft Entra ID "
        "(OAuth2 Authorization Code flow). Un paramètre `state` aléatoire est "
        "généré pour la protection CSRF du callback."
    ),
    response_description="Redirection HTTP 307 vers la page de connexion Microsoft.",
    status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    responses={
        307: {"description": "Redirection vers login.microsoftonline.com"},
    },
)
def login():
    """Redirige le navigateur vers la page de connexion Microsoft."""
    state = secrets.token_urlsafe(16)
    # TODO: stocker `state` (session/redis) et le vérifier au callback pour se
    # prémunir des attaques CSRF sur le flow OAuth. Squelette minimal pour l'instant.
    return RedirectResponse(url=microsoft.get_auth_url(state))


@router.get(
    "/callback",
    summary="Callback OAuth2 Microsoft",
    description=(
        "Point de retour appelé par Microsoft après authentification, avec un "
        "paramètre `code` (authorization code). Échange ce code contre les "
        "informations de l'utilisateur, crée ou met à jour le compte "
        "applicatif correspondant, puis émet un JWT propre à l'API."
    ),
    response_description="Jeton d'accès JWT applicatif.",
    responses={
        200: {
            "description": "Authentification réussie, jeton émis.",
            "content": {
                "application/json": {
                    "example": {
                        "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                        "token_type": "bearer",
                    }
                }
            },
        },
        400: {
            "description": (
                "Code d'autorisation invalide/expiré, ou claims Microsoft "
                "incomplets (`oid` ou email manquant)."
            )
        },
    },
)
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

    from datetime import datetime, timezone
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)

    token = create_access_token(user)

    # TODO: rediriger vers le frontend avec le token (ex: cookie httpOnly ou
    # fragment d'URL) plutôt que de le renvoyer brut en JSON.
    return {"access_token": token, "token_type": "bearer"}


@router.get(
    "/me",
    summary="Profil de l'utilisateur connecté",
    description="Retourne l'identité et le rôle de l'utilisateur associé au JWT fourni dans le header `Authorization`.",
    response_description="Informations du compte courant.",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "id": "b6f3a1e2-4c9d-4e2a-9f3d-2b7a1c0e5f11",
                        "email": "juvence@trimeta.mg",
                        "display_name": "Candriam Juvence",
                        "role": "user",
                    }
                }
            }
        },
        401: {"description": "Jeton absent, invalide ou expiré."},
    },
)
def me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "email": current_user.email,
        "display_name": current_user.display_name,
        "role": current_user.role.value,
    }
