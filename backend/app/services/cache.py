"""
Cache de lecture sur Redis.

Le portefeuille se lit bien plus qu'il ne s'écrit : un tableau de bord ouvert
toute la journée redemande les mêmes compteurs à chaque navigation, alors que
les actions ne bougent que quelques fois par jour — et à l'import Excel. Avec
une base à ~250 ms d'aller-retour, recalculer à chaque fois se paie cher pour
un résultat identique.

Deux garde-fous rendent ce cache sûr :

- **La clé porte le périmètre de l'appelant.** Deux comptes ne partagent jamais
  une entrée : servir à l'un le tableau de bord de l'autre serait exactement la
  fuite que le cloisonnement cherche à empêcher.
- **Toute écriture invalide la version.** Plutôt que de supprimer des clés une
  à une — impossible à faire exhaustivement sans balayer Redis — un compteur de
  version est incrémenté et entre dans chaque clé. Les anciennes entrées
  deviennent inatteignables et expirent seules.

Redis indisponible n'est jamais fatal : on retombe silencieusement sur le
calcul direct, plus lent mais correct.
"""

import hashlib
import json
import logging
from typing import Any, Awaitable, Callable, TypeVar

from app.services.events import get_redis

logger = logging.getLogger("dsio.cache")

#: Durée de vie d'une entrée. Courte volontairement : l'invalidation par
#: version couvre les écritures passant par l'API, ce délai couvre le reste —
#: un import Excel écrit directement en base par un worker Celery.
DEFAULT_TTL_SECONDS = 120

#: Clé du compteur de version. Incrémenté à chaque écriture métier.
_VERSION_KEY = "dsio:cache:version"

T = TypeVar("T")


async def current_version() -> int:
    """Version courante du cache — 0 si Redis est injoignable."""
    try:
        valeur = await get_redis().get(_VERSION_KEY)
        return int(valeur) if valeur is not None else 0
    except Exception:
        logger.debug("Version de cache illisible, calcul direct", exc_info=True)
        return 0


async def invalidate() -> None:
    """Rend inatteignables toutes les entrées existantes."""
    try:
        await get_redis().incr(_VERSION_KEY)
    except Exception:
        # Une invalidation ratée servirait des données périmées pendant au plus
        # `DEFAULT_TTL_SECONDS`. L'incident doit rester visible sans casser
        # l'écriture, qui elle est déjà committée.
        logger.warning("Invalidation du cache impossible", exc_info=True)


def build_key(namespace: str, *, scope_token: str, params: dict[str, Any], version: int) -> str:
    """Clé stable : espace de noms, version, périmètre, paramètres.

    Les paramètres sont hachés plutôt que concaténés : ils contiennent des UUID
    et des dates, et une clé Redis de plusieurs centaines d'octets se paie à
    chaque lecture.
    """
    empreinte = hashlib.sha1(
        json.dumps(params, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]
    return f"dsio:cache:{version}:{namespace}:{scope_token}:{empreinte}"


async def get_or_set(
    namespace: str,
    *,
    scope_token: str,
    params: dict[str, Any],
    producer: Callable[[], Awaitable[T]],
    ttl: int = DEFAULT_TTL_SECONDS,
    serialize: Callable[[T], str],
    deserialize: Callable[[str], T],
) -> T:
    """Sert l'entrée en cache, ou la calcule et l'y range."""
    version = await current_version()
    cle = build_key(namespace, scope_token=scope_token, params=params, version=version)

    try:
        brut = await get_redis().get(cle)
        if brut is not None:
            return deserialize(brut)
    except Exception:
        logger.debug("Lecture de cache impossible, calcul direct", exc_info=True)

    valeur = await producer()

    try:
        await get_redis().set(cle, serialize(valeur), ex=ttl)
    except Exception:
        logger.debug("Écriture de cache impossible", exc_info=True)

    return valeur


# ─── Accès brut, hors versionnement ───
#
# Le compteur de version sert les agrégats métier : une écriture sur une action
# doit les périmer tous. Certaines entrées ne suivent pas ce cycle — le profil
# d'un compte, par exemple, ne change pas parce qu'une action a bougé. Elles
# passent donc par ces accesseurs, avec leur propre durée de vie et leur propre
# purge explicite.


async def get_raw(key: str) -> str | None:
    try:
        return await get_redis().get(key)
    except Exception:
        logger.debug("Lecture de cache impossible", exc_info=True)
        return None


async def set_raw(key: str, value: str, ttl: int) -> None:
    try:
        await get_redis().set(key, value, ex=ttl)
    except Exception:
        logger.debug("Écriture de cache impossible", exc_info=True)


async def delete_raw(*keys: str) -> None:
    if not keys:
        return
    try:
        await get_redis().delete(*keys)
    except Exception:
        logger.warning("Purge de cache impossible", exc_info=True)
