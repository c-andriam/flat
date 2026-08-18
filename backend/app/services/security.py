import uuid
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.config import ConfigError, settings
from app.database import get_async_db
from app.models.user import User, UserRole

bearer_scheme = HTTPBearer()

# Rôles applicatifs, groupés par niveau d'accès pour éviter de recopier des
# listes de chaînes dans chaque routeur (et de se tromper de nom d'un rôle).
ROLE_ADMIN = UserRole.ADMIN.value
ROLE_RESPONSABLE_SI = UserRole.RESPONSABLE_SI.value
ROLE_LECTEUR = UserRole.LECTEUR.value

READ_ROLES = (ROLE_ADMIN, ROLE_RESPONSABLE_SI, ROLE_LECTEUR)
WRITE_ROLES = (ROLE_ADMIN, ROLE_RESPONSABLE_SI)


def create_access_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "role": user.role.value,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
        # Identifiant unique du jeton : nécessaire pour une future révocation
        # (liste noire Redis) et pour tracer un jeton dans les logs.
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def decode_access_token(token: str) -> dict:
    try:
        secret_key = settings.secret_key
    except ConfigError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Service d'authentification mal configuré",
        )
    try:
        return jwt.decode(
            token,
            secret_key,
            algorithms=[settings.algorithm],
            # Un jeton sans exp ni sub est rejeté au lieu d'être accepté
            # comme un jeton valide sans expiration.
            options={"require": ["exp", "sub"]},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalide ou expiré",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_async_db),
) -> User:
    """Dépendance FastAPI pour protéger les routes core-api/realtime-hub."""
    payload = decode_access_token(credentials.credentials)
    try:
        user_id = uuid.UUID(payload.get("sub"))
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalide ou expiré",
            headers={"WWW-Authenticate": "Bearer"},
        )

    result = await db.execute(select(User).filter(User.id == user_id))
    user = result.scalars().first()
    # Le rôle est relu en base à chaque requête (et non pris dans le jeton) :
    # une révocation ou une rétrogradation prend effet immédiatement, sans
    # attendre l'expiration du JWT.
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Compte introuvable ou désactivé",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_role(*allowed_roles: str):
    """Dépendance factory pour restreindre une route à certains rôles (RBAC)."""

    async def _check(user: User = Depends(get_current_user)) -> User:
        if user.role.value not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Permission refusée : rôle requis "
                    f"{' ou '.join(allowed_roles)}, rôle actuel {user.role.value}."
                ),
            )
        return user

    return _check


# Dépendances prêtes à l'emploi, réutilisables dans `dependencies=[...]`.
require_authenticated = Depends(get_current_user)
require_reader = Depends(require_role(*READ_ROLES))
require_writer = Depends(require_role(*WRITE_ROLES))
require_admin = Depends(require_role(ROLE_ADMIN))
