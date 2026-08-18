from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.database import async_engine
from app.logging_config import install_middlewares_and_handlers, setup_logging
from app.routers import auth as auth_router
from app.services.rate_limit import limiter

logger = setup_logging("auth-api")

tags_metadata = [
    {
        "name": "auth",
        "description": (
            "Authentification via Microsoft Entra ID (OAuth2 / OpenID Connect). "
            "Gère la redirection vers Microsoft, l'échange du code d'autorisation "
            "contre un JWT applicatif, et l'identité de l'utilisateur courant."
        ),
    },
    {
        "name": "monitoring",
        "description": "Endpoints de supervision (health checks).",
    },
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Échoue au démarrage plutôt qu'au premier login si la configuration
    # d'authentification est incomplète ou si SECRET_KEY est resté à la
    # valeur d'exemple : un conteneur qui refuse de démarrer se voit, un
    # 500 sur /callback à 18 h se découvre bien plus tard.
    _ = settings.secret_key
    if not settings.bootstrap_admin_emails:
        logger.warning(
            "BOOTSTRAP_ADMIN_EMAILS n'est pas renseigné : aucun compte ne sera "
            "promu administrateur automatiquement."
        )
    logger.info("auth-api démarré (env=%s)", settings.env)
    yield
    await async_engine.dispose()
    logger.info("auth-api arrêté proprement")


app = FastAPI(
    title="DSIO - Auth & Identity API",
    description=(
        "Microservice d'authentification de la plateforme DSIO (Trimeta "
        "Group). Émet les JWT applicatifs utilisés par les autres services "
        "(`core-api`, `realtime-hub`) après connexion via Microsoft Entra ID."
    ),
    version="1.1.0",
    contact={"name": "DSI - Trimeta Group"},
    openapi_tags=tags_metadata,
    swagger_ui_parameters={"defaultModelsExpandDepth": -1},
    # Alignés sur le préfixe /api/v1/auth que nginx route vers ce service
    # (proxy_pass conserve l'URI complète telle quelle, cf. gateway/nginx.conf).
    docs_url="/api/v1/auth/docs",
    redoc_url="/api/v1/auth/redoc",
    openapi_url="/api/v1/auth/openapi.json",
    lifespan=lifespan,
)

install_middlewares_and_handlers(app, "auth-api")

app.include_router(auth_router.router, prefix="/api/v1")

# --- CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
)

# --- Rate Limiting ---
# Le limiteur vient de app.services.rate_limit : c'est la même instance que
# celle utilisée par les décorateurs de routers/auth.py, sinon les compteurs
# sont indépendants et la limite annoncée n'est pas celle appliquée.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.get(
    "/health",
    tags=["monitoring"],
    summary="Vérifier l'état du service auth",
    description="Endpoint de health check interne (ex: probe container-à-container).",
    response_description="Statut du service.",
)
def health_check():
    return {"status": "ok", "service": "auth-api"}


@app.get(
    "/api/v1/auth/health",
    tags=["monitoring"],
    summary="Vérifier l'état du service auth (accessible via le gateway)",
    description="Identique à /health, mais joignable depuis l'extérieur via le gateway nginx.",
    response_description="Statut du service.",
)
def health_check_public():
    return {"status": "ok", "service": "auth-api"}
