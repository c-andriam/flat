import logging
from urllib.parse import quote_plus

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings

logger = logging.getLogger("dsio.database")

_PASSWORD = quote_plus(settings.postgres_password)
_DSN = (
    f"{settings.postgres_user}:{_PASSWORD}"
    f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
)

# URL synchrone pour psycopg2 (utilisée par Celery et Alembic)
SQLALCHEMY_DATABASE_URL = f"postgresql://{_DSN}"
# URL asynchrone pour asyncpg (utilisée par FastAPI)
SQLALCHEMY_DATABASE_URL_ASYNC = f"postgresql+asyncpg://{_DSN}"

_POOL_KWARGS = {
    "pool_size": settings.db_pool_size,
    "max_overflow": settings.db_max_overflow,
    # Le pooler Supabase coupe les connexions inactives : les recycler avant
    # évite les "server closed the connection unexpectedly" en production.
    "pool_recycle": settings.db_pool_recycle,
    "pool_pre_ping": True,
    "echo": settings.db_echo,
}

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"sslmode": "require"},
    **_POOL_KWARGS,
)

async_engine = create_async_engine(
    SQLALCHEMY_DATABASE_URL_ASYNC,
    connect_args={"ssl": "require"},
    **_POOL_KWARGS,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# expire_on_commit=False : en asynchrone, un attribut expiré déclenche un
# lazy-load hors contexte greenlet au moment de la sérialisation de la réponse
# (erreur MissingGreenlet). Garder les objets utilisables après commit.
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)

Base = declarative_base()


def get_db():
    """Dépendance FastAPI pour obtenir une session synchrone (Celery / Legacy)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


async def get_async_db():
    """Dépendance FastAPI pour obtenir une session asynchrone.

    Toute exception remontant du endpoint provoque un rollback explicite : sans
    ça la connexion retourne au pool avec une transaction ouverte, et la requête
    suivante qui la réutilise échoue en `InFailedSQLTransaction`.
    """
    async with AsyncSessionLocal() as db:
        try:
            yield db
        except Exception:
            await db.rollback()
            raise
