"""
FastAPI application — WebSocket entry point + REST API for the AI tutor.

Endpoints:
    ws://localhost:8000/ws/{child_id}
    GET /api/children/{child_id}/sessions
    GET /api/children/{child_id}/mastery?subject=math
    GET /api/children/{child_id}/mistakes?subject=math

On startup the database is initialised (pgvector → Alembic migrations → seeds).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Query, WebSocket

from .db.database import async_session_factory, init_db
from .db.repository import MemoryRepository
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

# Per-request DB session helper
async def _repo():
    sess = async_session_factory()
    try:
        yield MemoryRepository(sess)
    finally:
        await sess.close()


# --------------------------------------------------------------------------- #
# REST API — Parent Dashboard
# --------------------------------------------------------------------------- #


from fastapi import Depends, HTTPException


@app.get("/api/children/{child_id}/sessions")
async def get_sessions(
    child_id: str,
    subject: Optional[str] = Query(None),
    limit: int = Query(50),
    repo: MemoryRepository = Depends(_repo),
):
    """List recent tutoring sessions for a child."""
    rows = await repo.get_sessions(child_id, subject_id=subject, limit=limit)
    return {"sessions": rows}


@app.get("/api/children/{child_id}/mastery")
async def get_mastery(
    child_id: str,
    subject: Optional[str] = Query(None),
    repo: MemoryRepository = Depends(_repo),
):
    """Topic mastery scores, filterable by subject."""
    rows = await repo.get_mastery(child_id, subject_id=subject)
    return {"mastery": rows}


@app.get("/api/children/{child_id}/mistakes")
async def get_mistakes(
    child_id: str,
    subject: Optional[str] = Query(None),
    limit: int = Query(50),
    repo: MemoryRepository = Depends(_repo),
):
    """Recent mistake patterns, filterable by subject."""
    rows = await repo.get_mistakes(child_id, subject_id=subject, limit=limit)
    return {"mistakes": rows}


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
