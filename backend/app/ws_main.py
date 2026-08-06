import os

import redis.asyncio as redis
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

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
)

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))


@app.get(
    "/health",
    tags=["monitoring"],
    summary="Vérifier l'état du service temps réel",
    description="Endpoint de health check utilisé par les sondes de supervision (uptime, load balancer).",
    response_description="Statut du service.",
)
def health_check():
    return {"status": "ok", "service": "realtime-hub"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    Canal WebSocket temps réel.

    Non documenté dans Swagger (limitation OpenAPI). À la connexion, le
    serveur s'abonne au canal Redis Pub/Sub `dsio-events` et relaie chaque
    message reçu vers le client tel quel (texte brut).

    TODO: authentifier le client (token JWT) avant `accept()`, et définir un
    format de message structuré (JSON) pour permettre le routage côté client.
    """
    await websocket.accept()
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    pubsub = r.pubsub()
    await pubsub.subscribe("dsio-events")
    try:
        # TODO: relayer les messages Redis Pub/Sub vers le client WebSocket
        # et gérer l'authentification (token JWT) avant l'accept().
        async for message in pubsub.listen():
            if message["type"] == "message":
                await websocket.send_text(message["data"])
    except WebSocketDisconnect:
        pass
    finally:
        await pubsub.unsubscribe("dsio-events")
        await r.close()
