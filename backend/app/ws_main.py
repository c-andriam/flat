import asyncio
import contextlib
from contextlib import asynccontextmanager

import redis.asyncio as redis
from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.logging_config import install_middlewares_and_handlers, setup_logging
from app.services.events import EVENT_CHANNEL
from app.services.security import decode_access_token

logger = setup_logging("realtime-hub")

# Ping applicatif : sans trafic, nginx (proxy_read_timeout) et les pare-feux
# coupent une WebSocket inactive. Un ping régulier maintient le tunnel ouvert
# et détecte un client parti sans FIN propre.
PING_INTERVAL_SECONDS = 25

tags_metadata = [
    {
        "name": "monitoring",
        "description": "Endpoints de supervision (health checks).",
    },
]

# Pool Redis partagé (évite d'instancier un client par WebSocket)
redis_pool = redis.ConnectionPool.from_url(settings.redis_url, decode_responses=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("realtime-hub démarré (env=%s)", settings.env)
    yield
    await redis_pool.disconnect()
    logger.info("realtime-hub arrêté proprement")


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
    version="1.1.0",
    contact={"name": "DSI - Trimeta Group"},
    openapi_tags=tags_metadata,
    swagger_ui_parameters={"defaultModelsExpandDepth": -1},
    # Alignés sur le préfixe /api/v1/realtime que nginx route vers ce service.
    docs_url="/api/v1/realtime/docs",
    redoc_url="/api/v1/realtime/redoc",
    openapi_url="/api/v1/realtime/openapi.json",
    lifespan=lifespan,
)

install_middlewares_and_handlers(app, "realtime-hub")

# --- CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
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


async def _aclose(obj) -> None:
    """Ferme un objet redis-py, quelle que soit la version installée.

    `aclose()` n'existe que depuis redis 5.0.1 ; sur les versions antérieures
    la méthode s'appelle `close()`. Sans ce repli, la fermeture échouait
    silencieusement et la connexion restait ouverte côté serveur.
    """
    closer = getattr(obj, "aclose", None) or getattr(obj, "close", None)
    if closer is not None:
        await closer()


async def _drain_client(websocket: WebSocket) -> None:
    """Consomme (et ignore) les messages entrants.

    Le hub est unidirectionnel, mais sans lecture active Starlette ne voit
    jamais la trame de fermeture envoyée par le navigateur : la tâche restait
    bloquée dans `pubsub.listen()` et l'abonnement Redis n'était libéré qu'au
    prochain message publié — voire jamais.
    """
    while True:
        await websocket.receive_text()


async def _relay_events(websocket: WebSocket, pubsub) -> None:
    """Relaie les messages Redis vers le client, avec ping périodique."""
    while True:
        message = await pubsub.get_message(
            ignore_subscribe_messages=True, timeout=PING_INTERVAL_SECONDS
        )
        if message is None:
            # Aucun événement pendant l'intervalle : on maintient la connexion.
            await websocket.send_text('{"type":"ping"}')
            continue
        await websocket.send_text(message["data"])


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
        claims = decode_access_token(token)
    except Exception:
        await websocket.close(code=1008, reason="Token invalide ou expiré")
        return

    await websocket.accept()
    client = redis.Redis(connection_pool=redis_pool)
    pubsub = client.pubsub()
    await pubsub.subscribe(EVENT_CHANNEL)
    logger.info("WebSocket ouverte pour sub=%s", claims.get("sub"))

    relay = asyncio.create_task(_relay_events(websocket, pubsub))
    drain = asyncio.create_task(_drain_client(websocket))
    try:
        # La première tâche qui se termine (client parti, ou erreur de relais)
        # met fin à la session : on annule l'autre au lieu de la laisser
        # tourner sur une socket morte.
        done, pending = await asyncio.wait(
            {relay, drain}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        for task in done:
            exc = task.exception()
            if exc is not None and not isinstance(exc, WebSocketDisconnect):
                raise exc
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Erreur sur la WebSocket sub=%s", claims.get("sub"))
    finally:
        for task in (relay, drain):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        # Libère l'abonnement puis la connexion, y compris quand le client
        # disparaît brutalement — c'est cette fuite qui saturait le pool Redis.
        with contextlib.suppress(Exception):
            await pubsub.unsubscribe(EVENT_CHANNEL)
            await _aclose(pubsub)
        with contextlib.suppress(Exception):
            await _aclose(client)
        logger.info("WebSocket fermée pour sub=%s", claims.get("sub"))
