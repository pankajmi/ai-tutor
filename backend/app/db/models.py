"""
SQLAlchemy async ORM models for the per-child tutoring memory system.

Schema covers all subjects (Math, Science, English, Social Studies) with
subject_id as a first-class FK throughout. Error types use the generalized
taxonomy: conceptual / procedural / careless.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, DateTime, Enum, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class ErrorType(str, enum.Enum):
    """Subject-agnostic mistake taxonomy.

    "procedural" generalizes what was "calculation" in a math-only schema:
    a grammar rule misapplied in English, a step skipped in a science
    experiment — any case where the child knows the concept but misapplies it.
    """

    conceptual = "conceptual"
    procedural = "procedural"
    careless = "careless"


class Child(Base):
    __tablename__ = "child"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    grade: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    sessions: Mapped[list["Session"]] = relationship(back_populates="child")
    mistakes: Mapped[list["Mistake"]] = relationship(back_populates="child")
    topic_masteries: Mapped[list["TopicMastery"]] = relationship(back_populates="child")


class Subject(Base):
    __tablename__ = "subject"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)

    sessions: Mapped[list["Session"]] = relationship(back_populates="subject")
    mistakes: Mapped[list["Mistake"]] = relationship(back_populates="subject")
    topic_masteries: Mapped[list["TopicMastery"]] = relationship(back_populates="subject")


class Session(Base):
    __tablename__ = "session"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    child_id: Mapped[str] = mapped_column(
        String, ForeignKey("child.id"), nullable=False
    )
    subject_id: Mapped[str] = mapped_column(
        String, ForeignKey("subject.id"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    topics_covered: Mapped[Optional[list[Any]]] = mapped_column(JSON)

    child: Mapped["Child"] = relationship(back_populates="sessions")
    subject: Mapped["Subject"] = relationship(back_populates="sessions")
    mistakes: Mapped[list["Mistake"]] = relationship(back_populates="session")


class Mistake(Base):
    __tablename__ = "mistake"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    child_id: Mapped[str] = mapped_column(
        String, ForeignKey("child.id"), nullable=False
    )
    session_id: Mapped[str] = mapped_column(
        String, ForeignKey("session.id"), nullable=False
    )
    subject_id: Mapped[str] = mapped_column(
        String, ForeignKey("subject.id"), nullable=False
    )
    topic: Mapped[str] = mapped_column(String, nullable=False)
    error_type: Mapped[ErrorType] = mapped_column(
        Enum(ErrorType, name="error_type", create_constraint=True), nullable=False
    )
    description: Mapped[str] = mapped_column(String, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    child: Mapped["Child"] = relationship(back_populates="mistakes")
    session: Mapped["Session"] = relationship(back_populates="mistakes")
    subject: Mapped["Subject"] = relationship(back_populates="mistakes")


class TopicMastery(Base):
    __tablename__ = "topic_mastery"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    child_id: Mapped[str] = mapped_column(
        String, ForeignKey("child.id"), nullable=False
    )
    subject_id: Mapped[str] = mapped_column(
        String, ForeignKey("subject.id"), nullable=False
    )
    topic: Mapped[str] = mapped_column(String, nullable=False)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    last_tested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)

    child: Mapped["Child"] = relationship(back_populates="topic_masteries")
    subject: Mapped["Subject"] = relationship(back_populates="topic_masteries")
