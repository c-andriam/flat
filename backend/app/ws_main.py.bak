import os

import redis.asyncio as redis
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

app = FastAPI(title="DSIO - Real-Time Hub")

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))


@app.get("/health")
def health_check():
    return {"status": "ok", "service": "realtime-hub"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
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
