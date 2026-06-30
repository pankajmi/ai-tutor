"""
Database layer for the AI tutor: SQLAlchemy async models, async engine,
MemoryRepository, and startup initialization (pgvector, migrations, seeds).
"""
from .database import async_session_factory, engine, init_db
from .models import Base, Child, ErrorType, Mistake, Session, Subject, TopicMastery
from .repository import MemoryRepository
from .seed import SEED_SUBJECTS, seed_subjects

__all__ = [
    "Base",
    "Child",
    "ErrorType",
    "Mistake",
    "Session",
    "Subject",
    "TopicMastery",
    "MemoryRepository",
    "async_session_factory",
    "engine",
    "init_db",
    "seed_subjects",
    "SEED_SUBJECTS",
]
