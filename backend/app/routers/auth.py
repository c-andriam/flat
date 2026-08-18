import logging
import secrets
from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.config import settings
from app.database import get_async_db
from app.models.user import User, UserRole
from app.schemas.user_schema import UserOut
from app.services import microsoft
from app.services.rate_limit import limiter
from app.services.security import create_access_token, get_current_user

logger = logging.getLogger("dsio.auth")

router = APIRouter(prefix="/auth", tags=["auth"])

_STATE_COOKIE = "oauth_state"
_STATE_COOKIE_PATH = "/api/v1/auth"


@router.get(
    "/login",
    summary="Lancer le flux SSO Microsoft",
    description="Génère un état anti-CSRF et redirige vers la page de login Microsoft.",
    response_description="Redirection HTTP 302 vers login.microsoftonline.com",
)
@limiter.limit("10/minute")
def login(request: Request):
    """Redirige le navigateur vers la page de connexion Microsoft."""
    state = secrets.token_urlsafe(32)
    url = microsoft.get_auth_url(state)
    response = RedirectResponse(url=url)
    response.set_cookie(
        key=_STATE_COOKIE,
        value=state,
        httponly=True,
        # `secure` : le cookie ne doit jamais transiter en clair. Désactivable
        # via COOKIE_SECURE=false pour un poste de dev servi en http://.
        secure=settings.cookie_secure,
        max_age=300,  # 5 minutes
        samesite="lax",
        path=_STATE_COOKIE_PATH,
    )
    return response


