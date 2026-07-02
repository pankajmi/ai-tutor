"""
WebSocket session manager for the AI tutor.

Handles text (JSON) and binary (audio) frames over a single WebSocket.
Wires the orchestrator to voice I/O (STT/TTS) via a VoiceLoop when the
browser sends audio frames. JSON messages (speech, whiteboard, emotion)
are forwarded independently so the frontend can process them in parallel.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

import numpy as np
import redis.asyncio as aioredis
from fastapi import WebSocket, WebSocketDisconnect

from agents.models import Message
from agents.orchestrator import Orchestrator, SessionState

from .db.database import async_session_factory
from .db.models import Child, Session as DbSession
from .db.seed import seed_subjects
from .voice.audio_base import AudioSink
from .voice.voice_loop import VoiceLoop, VoiceLoopConfig
from .voice.voice_session import VoiceSessionConfig

logger = logging.getLogger("ai_tutor.ws_manager")

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")


def _channel_speech(child_id: str) -> str:
    return f"tutor:{child_id}:speech"


def _channel_whiteboard(child_id: str) -> str:
    return f"tutor:{child_id}:whiteboard"


# --------------------------------------------------------------------------- #
# Session manager (one instance per WebSocket connection)
# --------------------------------------------------------------------------- #


class WebSocketSessionManager:
    """
    Manages a single WebSocket session for one child, supporting both
    text (JSON) and binary (audio) frames.

    When the browser sends binary audio frames, a voice pipeline is
    lazily initialized (WebSocketSource → VoiceInputManager → Whisper →
    Orchestrator → Kokoro → WebSocketSink). Text-only sessions skip the
    voice pipeline and receive JSON messages only.
    """

    def __init__(self, websocket: WebSocket, child_id: str) -> None:
        self.ws = websocket
        self.child_id = child_id

        self.orchestrator = Orchestrator()
        self.session: Optional[SessionState] = None
        self.db_session_id: Optional[str] = None
        self.subjects_visited: list[str] = []

        # Voice pipeline (lazy)
        self._voice_loop: Optional[VoiceLoop] = None
        self._ws_source: Optional["WebSocketSource"] = None
        self._ws_sink: Optional["WebSocketSink"] = None
        self._voice_enabled = False
        self._frame_count = 0  # debug

        # Redis Pub/Sub
        self._redis: Optional[aioredis.Redis] = None
        self._pubsub: Optional[aioredis.client.PubSub] = None
        self._listener_task: Optional[asyncio.Task] = None

    # ---------------------------------------------------------------- #
    # Public entrypoint
    # ---------------------------------------------------------------- #

    async def run(self) -> None:
        """Accept the WebSocket, start Redis listener, process messages."""
        await self.ws.accept()
        logger.info("WebSocket connected: child_id=%s", self.child_id)

        await self._init_redis()

        self._listener_task = asyncio.create_task(self._listen_redis())

        try:
            while True:
                msg = await self.ws.receive()
                if msg["type"] == "websocket.disconnect":
                    break
                if msg.get("bytes") is not None:
                    await self._handle_audio_bytes(msg["bytes"])
                elif msg.get("text") is not None:
                    data = json.loads(msg["text"])
                    await self._dispatch(data)
        except WebSocketDisconnect:
            logger.info("WebSocket disconnected: child_id=%s", self.child_id)
        except Exception:
            logger.exception("Unexpected error in WebSocket loop")
        finally:
            await self._stop_voice_pipeline()
            await self._on_disconnect()

    # ---------------------------------------------------------------- #
    # Voice pipeline (lazy, on binary frame)
    # ---------------------------------------------------------------- #

    async def _ensure_voice_pipeline(self) -> None:
        """Set up the voice pipeline on first binary audio frame."""
        if self._voice_enabled:
            return
        self._voice_enabled = True

        from .voice.websocket_source import WebSocketSource
        from .voice.websocket_sink import WebSocketSink
        from .voice.stt import VoiceInputManager
        from .voice.tts import VoiceOutputManager

        self._ws_source = WebSocketSource()
        self._ws_sink = WebSocketSink(self.ws)

        voice_input = VoiceInputManager(source=self._ws_source)
        voice_output = VoiceOutputManager(sink=self._ws_sink)

        self._voice_loop = VoiceLoop(
            on_user_speech=self._handle_voice_transcription,
            voice_input=voice_input,
            voice_output=voice_output,
            config=VoiceLoopConfig(end_of_speech_silence_ms=700),
        )
        await self._voice_loop.start()
        logger.info("Voice pipeline initialised for child_id=%s", self.child_id)

    async def _stop_voice_pipeline(self) -> None:
        if self._voice_loop is not None:
            await self._voice_loop.stop()
            self._voice_loop = None
        self._ws_source = None
        self._ws_sink = None
        self._voice_enabled = False

    async def _handle_audio_bytes(self, data: bytes) -> None:
        """Process a binary audio frame from the browser mic."""
        await self._ensure_voice_pipeline()
        if self._ws_source is None:
            return
        frame = np.frombuffer(data, dtype=np.float32)
        self._ws_source.push_frame(frame)
        self._frame_count += 1
        if self._frame_count % 50 == 0:
            logger.debug(
                "Audio frames received: %d, shape=%s, mean=%.4f, max=%.4f",
                self._frame_count, frame.shape,
                float(np.mean(np.abs(frame))),
                float(np.max(np.abs(frame))),
            )

    async def _handle_voice_transcription(self, text: str) -> None:
        """Called by VoiceLoop when STT transcribes a voice utterance."""
        logger.info("Voice transcription: %.80s", text)
        # Echo transcription back to frontend so the chat log can show
        # what the child said (voice path has no other way to get it).
        try:
            await self.ws.send_json({"type": "transcription", "text": text})
        except Exception:
            logger.debug("Failed to send transcription echo to WS")
        await self._process_speech(text)

    # ---------------------------------------------------------------- #
    # Redis lifecycle
    # ---------------------------------------------------------------- #

    async def _init_redis(self) -> None:
        try:
            self._redis = aioredis.from_url(REDIS_URL, decode_responses=True)
            self._pubsub = self._redis.pubsub()
            await self._pubsub.subscribe(
                _channel_speech(self.child_id),
                _channel_whiteboard(self.child_id),
            )
        except Exception:
            logger.warning("Redis unavailable — using direct WS writes")
            self._redis = None
            self._pubsub = None

    async def _close_redis(self) -> None:
        if self._pubsub is not None:
            await self._pubsub.unsubscribe()
            await self._pubsub.close()
        if self._redis is not None:
            await self._redis.close()
        self._redis = None
        self._pubsub = None

    # ---------------------------------------------------------------- #
    # Redis listener — forwards pub/sub messages to WebSocket
    # ---------------------------------------------------------------- #

    async def _listen_redis(self) -> None:
        if self._pubsub is None:
            return
        try:
            async for message in self._pubsub.listen():
                if message["type"] != "message":
                    continue
                await self._send_redis_message(
                    message["channel"], message["data"]
                )
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Redis listener error")

    async def _send_redis_message(self, channel: str, data: str) -> None:
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON on channel %s: %.80s", channel, data)
            return
        try:
            if channel.endswith(":speech"):
                await self.ws.send_json({
                    "type": "tutor_speech",
                    "text": payload["text"],
                })
                await self.ws.send_json({
                    "type": "emotion",
                    "signal": payload["emotion"],
                })
            elif channel.endswith(":whiteboard"):
                await self.ws.send_json({
                    "type": "whiteboard",
                    "commands": payload,
                })
        except Exception:
            logger.exception("Failed to send WS message via Redis path")

    # ---------------------------------------------------------------- #
    # Message dispatch
    # ---------------------------------------------------------------- #

    async def _dispatch(self, data: dict[str, Any]) -> None:
        msg_type = data.get("type", "")
        handler = {
            "session_start": self._handle_session_start,
            "speech": self._handle_speech,
            "session_end": self._handle_session_end,
        }.get(msg_type)
        if handler is not None:
            await handler(data)
        else:
            await self.ws.send_json({
                "type": "error",
                "message": f"Unknown message type: {msg_type}",
            })

    # ---------------------------------------------------------------- #
    # Handlers
    # ---------------------------------------------------------------- #

    async def _handle_session_start(self, data: dict[str, Any]) -> None:
        subject = data.get("subject") or ""
        topic = data.get("topic") or ""
        # If no subject provided, start with a general greeting and let
        # the subject_detector figure it out from the child's first turn.
        if not subject:
            subject = "General"
        self.session = SessionState(
            child_id=self.child_id,
            subject=subject,
            current_topic=topic,
            conversation_history=[],
            current_mode="teaching",
            last_tutor_response=None,
            pending_whiteboard_commands=[],
        )
        self.subjects_visited = [subject] if subject != "General" else []
        logger.info("Session started: child=%s subject=%s topic=%s", self.child_id, subject, topic)
        greeting = (
            f"Hi there! I'm Nova, your tutor. "
            f"Let's explore {topic or subject} together. "
            f"What would you like to learn about?"
        ) if subject != "General" else (
            "Hi there! I'm Nova, your tutor. "
            "What subject would you like to explore today? "
            "I can help with Math, Science, English, or Social Studies."
        )
        await self.ws.send_json({"type": "tutor_speech", "text": greeting})
        await self.ws.send_json({"type": "emotion", "signal": "encouraging"})

    async def _handle_speech(self, data: dict[str, Any]) -> None:
        """Process a text chat message from the browser."""
        text = data.get("text", "").strip()
        if not text:
            return
        if self.session is None:
            self.session = SessionState(
                child_id=self.child_id,
                subject="General",
                current_topic="",
                conversation_history=[],
                current_mode="teaching",
                last_tutor_response=None,
                pending_whiteboard_commands=[],
            )
        await self._process_speech(text)

    async def _process_speech(self, text: str) -> None:
        """Run orchestrator and send response."""
        logger.info("Processing: %.80s", text)
        try:
            self.session = await self.orchestrator.ainvoke(text, self.session)
        except Exception:
            logger.exception("Orchestrator failed")
            await self.ws.send_json({
                "type": "error",
                "message": "I'm having trouble thinking right now. Please try again.",
            })
            return

        # Track subjects visited for DB persistence
        current_subject = self.session.get("subject", "")
        if current_subject and current_subject not in self.subjects_visited:
            self.subjects_visited.append(current_subject)

        response = self.session.get("last_tutor_response")
        if response is None:
            return

        await self._publish_or_send(response)

        # If voice pipeline is active, synthesize and send TTS audio.
        if self._voice_enabled and self._voice_loop is not None and response.spoken_text:
            await self._voice_loop.speak(response.spoken_text)

    async def _publish_or_send(self, response) -> None:
        speech_payload = json.dumps({
            "text": response.spoken_text,
            "emotion": response.emotion_signal,
        })
        wb_payload = (
            json.dumps([c.model_dump() for c in response.whiteboard_commands])
            if response.whiteboard_commands
            else None
        )

        if self._redis is not None:
            await self._redis.publish(_channel_speech(self.child_id), speech_payload)
        else:
            await self.ws.send_json({
                "type": "tutor_speech",
                "text": response.spoken_text,
            })
            await self.ws.send_json({
                "type": "emotion",
                "signal": response.emotion_signal,
            })

        if wb_payload is not None:
            if self._redis is not None:
                await self._redis.publish(_channel_whiteboard(self.child_id), wb_payload)
            else:
                await self.ws.send_json({
                    "type": "whiteboard",
                    "commands": [
                        c.model_dump() for c in response.whiteboard_commands
                    ],
                })

    async def _handle_session_end(self, data: dict[str, Any] | None = None) -> None:
        await self._persist_session()
        await self.ws.send_json({
            "type": "tutor_speech",
            "text": "Great work today! Come back anytime.",
        })
        await self.ws.send_json({"type": "emotion", "signal": "encouraging"})
        await self.ws.close()

    # ---------------------------------------------------------------- #
    # Disconnect / persistence
    # ---------------------------------------------------------------- #

    async def _on_disconnect(self) -> None:
        await self._persist_session()
        await self._cleanup()

    async def _persist_session(self) -> None:
        if self.session is None:
            return
        try:
            async with async_session_factory() as db_sess:
                repo = __import__(
                    "app.db.repository", fromlist=["MemoryRepository"]
                ).MemoryRepository(db_sess)
                child = await repo.get_child(self.child_id)
                if child is None:
                    db_sess.add(Child(id=self.child_id, name=f"Child_{self.child_id[:8]}", grade=5))
                    await db_sess.commit()
                # Primary subject FK = first subject visited, or "general"
                subject_id = (
                    self.subjects_visited[0].lower().replace(" ", "_")
                    if self.subjects_visited
                    else "general"
                )
                topics = self.session.get("current_topic", "")
                topics_list = [topics] if topics else []
                db_session = DbSession(
                    id=self.db_session_id or str(__import__("uuid").uuid4()),
                    child_id=self.child_id,
                    subject_id=subject_id,
                    ended_at=datetime.now(timezone.utc),
                    topics_covered=topics_list,
                    subjects_covered=list(self.subjects_visited),
                )
                db_session = await db_sess.merge(db_session)
                await db_sess.commit()
                if self.db_session_id is None:
                    self.db_session_id = db_session.id
                logger.info("Session persisted: child=%s subject=%s", self.child_id, subject_id)
        except Exception:
            logger.exception("Failed to persist session")

    async def _cleanup(self) -> None:
        if self._listener_task is not None:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
        await self._close_redis()
