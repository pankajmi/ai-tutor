"""
MistakePatternAgent — stub implementation.

Logs to console as a placeholder for the real background classifier
(qwen2.5:1.5b) that will analyse mistakes for conceptual / procedural /
careless classification. This stub runs asynchronously and does not
block the response flow.
"""

from __future__ import annotations

import asyncio
import logging

from .models import Message, TutorResponse

logger = logging.getLogger("agents.stub_mistake_pattern")


async def analyse_turn(
    child_message: str,
    tutor_response: TutorResponse | None,
    conversation_history: list[Message],
    subject: str,
) -> None:
    """
    Analyse the latest turn for mistake patterns. Non-blocking (fire-and-forget).

    In the stub, this simply logs the turn to console. The real implementation
    will invoke qwen2.5:1.5b to classify errors as conceptual / procedural /
    careless and record them via the MemoryRepository.
    """
    if tutor_response is None:
        return

    # Simulate a tiny async delay (network / model inference in real impl).
    await asyncio.sleep(0)

    logger.info(
        "[MistakePattern stub] subject=%s last_tutor_emotion=%s message_len=%d history_turns=%d",
        subject,
        tutor_response.emotion_signal,
        len(child_message),
        len(conversation_history),
    )
