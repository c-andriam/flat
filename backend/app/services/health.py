import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger("core-api")


def perform_health_check(db: Session) -> dict:
    """Exécute la vérification de la base de données (SELECT 1)."""
    try:
        db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        logger.error("Health check DB failed: %s", e)
        db_status = "unreachable"

    return {
        "status": "ok",
        "service": "core-api",
        "database": db_status,
    }
