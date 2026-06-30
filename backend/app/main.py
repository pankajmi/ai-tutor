"""
FastAPI application — WebSocket entry point for the AI tutor.

Single endpoint:
    ws://localhost:8000/ws/{child_id}

On startup the database is initialised (pgvector → Alembic migrations → seeds).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket

from .db.database import async_session_factory, init_db
from .db.seed import seed_subjects
from .websocket_manager import WebSocketSessionManager

logger = logging.getLogger("ai_tutor.main")


# --------------------------------------------------------------------------- #
# Lifespan — database init on startup
# --------------------------------------------------------------------------- #


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Run once at startup: pgvector → Alembic → seed subjects."""
    logger.info("Starting up — initialising database...")
    await init_db()
    await seed_subjects(async_session_factory)
    logger.info("Startup complete.")
    yield
    logger.info("Shutting down.")


# --------------------------------------------------------------------------- #
# App instance
# --------------------------------------------------------------------------- #

app = FastAPI(
    title="AI Tutor",
    version="0.1.0",
    lifespan=lifespan,
)


# --------------------------------------------------------------------------- #
# WebSocket endpoint
# --------------------------------------------------------------------------- #


@app.websocket("/ws/{child_id}")
async def websocket_endpoint(websocket: WebSocket, child_id: str) -> None:
    """
    Single WebSocket connection per child session.

    Protocol:
      Client → Server:  session_start | speech | session_end
      Server → Client:  tutor_speech | whiteboard | emotion | error

    The session manager handles the full lifecycle: connect → process →
    disconnect / persist.
    """
    manager = WebSocketSessionManager(websocket, child_id)
    await manager.run()
