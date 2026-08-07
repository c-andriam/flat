from fastapi import FastAPI

from app.routers import auth as auth_router

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

app = FastAPI(
    title="DSIO - Auth & Identity API",
    description=(
        "Microservice d'authentification de la plateforme DSIO (Trimeta "
        "Group). Émet les JWT applicatifs utilisés par les autres services "
        "(`core-api`, `realtime-hub`) après connexion via Microsoft Entra ID."
    ),
    version="1.0.0",
    contact={"name": "DSI - Trimeta Group"},
    openapi_tags=tags_metadata,
    swagger_ui_parameters={"defaultModelsExpandDepth": -1},
    # Alignés sur le préfixe /api/v1/auth que nginx route vers ce service
    # (proxy_pass conserve l'URI complète telle quelle, cf. gateway/nginx.conf).
    docs_url="/api/v1/auth/docs",
    redoc_url="/api/v1/auth/redoc",
    openapi_url="/api/v1/auth/openapi.json",
)
app.include_router(auth_router.router, prefix="/api/v1")


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
