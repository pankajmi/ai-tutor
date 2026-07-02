"""
MemoryRepository — async data-access layer for per-child tutoring memory.

Provides subject-scoped read/write access to the tutoring database.
All methods expect caller to pass a session (unit-of-work pattern).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import func, select

from sqlalchemy.orm import joinedload

from .models import Child, ErrorType, Mistake, Session, Subject, TopicMastery

logger = logging.getLogger("ai_tutor.db.repository")


class MemoryRepository:
    """
    Read/write interface for per-child tutoring data, scoped by subject.

    Uses a session-per-call pattern — the caller manages the session
    lifecycle (typically via async context manager or dependency injection
    in FastAPI).
    """

    def __init__(self, session) -> None:
        self.session = session

    # ---------------------------------------------------------------- #
    # Child
    # ---------------------------------------------------------------- #

    async def get_child(self, child_id: str) -> Optional[Child]:
        """
        Fetch a child by ID.

        Returns the Child ORM object or None if not found.
        """
        stmt = select(Child).where(Child.id == child_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_child(self, child_id: str, name: str, grade: int) -> Child:
        """
        Create a new child profile. If the child already exists, return existing.
        """
        existing = await self.get_child(child_id)
        if existing:
            return existing
        child = Child(id=child_id, name=name, grade=grade)
        self.session.add(child)
        await self.session.commit()
        return child

    # ---------------------------------------------------------------- #
    # Weak topics
    # ---------------------------------------------------------------- #

    async def get_weak_topics(
        self,
        child_id: str,
        subject_id: Optional[str] = None,
        limit: int = 5,
    ) -> list[TopicMastery]:
        """
        Return the weakest (lowest-scoring) topics for a child.

        Args:
            child_id:  target child.
            subject_id:  if provided, scope to a single subject.
            limit:  max number of results (default 5).

        Returns list of TopicMastery rows sorted by score ascending.
        """
        stmt = (
            select(TopicMastery)
            .where(
                TopicMastery.child_id == child_id,
                TopicMastery.score < 0.6,  # "weak" threshold
            )
            .order_by(TopicMastery.score.asc())
            .limit(limit)
        )
        if subject_id is not None:
            stmt = stmt.where(TopicMastery.subject_id == subject_id)

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    # ---------------------------------------------------------------- #
    # Mistakes
    # ---------------------------------------------------------------- #

    async def log_mistake(
        self,
        child_id: str,
        session_id: str,
        subject_id: str,
        topic: str,
        error_type: str,
        description: str,
    ) -> Mistake:
        """
        Record a mistake for a child during a tutoring session.

        Args:
            child_id:   child who made the mistake.
            session_id: the tutoring session.
            subject_id: subject scope (e.g. "math", "science").
            topic:      specific topic within the subject (e.g. "fractions").
            error_type: one of "conceptual", "procedural", "careless".
            description: free-text description of what went wrong.

        Returns the newly created Mistake ORM object.
        """
        mistake = Mistake(
            child_id=child_id,
            session_id=session_id,
            subject_id=subject_id,
            topic=topic,
            error_type=ErrorType(error_type),
            description=description,
        )
        self.session.add(mistake)
        await self.session.commit()
        await self.session.refresh(mistake)
        return mistake

    # ---------------------------------------------------------------- #
    # Topic mastery
    # ---------------------------------------------------------------- #

    async def update_mastery(
        self,
        child_id: str,
        subject_id: str,
        topic: str,
        score_delta: float,
    ) -> TopicMastery:
        """
        Update (or create) a child's mastery score for a topic.

        The score is clamped to [0.0, 1.0]. score_delta is added to the
        current score (can be negative). On creation the score starts at
        max(0.0, score_delta) since there is no prior value.

        Args:
            child_id:   target child.
            subject_id: subject scope.
            topic:      specific topic (e.g. "fractions").
            score_delta:  change to apply (e.g. +0.1 for correct, -0.1 for mistake).

        Returns the updated (or newly created) TopicMastery ORM object.
        """
        stmt = select(TopicMastery).where(
            TopicMastery.child_id == child_id,
            TopicMastery.subject_id == subject_id,
            TopicMastery.topic == topic,
        )
        result = await self.session.execute(stmt)
        mastery = result.scalar_one_or_none()

        now = datetime.now(timezone.utc)

        if mastery is None:
            mastery = TopicMastery(
                child_id=child_id,
                subject_id=subject_id,
                topic=topic,
                score=max(0.0, min(1.0, score_delta)),
                attempts=1,
                last_tested_at=now,
            )
            self.session.add(mastery)
        else:
            mastery.score = max(0.0, min(1.0, mastery.score + score_delta))
            mastery.attempts += 1
            mastery.last_tested_at = now

        await self.session.commit()
        await self.session.refresh(mastery)
        return mastery

    # ---------------------------------------------------------------- #
    # Session summary
    # ---------------------------------------------------------------- #

    # ---------------------------------------------------------------- #
    # Sessions
    # ---------------------------------------------------------------- #

    async def get_sessions(
        self,
        child_id: str,
        subject_id: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """
        List recent sessions for a child, optionally filtered by subject.

        Returns list of dicts with id, subject_id, subject_name, started_at,
        ended_at, duration_minutes, topics_covered.
        """
        stmt = (
            select(Session)
            .options(joinedload(Session.subject))
            .where(Session.child_id == child_id, Session.ended_at.isnot(None))
            .order_by(Session.started_at.desc())
            .limit(limit)
        )
        if subject_id is not None:
            stmt = stmt.where(Session.subject_id == subject_id)

        result = await self.session.execute(stmt)
        sessions = result.unique().scalars().all()

        rows = []
        for s in sessions:
            duration = None
            if s.ended_at and s.started_at:
                delta = s.ended_at - s.started_at
                duration = round(delta.total_seconds() / 60, 1)

            rows.append({
                "id": s.id,
                "subject_id": s.subject_id,
                "subject_name": s.subject.name if s.subject else s.subject_id,
                "started_at": s.started_at.isoformat() if s.started_at else None,
                "ended_at": s.ended_at.isoformat() if s.ended_at else None,
                "duration_minutes": duration,
                "topics_covered": s.topics_covered or [],
            })
        return rows

    # ---------------------------------------------------------------- #
    # Topic mastery
    # ---------------------------------------------------------------- #

    async def get_mastery(
        self,
        child_id: str,
        subject_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """
        Get all topic mastery scores for a child.

        Returns list of dicts with topic, subject_id, score, attempts,
        last_tested_at.
        """
        stmt = (
            select(TopicMastery)
            .where(TopicMastery.child_id == child_id)
            .order_by(TopicMastery.topic.asc())
        )
        if subject_id is not None:
            stmt = stmt.where(TopicMastery.subject_id == subject_id)

        result = await self.session.execute(stmt)
        rows = result.scalars().all()

        return [
            {
                "topic": r.topic,
                "subject_id": r.subject_id,
                "score": r.score,
                "attempts": r.attempts,
                "last_tested_at": (
                    r.last_tested_at.isoformat() if r.last_tested_at else None
                ),
            }
            for r in rows
        ]

    # ---------------------------------------------------------------- #
    # Mistakes
    # ---------------------------------------------------------------- #

    async def get_mistakes(
        self,
        child_id: str,
        subject_id: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """
        List recent mistakes for a child, optionally filtered by subject.

        Returns list of dicts with id, session_id, subject_id, topic,
        error_type, description, timestamp.
        """
        stmt = (
            select(Mistake)
            .where(Mistake.child_id == child_id)
            .order_by(Mistake.timestamp.desc())
            .limit(limit)
        )
        if subject_id is not None:
            stmt = stmt.where(Mistake.subject_id == subject_id)

        result = await self.session.execute(stmt)
        rows = result.scalars().all()

        return [
            {
                "id": r.id,
                "session_id": r.session_id,
                "subject_id": r.subject_id,
                "topic": r.topic,
                "error_type": r.error_type.value,
                "description": r.description,
                "timestamp": r.timestamp.isoformat() if r.timestamp else None,
            }
            for r in rows
        ]

    async def get_session_summary(self, session_id: str) -> dict[str, Any]:
        """
        Build a summary dict for a completed tutoring session.

        Returns:
            {
                "session_id": ...,
                "child_id": ...,
                "subject_id": ...,
                "started_at": ...,
                "ended_at": ...,
                "topics_covered": [...],
                "total_mistakes": int,
                "mistakes_by_type": {"conceptual": N, "procedural": N, "careless": N},
            }

        Returns an empty dict if the session does not exist.
        """
        stmt = select(Session).where(Session.id == session_id)
        result = await self.session.execute(stmt)
        session = result.scalar_one_or_none()
        if session is None:
            return {}

        mistakes_stmt = select(Mistake).where(Mistake.session_id == session_id)
        mistakes_result = await self.session.execute(mistakes_stmt)
        mistakes = list(mistakes_result.scalars().all())

        error_counts: dict[str, int] = {}
        for m in mistakes:
            et = m.error_type.value
            error_counts[et] = error_counts.get(et, 0) + 1

        return {
            "session_id": session.id,
            "child_id": session.child_id,
            "subject_id": session.subject_id,
            "started_at": session.started_at.isoformat() if session.started_at else None,
            "ended_at": session.ended_at.isoformat() if session.ended_at else None,
            "topics_covered": session.topics_covered or [],
            "total_mistakes": len(mistakes),
            "mistakes_by_type": error_counts,
        }
