"""
Async database engine, session factory, and startup initializer.

init_db() should be called once at app startup to:
  1. Enable pgvector extension (safety net — docker/init.sql also does this)
  2. Run Alembic migrations
  3. Seed CBSE subjects
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from alembic.config import Config
from alembic import command
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

logger = logging.getLogger("ai_tutor.db.database")

DEFAULT_DATABASE_URL = "postgresql+asyncpg://tutor:tutor@localhost:5432/ai_tutor"

engine = create_async_engine(
    os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
    echo=False,
    pool_pre_ping=True,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def _enable_pgvector() -> None:
    """Enable pgvector extension if not already present."""
    async with engine.begin() as conn:
        await conn.execute(
            # Text() avoids needing a model import for a raw SQL statement.
            __import__("sqlalchemy").text("CREATE EXTENSION IF NOT EXISTS vector")
        )
    logger.info("pgvector extension enabled.")


def _run_alembic_migrations() -> None:
    """
    Run Alembic migrations synchronously. The migration env.py handles
    async engine setup internally via asyncio.run().
    """
    root_dir = Path(__file__).resolve().parents[3]  # up to project root
    alembic_ini = root_dir / "alembic.ini"
    if not alembic_ini.exists():
        logger.warning("alembic.ini not found at %s — skipping migrations.", alembic_ini)
        return
    cfg = Config(str(alembic_ini))
    command.upgrade(cfg, "head")
    logger.info("Alembic migrations applied (head).")


async def init_db() -> None:
    """
    Initialise database on startup: pgvector → Alembic → seeds.
    Safe to call multiple times (idempotent).
    """
    await _enable_pgvector()
    _run_alembic_migrations()
    # Seed subjects is handled by seed_subjects() called separately or
    # within the repository layer so it shares the same session lifecycle.
    logger.info("Database initialisation complete.")
