import os
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status, Request, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.database import get_async_db
from app.models.user import User
from app.services import microsoft
from app.services.security import create_access_token, get_current_user

limiter = Limiter(key_func=get_remote_address)
router = APIRouter(prefix="/auth", tags=["auth"])


@router.get(
    "/login",
    summary="Lancer le flux SSO Microsoft",
    description="Génère un état anti-CSRF et redirige vers la page de login Microsoft.",
    response_description="Redirection HTTP 302 vers login.microsoftonline.com",
)
@limiter.limit("10/minute")
def login(request: Request):
    """Redirige le navigateur vers la page de connexion Microsoft."""
    state = secrets.token_urlsafe(16)
    url = microsoft.get_auth_url(state)
    response = RedirectResponse(url=url)
    response.set_cookie(
        key="oauth_state",
        value=state,
        httponly=True,
        max_age=300,  # 5 minutes
        samesite="lax",
    )
    return response


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
@limiter.limit("5/minute")
async def callback(
    request: Request,
    code: str = Query(..., description="Le code d'autorisation retourné par Microsoft Entra ID."),
    state: str = Query(..., description="L'état anti-CSRF initialement généré par /login."),
    db: AsyncSession = Depends(get_async_db)
):
    """
    Microsoft redirige ici après connexion avec ?code=...&state=...
    On vérifie l'état CSRF, on échange le code contre les infos utilisateur, 
    on crée/met à jour le compte en base, et on émet notre propre JWT applicatif.
    """
    # 1. Vérification CSRF
    stored_state = request.cookies.get("oauth_state")
    if not stored_state or state != stored_state:
        raise HTTPException(status_code=400, detail="Invalid CSRF state token")

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

    result = await db.execute(select(User).filter(User.azure_object_id == azure_object_id))
    user = result.scalars().first()
    if not user:
        user = User(azure_object_id=azure_object_id, email=email, display_name=display_name)
        db.add(user)
    else:
        user.email = email
        user.display_name = display_name

    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(user)

    token = create_access_token(user)

    # Rediriger vers le frontend avec le token
    frontend_url = os.getenv("FRONTEND_URL", "/")
    response = RedirectResponse(url=f"{frontend_url}?token={token}")
    response.delete_cookie(key="oauth_state")
    return response


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
