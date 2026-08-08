import os
from urllib.parse import quote_plus

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base

POSTGRES_USER = os.environ["POSTGRES_USER"]
POSTGRES_PASSWORD = quote_plus(os.environ["POSTGRES_PASSWORD"])
POSTGRES_DB = os.environ["POSTGRES_DB"]
# Pas de défaut "postgres" : ce projet utilise Supabase (hôte distant),
# POSTGRES_HOST doit toujours être fourni explicitement via .env.
POSTGRES_HOST = os.environ["POSTGRES_HOST"]
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")

# URL synchrone pour psycopg2 (utilisée par Celery)
SQLALCHEMY_DATABASE_URL = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
# URL asynchrone pour asyncpg (utilisée par FastAPI)
SQLALCHEMY_DATABASE_URL_ASYNC = f"postgresql+asyncpg://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"sslmode": "require"},
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
)

async_engine = create_async_engine(
    SQLALCHEMY_DATABASE_URL_ASYNC,
    connect_args={"ssl": "require"},
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
AsyncSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=async_engine, class_=AsyncSession)

Base = declarative_base()


def get_db():
    """Dépendance FastAPI pour obtenir une session synchrone (Celery / Legacy)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


async def get_async_db():
    """Dépendance FastAPI pour obtenir une session asynchrone ultra-rapide."""
    async with AsyncSessionLocal() as db:
        yield db

