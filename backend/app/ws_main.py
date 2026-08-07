import logging
import os

import redis.asyncio as redis
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query

from app.services.security import decode_access_token

logger = logging.getLogger("realtime-hub")

tags_metadata = [
    {
        "name": "monitoring",
        "description": "Endpoints de supervision (health checks).",
    },
]

app = FastAPI(
    title="DSIO - Real-Time Hub",
    description=(
        "Microservice temps réel de la plateforme DSIO (Trimeta Group). "
        "Relaie les événements publiés sur le canal Redis Pub/Sub "
        "`dsio-events` vers les clients connectés via WebSocket "
        "(`GET /ws`, upgrade WebSocket).\n\n"
        "**Note :** la connexion WebSocket n'apparaît pas dans cette "
        "documentation Swagger — la spécification OpenAPI ne décrit que les "
        "routes HTTP classiques. Se connecter directement sur `wss://<host>/ws` "
        "(ou `ws://` en local) avec un client WebSocket."
    ),
    version="1.0.0",
    contact={"name": "DSI - Trimeta Group"},
    openapi_tags=tags_metadata,
    swagger_ui_parameters={"defaultModelsExpandDepth": -1},
    # Alignés sur le préfixe /api/v1/realtime que nginx route vers ce service.
    docs_url="/api/v1/realtime/docs",
    redoc_url="/api/v1/realtime/redoc",
    openapi_url="/api/v1/realtime/openapi.json",
)

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

# Pool Redis partagé (évite d'instancier un client par WebSocket)
redis_pool = redis.ConnectionPool.from_url(
    f"redis://{REDIS_HOST}:{REDIS_PORT}/0",
    decode_responses=True,
)


@app.get(
    "/health",
    tags=["monitoring"],
    summary="Vérifier l'état du service temps réel",
    description="Endpoint de health check interne (ex: probe container-à-container).",
    response_description="Statut du service.",
)
def health_check():
    return {"status": "ok", "service": "realtime-hub"}


@app.get(
    "/api/v1/realtime/health",
    tags=["monitoring"],
    summary="Vérifier l'état du service temps réel (accessible via le gateway)",
    description="Identique à /health, mais joignable depuis l'extérieur via le gateway nginx.",
    response_description="Statut du service.",
)
def health_check_public():
    return {"status": "ok", "service": "realtime-hub"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str = Query(None)):
    """
    Canal WebSocket temps réel.

    Non documenté dans Swagger (limitation OpenAPI). Le client doit passer
    son JWT via le query parameter `token` (ex: ws://host/ws?token=eyJ...).
    À la connexion, le serveur s'abonne au canal Redis Pub/Sub `dsio-events`
    et relaie chaque message reçu vers le client tel quel (texte brut).
    """
    # --- Authentification JWT obligatoire ---
    if not token:
        await websocket.close(code=1008, reason="Token manquant")
        return
    try:
        decode_access_token(token)
    except Exception:
        await websocket.close(code=1008, reason="Token invalide ou expiré")
        return

    await websocket.accept()
    r = redis.Redis(connection_pool=redis_pool)
    pubsub = r.pubsub()
    await pubsub.subscribe("dsio-events")
    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                await websocket.send_text(message["data"])
    except WebSocketDisconnect:
        pass
    finally:
        await pubsub.unsubscribe("dsio-events")
        await r.aclose()
