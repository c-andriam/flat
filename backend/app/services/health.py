import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("dsio.health")


def _payload(service: str, db_status: str) -> tuple[dict, int]:
    healthy = db_status == "connected"
    body = {
        "status": "ok" if healthy else "degraded",
        "service": service,
        "database": db_status,
    }
    # 503 quand la base est injoignable : un load balancer doit sortir
    # l'instance du pool, or un corps `{"status": "ok"}` avec un HTTP 200
    # lui faisait croire que tout allait bien.
    return body, 200 if healthy else 503


async def perform_health_check_async(
    db: AsyncSession, service: str = "core-api"
) -> tuple[dict, int]:
    """Vérification base de données (SELECT 1) — version asynchrone."""
    try:
        await db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as exc:
        logger.error("Health check DB failed: %s", exc)
        db_status = "unreachable"
    return _payload(service, db_status)
