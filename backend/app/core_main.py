from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_engine, get_async_db
from app.logging_config import install_middlewares_and_handlers, setup_logging
from app.routers import core as core_router
from app.routers import relances as relances_router
from app.routers import reports as reports_router
from app.routers import slots as slots_router
from app.routers import users as users_router
from app.services.events import close_redis
from app.services.health import perform_health_check_async

logger = setup_logging("core-api")

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
        "name": "reports",
        "description": (
            "Rapports consolides : portefeuille, projet, charge par "
            "responsable, prevision hebdomadaire des echeances."
        ),
    },
    {
        "name": "relances",
        "description": (
            "Rappels par email aux responsables (Outlook / Microsoft Graph) : "
            "apercu du message, envoi individuel ou campagne. Les actions "
            "concernees sont deduites de l'identifiant du responsable et de "
            "la nature du rappel."
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
        "description": "Endpoints de supervision (health checks), accessibles sans jeton.",
    },
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("core-api démarré (env=%s)", settings.env)
    yield
    # Fermeture explicite : sans ça, les connexions Redis et le pool
    # PostgreSQL restaient ouverts côté serveur jusqu'à leur expiration.
    await close_redis()
    await async_engine.dispose()
    logger.info("core-api arrêté proprement")


app = FastAPI(
    title="DSIO - Project Management Core API",
    description=(
        "Microservice cœur de la plateforme DSIO (Trimeta Group) : gestion "
        "des projets, actions, responsables et comptes utilisateurs.\n\n"
        "### Authentification\n"
        "Toutes les routes métier attendent un header `Authorization: Bearer "
        "<token>` émis par le service `auth-api` (`/api/v1/auth/login`).\n\n"
        "### Rôles (RBAC)\n"
        "- `lecteur` : lecture des projets, actions et responsables ;\n"
        "- `responsable_si` : lecture + écriture, et accès aux journaux ;\n"
        "- `admin` : idem, plus la gestion des comptes (`/users`).\n\n"
        "Seuls les health checks sont ouverts sans jeton."
    ),
    version="1.1.0",
    docs_url="/api/v1/docs",
    redoc_url="/api/v1/redoc",
    openapi_url="/api/v1/openapi.json",
    contact={"name": "DSI - Trimeta Group"},
    openapi_tags=tags_metadata,
    swagger_ui_parameters={"defaultModelsExpandDepth": -1},
    lifespan=lifespan,
)

install_middlewares_and_handlers(app, "core-api")

app.include_router(core_router.router, prefix="/api/v1")
app.include_router(reports_router.router, prefix="/api/v1")
app.include_router(relances_router.router, prefix="/api/v1")
app.include_router(users_router.router, prefix="/api/v1")
app.include_router(slots_router.router, prefix="/api/v1")

# --- CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    # Sans ça, un client JavaScript ne peut pas lire le total de pagination.
    expose_headers=["X-Total-Count", "X-Request-ID"],
)


@app.get(
    "/health",
    tags=["monitoring"],
    summary="Vérifier l'état du service core",
    description=(
        "Endpoint de health check utilisé par les sondes de supervision "
        "(uptime, load balancer). Exécute un `SELECT 1` pour vérifier que "
        "PostgreSQL répond, et renvoie 503 si la base est injoignable."
    ),
    response_description="Statut du service et de la connexion à la base de données.",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "status": "ok",
                        "service": "core-api",
                        "database": "connected",
                    }
                }
            }
        },
        503: {
            "description": "Base de données injoignable.",
            "content": {
                "application/json": {
                    "example": {
                        "status": "degraded",
                        "service": "core-api",
                        "database": "unreachable",
                    }
                }
            },
        },
    },
)
async def health_check(response: Response, db: AsyncSession = Depends(get_async_db)):
    """Vérifie que l'API tourne et que PostgreSQL répond aux requêtes."""
    body, status_code = await perform_health_check_async(db, "core-api")
    response.status_code = status_code
    return body


# NOTE : /api/v1/health est défini une seule fois, dans routers/core.py
# (monté avec le préfixe /api/v1). Une définition ici ferait doublon.
