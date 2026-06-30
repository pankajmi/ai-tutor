"""
Shared Pydantic v2 data contracts for the AI tutor agents.

These models define the I/O contracts for the Tutor Agent, Whiteboard Agent,
and Orchestrator. All LLM-facing output must be validated via
.with_structured_output() — never accept raw LLM text where a structured
model is defined.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class DrawCommand(BaseModel):
    """A single drawing instruction for the whiteboard.

    type-specific fields are optional — only the fields relevant to the
    command's type should be populated:
      write:      content, x, y
      highlight:  target_text, color
      arrow:      from_x, from_y, to_x, to_y
      circle:     cx, cy, r
      clear:      (no extra fields)
      box:        x, y, width, height
    """

    type: Literal["write", "highlight", "arrow", "circle", "clear", "box"]
    delay_ms: int = 0

    content: str | None = None
    x: float | None = None
    y: float | None = None
    target_text: str | None = None
    color: str | None = None
    from_x: float | None = None
    from_y: float | None = None
    to_x: float | None = None
    to_y: float | None = None
    cx: float | None = None
    cy: float | None = None
    r: float | None = None
    width: float | None = None
    height: float | None = None


class ChildContext(BaseModel):
    """Per-child pedagogical context for the current session.

    Subject is the primary axis of variation — the Tutor Agent's prompt
    adapts to the subject, but the agent's LLM client and infrastructure
    remain fully subject-agnostic.
    """

    grade: int
    subject: str
    weak_topics: list[str] = []
    current_topic: str = ""


class Message(BaseModel):
    """A single turn in the tutoring conversation."""

    role: str  # "user" | "assistant"
    content: str


class TutorResponse(BaseModel):
    """Structured output from the Tutor Agent.

    The LLM produces this via .with_structured_output(). Every field
    must be populated meaningfully.
    """

    spoken_text: str
    whiteboard_commands: list[DrawCommand] | None = None
    emotion_signal: Literal["encouraging", "neutral", "redirecting"]
    topic_detected: str | None = None
