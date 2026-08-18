"""
Journalisation et gestion d'erreurs communes aux trois services FastAPI.

Avant : une exception non gérée dans un endpoint renvoyait un 500 vide et rien
n'apparaissait dans les logs (uvicorn n'imprime la trace que sur le logger
racine, jamais configuré). Impossible de diagnostiquer un incident a posteriori.
"""

import logging
import sys
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import settings

_CONFIGURED = False


def setup_logging(service_name: str) -> logging.Logger:
    """Configure le logger racine une seule fois par process."""
    global _CONFIGURED
    if not _CONFIGURED:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S%z",
            )
        )
        root = logging.getLogger()
        root.handlers = [handler]
        root.setLevel(getattr(logging, settings.log_level, logging.INFO))
        _CONFIGURED = True
    return logging.getLogger(service_name)


def install_middlewares_and_handlers(app: FastAPI, service_name: str) -> None:
    """Ajoute le suivi de requête (request-id + durée) et le filet 500."""
    logger = logging.getLogger(service_name)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        request.state.request_id = request_id
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            elapsed_ms = (time.perf_counter() - started) * 1000
            logger.exception(
                "request_id=%s %s %s -> 500 (%.1f ms)",
                request_id, request.method, request.url.path, elapsed_ms,
            )
            return JSONResponse(
                status_code=500,
                content={
                    "detail": "Erreur interne du serveur",
                    "request_id": request_id,
                },
                headers={"X-Request-ID": request_id},
            )
        elapsed_ms = (time.perf_counter() - started) * 1000
        response.headers["X-Request-ID"] = request_id
        # Les health checks sont interrogés toutes les 5 s : les journaliser en
        # INFO noierait tout le reste.
        level = logging.DEBUG if request.url.path.endswith("/health") else logging.INFO
        logger.log(
            level,
            "request_id=%s %s %s -> %s (%.1f ms)",
            request_id, request.method, request.url.path,
            response.status_code, elapsed_ms,
        )
        return response
