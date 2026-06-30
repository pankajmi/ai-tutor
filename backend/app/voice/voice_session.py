"""
VoiceSession — ties together the voice I/O loop (VoiceLoop), the LangGraph
Orchestrator (LLM), and an optional WebSocket bridge for whiteboard commands.

Usage (CLI run.py entrypoint):
    session = VoiceSession(subject="Math", topic="Fractions")
    await session.start()
    # Talk to the tutor...
    await session.stop()

Usage (with WebSocket whiteboard bridge):
    from app.websocket_manager import WebSocketSessionManager

    ws_manager = WebSocketSessionManager(websocket, child_id)
    session = VoiceSession(
        child_id="abc",
        subject="Math",
        topic="Fractions",
        whiteboard_bridge=ws_manager.send_whiteboard,
    )
    # Run both concurrently:
    await asyncio.gather(session.run(), ws_manager.run())
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Callable, Optional

from agents.orchestrator import Orchestrator, SessionState

from .voice_loop import VoiceLoop, VoiceLoopConfig

logger = logging.getLogger("ai_tutor.voice.session")

WhiteboardBridge = Callable[[list[dict]], None]


@dataclass
class VoiceSessionConfig:
    subject: str = "Math"
    topic: str = ""
    child_id: str = "local_child"
    voice_loop_config: VoiceLoopConfig = field(default_factory=VoiceLoopConfig)


class VoiceSession:
    """
    Complete voice-driven tutoring session.

    Wires the VoiceLoop (mic → STT → TTS → speaker) to the LangGraph
    Orchestrator for fully local, hands-free tutoring.

    Optionally accepts a `whiteboard_bridge` callable that receives
    whiteboard commands dicts — for example, to relay commands to a
    connected browser via WebSocket.
    """

    def __init__(
        self,
        config: Optional[VoiceSessionConfig] = None,
        whiteboard_bridge: Optional[WhiteboardBridge] = None,
    ) -> None:
        self.config = config or VoiceSessionConfig()
        self.whiteboard_bridge = whiteboard_bridge

        self._orchestrator = Orchestrator()

        self.session: SessionState = SessionState(
            child_id=self.config.child_id,
            subject=self.config.subject,
            current_topic=self.config.topic,
            conversation_history=[],
            current_mode="teaching",
            last_tutor_response=None,
            pending_whiteboard_commands=[],
        )

        self._voice_loop: Optional[VoiceLoop] = None
        self._running = False
        self._task: Optional[asyncio.Task] = None

    # ---------------------------------------------------------------- #
    # Lifecycle
    # ---------------------------------------------------------------- #

    async def start(self) -> None:
        """Start voice capture, begin tutoring session."""
        self._voice_loop = VoiceLoop(
            on_user_speech=self._on_user_speech,
            config=self.config.voice_loop_config,
        )
        await self._voice_loop.start()

        self._running = True
        self._task = asyncio.create_task(self._run())

        # Greeting
        greeting = (
            f"Hi there! I'm Nova, your tutor. "
            f"Let's explore {self.config.topic or self.config.subject} together. "
            f"What would you like to learn about?"
        )
        await self._voice_loop.speak(greeting)

        logger.info(
            "VoiceSession started: subject=%s topic=%s",
            self.config.subject, self.config.topic,
        )

    async def stop(self) -> None:
        """Stop voice capture and clean up."""
        self._running = False
        if self._voice_loop is not None:
            await self._voice_loop.stop()

        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        # Persist session
        from app.db.database import async_session_factory
        from app.db.models import Session as DbSession
        from app.db.models import Child
        from datetime import datetime, timezone
        import uuid

        try:
            async with async_session_factory() as db_sess:
                child = await db_sess.get(Child, self.config.child_id)
                if child is None:
                    db_sess.add(
                        Child(
                            id=self.config.child_id,
                            name="Local Child",
                            grade=5,
                        )
                    )
                    await db_sess.commit()

                db_session = DbSession(
                    id=str(uuid.uuid4()),
                    child_id=self.config.child_id,
                    subject_id=self.config.subject.lower().replace(" ", "_"),
                    ended_at=datetime.now(timezone.utc),
                    topics_covered=(
                        [self.config.topic] if self.config.topic else []
                    ),
                )
                async with db_sess.begin():
                    db_sess.add(db_session)
                logger.info("Session persisted to DB.")
        except Exception:
            logger.exception("Failed to persist session, continuing.")

        logger.info("VoiceSession stopped.")

    # ---------------------------------------------------------------- #
    # Internal
    # ---------------------------------------------------------------- #

    async def _on_user_speech(self, text: str) -> None:
        """
        Called by VoiceLoop when the child finishes speaking.
        Runs the orchestrator and speaks the response.
        """
        logger.info("Processing: %.80s", text)

        try:
            self.session = await self._orchestrator.ainvoke(text, self.session)
        except Exception:
            logger.exception("Orchestrator error")
            await self._voice_loop.speak(
                "I'm having trouble thinking right now. Could you try again?"
            )
            return

        response = self.session.get("last_tutor_response")
        if response is None:
            return

        # Speak the response
        if response.spoken_text:
            await self._voice_loop.speak(response.spoken_text)

        # Relay whiteboard commands if a bridge is configured
        if self.whiteboard_bridge and response.whiteboard_commands:
            try:
                self.whiteboard_bridge(
                    [c.model_dump() for c in response.whiteboard_commands]
                )
            except Exception:
                logger.exception("Whiteboard bridge error")

    async def _run(self) -> None:
        """
        Main loop: keep running until stopped.
        The real work happens in VoiceLoop's internal loops.
        """
        while self._running:
            await asyncio.sleep(0.1)
