"""
ProblemGeneratorAgent — stub implementation.

Returns a hardcoded practice problem appropriate for the active subject.
To be replaced with the full difficulty-adaptive Problem Generator in a
later build layer.
"""

from __future__ import annotations

import logging

from .models import DrawCommand, TutorResponse

logger = logging.getLogger("agents.stub_problem_gen")

_SUBJECT_PROBLEMS: dict[str, str] = {
    "math": (
        "If you have 3/4 of a pizza and eat 1/2 of it, "
        "how much pizza is left?"
    ),
    "science": (
        "A plant is placed in a dark closet for one week. "
        "What do you think will happen to the plant, and why?"
    ),
    "english": (
        "Which sentence is correct? "
        "A) 'She don't like apples.' "
        "B) 'She doesn't like apples.' "
        "Explain your choice."
    ),
    "social studies": (
        "The Indus Valley civilization had advanced drainage systems. "
        "Why do you think clean water and waste management were important "
        "for early cities?"
    ),
}

_DEFAULT_PROBLEM = "Here is a practice problem: can you think of an example related to what we're learning?"


def generate_problem(subject: str) -> TutorResponse:
    """Return a hardcoded practice problem for the given subject."""
    problem_text = _SUBJECT_PROBLEMS.get(subject.lower().strip(), _DEFAULT_PROBLEM)
    logger.info("ProblemGenerator (stub) — subject=%s", subject)

    return TutorResponse(
        spoken_text=problem_text,
        whiteboard_commands=[
            DrawCommand(
                type="write",
                delay_ms=0,
                content=problem_text,
                x=50,
                y=50,
            ),
        ],
        emotion_signal="neutral",
        topic_detected="practice",
    )
