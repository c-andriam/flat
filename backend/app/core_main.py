import os

from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis import asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_db
from app.routers import core as core_router
from app.routers import users as users_router
from app.services.health import perform_health_check_async

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

tags_metadata = [
    {
        "name": "projects",
        "description": "Gestion des projets suivis par la DSI (CRUD complet).",
    },
    {
        "name": "actions",
        "description": (
            "Actions rattachées à un projet, importées depuis Excel ou créées "
            "manuellement. Suivi de la progression, du statut et des retards."
        ),
    },
    {
        "name": "responsables",
        "description": (
            "Mapping entre les noms affichés dans les fichiers Excel et les "
            "adresses email réelles des responsables d'actions."
        ),
    },
    {
        "name": "logs",
        "description": (
            "Traces système en lecture seule : synchronisations Excel "
            "(SyncLog) et envois de relances par email (RelanceLog)."
        ),
    },
    {
        "name": "users",
        "description": (
            "Gestion des comptes applicatifs et des rôles (RBAC). "
            "Réservé aux administrateurs."
        ),
    },
    {
        "name": "monitoring",
        "description": "Endpoints de supervision (health checks).",
    },
]


app = FastAPI(
    title="DSIO - Project Management Core API",
    description=(
        "Microservice cœur de la plateforme DSIO (Trimeta Group) : gestion "
        "des projets, actions, responsables et comptes utilisateurs.\n\n"
        "### Authentification\n"
        "Les routes protégées attendent un header `Authorization: Bearer "
        "<token>` émis par le service `auth-api`."
    ),
    version="1.0.0",
    docs_url="/api/v1/docs",
    redoc_url="/api/v1/redoc",
    openapi_url="/api/v1/openapi.json",
    contact={"name": "DSI - Trimeta Group"},
    openapi_tags=tags_metadata,
    swagger_ui_parameters={"defaultModelsExpandDepth": -1},
)
app.include_router(core_router.router, prefix="/api/v1")
app.include_router(users_router.router, prefix="/api/v1")

# --- CORS ---
FRONTEND_ORIGIN = os.getenv("FRONTEND_URL", "http://localhost:8080")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get(
    "/health",
    tags=["monitoring"],
    summary="Vérifier l'état du service core",
    description=(
        "Endpoint de health check utilisé par les sondes de supervision "
        "(uptime, load balancer). Exécute un `SELECT 1` pour vérifier que "
        "PostgreSQL répond, sans faire échouer la requête si la base est "
        "injoignable."
    ),
    response_description="Statut du service et de la connexion à la base de données.",
    responses={
        200: {
            "content": {
                "application/json": {
                    "examples": {
                        "db_ok": {
                            "summary": "Base de données accessible",
                            "value": {
                                "status": "ok",
                                "service": "core-api",
                                "database": "connected",
                            },
                        },
                        "db_down": {
                            "summary": "Base de données injoignable",
                            "value": {
                                "status": "ok",
                                "service": "core-api",
                                "database": "unreachable (...)",
                            },
                        },
                    }
                }
            }
        }
    },
)
async def health_check(db: AsyncSession = Depends(get_async_db)):
    """Vérifie que l'API tourne et que PostgreSQL répond aux requêtes à la racine."""
    return await perform_health_check_async(db)


# NOTE : /api/v1/health est défini une seule fois, dans routers/core.py
# (monté avec le préfixe /api/v1). Une définition ici ferait doublon.
