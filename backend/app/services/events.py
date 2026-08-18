"""
Publication d'événements temps réel sur le canal Redis Pub/Sub `dsio-events`.

Le client Redis est un singleton paresseux : le créer à l'import faisait que
chaque worker uvicorn ouvrait une connexion même sans jamais publier, et rien
ne la refermait à l'arrêt du process.
"""

import json
import logging
import uuid
from datetime import date, datetime
from enum import Enum

import redis
import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger("dsio.events")

EVENT_CHANNEL = "dsio-events"

_client: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _client
    if _client is None:
        _client = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def _json_default(obj):
    if isinstance(obj, uuid.UUID):
        return str(obj)
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError(f"Type non sérialisable : {type(obj)}")


async def publish_event(event_type: str, data: dict) -> None:
    """Publie un événement JSON — ne fait jamais échouer l'appelant."""
    try:
        message = json.dumps(
            {"type": event_type, "payload": data}, default=_json_default
        )
        await get_redis().publish(EVENT_CHANNEL, message)
    except Exception:
        # Redis indisponible ne doit pas casser une écriture métier déjà
        # committée, mais l'incident doit rester visible dans les logs.
        logger.warning(
            "Publication de l'événement %s impossible (Redis injoignable ?)",
            event_type,
            exc_info=True,
        )


_sync_client: redis.Redis | None = None


def publish_event_sync(event_type: str, data: dict) -> None:
    """Variante synchrone, pour les workers Celery.

    Les workers annonçaient dans leur docstring qu'ils publiaient un événement
    temps réel, mais aucun code ne le faisait : l'interface ne se rafraîchissait
    jamais après une synchronisation Excel.
    """
    global _sync_client
    try:
        if _sync_client is None:
            _sync_client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        message = json.dumps(
            {"type": event_type, "payload": data}, default=_json_default
        )
        _sync_client.publish(EVENT_CHANNEL, message)
    except Exception:
        logger.warning(
            "Publication de l'événement %s impossible (Redis injoignable ?)",
            event_type,
            exc_info=True,
        )
