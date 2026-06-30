"""
CBSE subject seeds for the AI tutor.

Run once at startup to ensure the Subject table contains the standard
CBSE subjects. Idempotent — skips names that already exist.
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from .models import Subject

logger = logging.getLogger("ai_tutor.db.seed")

SEED_SUBJECTS = [
    "Math",
    "Science",
    "English",
    "Social Studies",
]


async def seed_subjects(session_factory) -> None:
    """
    Insert SEED_SUBJECTS that do not already exist. Idempotent.
    """
    async with session_factory() as session:
        existing = await session.execute(select(Subject.name))
        existing_names = {row[0] for row in existing}

        for name in SEED_SUBJECTS:
            if name not in existing_names:
                session.add(Subject(id=name.lower().replace(" ", "_"), name=name))
                logger.info("Seeded subject: %s", name)

        await session.commit()