@router.get(
    "/callback",
    summary="Callback OAuth2 Microsoft",
    description=(
        "Point de retour appelé par Microsoft après authentification, avec un "
        "paramètre `code` (authorization code). Échange ce code contre les "
        "informations de l'utilisateur, crée ou met à jour le compte "
        "applicatif correspondant, puis redirige vers le frontend avec un JWT "
        "propre à l'API.\n\n"
        "Le jeton est transmis dans le **fragment** de l'URL "
        "(`.../#token=...`) et non dans la query string : un fragment n'est "
        "jamais envoyé au serveur, donc jamais écrit dans les logs nginx ni "
        "transmis via l'en-tête `Referer` à un site tiers."
    ),
    response_description="Redirection vers le frontend, jeton dans le fragment d'URL.",
    responses={
        400: {
            "description": (
                "Consentement refusé, état CSRF invalide, code d'autorisation "
                "expiré, ou claims Microsoft incomplets (`oid` ou email manquant)."
            )
        },
        502: {"description": "Microsoft Entra ID injoignable."},
    },
)
@limiter.limit("5/minute")
async def callback(
    request: Request,
    code: str | None = Query(None, description="Le code d'autorisation retourné par Microsoft Entra ID."),
    state: str | None = Query(None, description="L'état anti-CSRF initialement généré par /login."),
    error: str | None = Query(None, description="Code d'erreur renvoyé par Microsoft (ex: access_denied)."),
    error_description: str | None = Query(None, description="Message d'erreur détaillé de Microsoft."),
    db: AsyncSession = Depends(get_async_db),
):
    """
    Microsoft redirige ici après connexion avec ?code=...&state=...
    On vérifie l'état CSRF, on échange le code contre les infos utilisateur,
    on crée/met à jour le compte en base, et on émet notre propre JWT applicatif.
    """
    # 0. Microsoft signale une erreur (consentement refusé, compte bloqué...).
    #    Sans ce cas, l'absence de `code` produisait un 422 illisible.
    if error:
        logger.warning("Callback Microsoft en erreur : %s (%s)", error, error_description)
        raise HTTPException(
            status_code=400,
            detail=f"Authentification Microsoft refusée : {error_description or error}",
        )
    if not code or not state:
        raise HTTPException(
            status_code=400,
            detail="Paramètres 'code' et 'state' requis — relancer la connexion depuis /api/v1/auth/login.",
        )

    # 1. Vérification CSRF, en comparaison à temps constant.
    stored_state = request.cookies.get(_STATE_COOKIE)
    if not stored_state or not secrets.compare_digest(state, stored_state):
        raise HTTPException(status_code=400, detail="Invalid CSRF state token")

    try:
        result = microsoft.acquire_token_by_code(code)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        logger.exception("Échange du code d'autorisation impossible")
        raise HTTPException(status_code=502, detail="Erreur de communication avec Microsoft")

    claims = result.get("id_token_claims", {}) or {}
    azure_object_id = claims.get("oid")
    email = claims.get("preferred_username") or claims.get("email")
    display_name = claims.get("name") or email

    if not azure_object_id or not email:
        raise HTTPException(status_code=400, detail="Claims Microsoft incomplets")

    email = email.strip().lower()

    db_result = await db.execute(select(User).filter(User.azure_object_id == azure_object_id))
    user = db_result.scalars().first()

    if user is None:
        # Rattachement par email : un compte peut avoir été pré-créé par un
        # administrateur (scripts/issue_token.py) avec un identifiant local, ou
        # avoir été recréé côté Entra ID avec un nouvel `oid`. Sans ce repli, on
        # tentait d'insérer un second compte sur un email déjà pris — soit une
        # erreur d'intégrité en pleine connexion. L'email vient d'un jeton signé
        # par notre propre tenant, il fait donc autorité pour l'identification.
        by_email = await db.execute(select(User).filter(User.email == email))
        user = by_email.scalars().first()
        if user is not None:
            logger.info(
                "Rattachement du compte existant %s à l'identité Entra ID %s",
                email, azure_object_id,
            )
            user.azure_object_id = azure_object_id

    if user is None:
        user = User(azure_object_id=azure_object_id, email=email, display_name=display_name)
        db.add(user)
    else:
        user.email = email
        user.display_name = display_name

    # Amorçage RBAC : sans ça, le tout premier utilisateur arrivait en `lecteur`
    # et personne ne pouvait promouvoir personne — /users exige déjà le rôle
    # admin, l'application était donc définitivement inadministrable.
    if email in settings.bootstrap_admin_emails and user.role is not UserRole.ADMIN:
        logger.warning("Promotion admin de %s via BOOTSTRAP_ADMIN_EMAILS", email)
        user.role = UserRole.ADMIN
        user.is_active = True

    user.last_login_at = datetime.now(timezone.utc)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        # Typiquement : l'email existe déjà sur un autre azure_object_id
        # (compte recréé côté Entra ID).
        logger.exception("Synchronisation du compte %s impossible", email)
        raise HTTPException(
            status_code=409,
            detail="Conflit lors de la synchronisation du compte utilisateur",
        )
    await db.refresh(user)

    admin_count = await db.execute(
        select(func.count())
        .select_from(User)
        .filter(User.role == UserRole.ADMIN, User.is_active.is_(True))
    )
    if admin_count.scalar_one() == 0:
        logger.warning(
            "Aucun administrateur actif en base : renseigner BOOTSTRAP_ADMIN_EMAILS "
            "dans .env puis relancer auth-api pour promouvoir un compte."
        )

    if not user.is_active:
        raise HTTPException(
            status_code=403,
            detail="Ce compte a été désactivé par un administrateur.",
        )

    token = create_access_token(user)

    response = RedirectResponse(url=f"{settings.frontend_url}/#token={quote(token)}")
    response.delete_cookie(key=_STATE_COOKIE, path=_STATE_COOKIE_PATH)
    return response


@router.get(
    "/me",
    response_model=UserOut,
    summary="Profil de l'utilisateur connecté",
    description=(
        "Retourne l'identité et le rôle de l'utilisateur associé au JWT fourni "
        "dans le header `Authorization`. Le rôle est relu en base à chaque "
        "appel : une rétrogradation prend effet immédiatement."
    ),
    response_description="Informations du compte courant.",
    responses={401: {"description": "Jeton absent, invalide ou expiré."}},
)
def me(current_user: User = Depends(get_current_user)):
    return current_user
