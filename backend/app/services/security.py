import json
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
ROLE_DSIO = UserRole.DSIO.value

READ_ROLES = (ROLE_ADMIN, ROLE_RESPONSABLE_SI, ROLE_LECTEUR, ROLE_DSIO)
WRITE_ROLES = (ROLE_ADMIN, ROLE_RESPONSABLE_SI)
#: Qui peut ouvrir des disponibilites, arbitrer les demandes de rendez-vous et
#: voir l'identite des demandeurs.
#:
#: `admin` en est volontairement exclu : c'est un role d'administration des
#: comptes, pas un interlocuteur. L'y inclure lui aurait donne un agenda de
#: rendez-vous et, surtout, la lecture de l'objet des entretiens du DSIO.
#: Rien ne peut se bloquer pour autant, un admin pouvant promouvoir un compte
#: en `dsio`.
SLOT_OWNER_ROLES = (ROLE_DSIO,)


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

    user = await _charger_compte(db, user_id)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Compte introuvable ou désactivé",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


#: Espace de clés du profil de compte. Distinct du cache d'agrégats : une
#: écriture sur une action ne change pas le rôle de qui que ce soit.
_PROFIL_PREFIX = "dsio:auth:user:"


def profil_cache_key(user_id: uuid.UUID) -> str:
    return f"{_PROFIL_PREFIX}{user_id}"


async def purger_profil(user_id: uuid.UUID) -> None:
    """Rend effectif immédiatement un changement de rôle ou une désactivation."""
    from app.services.cache import delete_raw

    await delete_raw(profil_cache_key(user_id))


async def _charger_compte(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    """Profil du compte, mis en cache quelques secondes.

    Le rôle reste relu hors du jeton — un JWT vit plusieurs heures, s'y fier
    rendrait toute rétrogradation sans effet jusqu'à son expiration. Mais le
    relire en base à *chaque* requête coûtait un aller-retour complet, soit
    environ un tiers du temps de réponse sur une base distante.

    Compromis retenu : une fenêtre de `AUTH_CACHE_TTL_SECONDS` (30 s par
    défaut) pendant laquelle un changement fait directement en base n'est pas
    encore vu. Les changements passant par l'API purgent l'entrée
    explicitement, et prennent donc effet immédiatement. Mettre le réglage à 0
    rétablit la relecture systématique.
    """
    from app.services.cache import get_raw, set_raw

    ttl = settings.auth_cache_ttl_seconds
    cle = profil_cache_key(user_id)

    if ttl > 0:
        brut = await get_raw(cle)
        if brut is not None:
            donnees = json.loads(brut)
            # Instance détachée : seuls des attributs scalaires sont lus en
            # aval, aucune relation n'est parcourue.
            #
            # Tous les champs de `UserOut` sont restitués, y compris ceux que
            # l'autorisation n'utilise pas : /auth/me sérialise l'objet entier,
            # et un `created_at` manquant y provoquait une erreur 500 dès le
            # deuxième appel — le premier passant encore par la base.
            return User(
                id=user_id,
                azure_object_id=donnees["azure_object_id"],
                email=donnees["email"],
                display_name=donnees["display_name"],
                role=UserRole(donnees["role"]),
                is_active=donnees["is_active"],
                created_at=datetime.fromisoformat(donnees["created_at"]),
                last_login_at=(
                    datetime.fromisoformat(donnees["last_login_at"])
                    if donnees["last_login_at"]
                    else None
                ),
            )

    result = await db.execute(select(User).filter(User.id == user_id))
    user = result.scalars().first()

    if user is not None and ttl > 0:
        await set_raw(
            cle,
            json.dumps(
                {
                    "azure_object_id": user.azure_object_id,
                    "email": user.email,
                    "display_name": user.display_name,
                    "role": user.role.value,
                    "is_active": user.is_active,
                    "created_at": user.created_at.isoformat(),
                    "last_login_at": (
                        user.last_login_at.isoformat() if user.last_login_at else None
                    ),
                }
            ),
            ttl,
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
require_slot_owner = Depends(require_role(*SLOT_OWNER_ROLES))
