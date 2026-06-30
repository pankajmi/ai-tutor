"""
WebSocket session manager for the AI tutor.

Wires the LangGraph Orchestrator to a single WebSocket connection via
Redis Pub/Sub for independent streaming of speech and whiteboard commands.
Persists session state to Postgres on disconnect.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

import redis.asyncio as aioredis
from fastapi import WebSocket, WebSocketDisconnect

from agents.models import Message
from agents.orchestrator import Orchestrator, SessionState

from .db.database import async_session_factory
from .db.models import Child, Session as DbSession
from .db.seed import seed_subjects

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
    Manages a single WebSocket session for one child.

    Usage (from main.py):
        manager = WebSocketSessionManager(websocket, child_id)
        await manager.run()
    """

    def __init__(self, websocket: WebSocket, child_id: str) -> None:
        self.ws = websocket
        self.child_id = child_id

        self.orchestrator = Orchestrator()
        self.session: Optional[SessionState] = None
        self.db_session_id: Optional[str] = None  # Postgres session.id once created

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
                raw = await self.ws.receive_json()
                await self._dispatch(raw)
        except WebSocketDisconnect:
            logger.info("WebSocket disconnected: child_id=%s", self.child_id)
        except Exception:
            logger.exception("Unexpected error in WebSocket loop")
        finally:
            await self._on_disconnect()

    # ---------------------------------------------------------------- #
    # Redis lifecycle
    # ---------------------------------------------------------------- #

    async def _init_redis(self) -> None:
        """Connect to Redis and subscribe to this child's channels."""
        try:
            self._redis = aioredis.from_url(REDIS_URL, decode_responses=True)
            self._pubsub = self._redis.pubsub()
            await self._pubsub.subscribe(
                _channel_speech(self.child_id),
                _channel_whiteboard(self.child_id),
            )
            logger.debug("Redis subscribed: child_id=%s", self.child_id)
        except Exception:
            logger.warning(
                "Redis unavailable — falling back to direct WebSocket writes"
            )
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
        """
        Background task: consume from Redis Pub/Sub and write to the
        WebSocket. Each message type is sent as a separate JSON frame so
        the frontend can process speech and whiteboard independently.
        """
        if self._pubsub is None:
            return

        try:
            async for message in self._pubsub.listen():
                if message["type"] != "message":
                    continue
                channel: str = message["channel"]
                data: str = message["data"]
                await self._send_redis_message(channel, data)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Redis listener error")

    async def _send_redis_message(self, channel: str, data: str) -> None:
        """Parse a Redis pub/sub message and send the appropriate WS frame."""
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
        logger.debug("Incoming message type=%s", msg_type)

        handler = {
            "session_start": self._handle_session_start,
            "speech": self._handle_speech,
            "session_end": self._handle_session_end,
        }.get(msg_type)

        if handler is not None:
            await handler(data)
        else:
            logger.warning("Unknown message type: %s", msg_type)
            await self.ws.send_json({
                "type": "error",
                "message": f"Unknown message type: {msg_type}",
            })

    # ---------------------------------------------------------------- #
    # Handlers
    # ---------------------------------------------------------------- #

    async def _handle_session_start(self, data: dict[str, Any]) -> None:
        """Initialise a new tutoring session."""
        subject = data.get("subject", "Math")
        topic = data.get("topic", "")

        self.session = SessionState(
            child_id=self.child_id,
            subject=subject,
            current_topic=topic,
            conversation_history=[],
            current_mode="teaching",
            last_tutor_response=None,
            pending_whiteboard_commands=[],
        )

        logger.info(
            "Session started: child=%s subject=%s topic=%s",
            self.child_id, subject, topic,
        )

        await self.ws.send_json({
            "type": "tutor_speech",
            "text": (
                f"Hi there! I'm Nova, your tutor. "
                f"Let's explore {topic or subject} together. "
                f"What would you like to learn about?"
            ),
        })
        await self.ws.send_json({
            "type": "emotion",
            "signal": "encouraging",
        })

    async def _handle_speech(self, data: dict[str, Any]) -> None:
        """Process a child utterance through the orchestrator."""
        text = data.get("text", "").strip()
        if not text:
            return

        if self.session is None:
            # Auto-start session if client didn't send session_start.
            self.session = SessionState(
                child_id=self.child_id,
                subject="Math",
                current_topic="",
                conversation_history=[],
                current_mode="teaching",
                last_tutor_response=None,
                pending_whiteboard_commands=[],
            )

        logger.info("Processing speech (%.80s)", text)

        try:
            self.session = await self.orchestrator.ainvoke(text, self.session)
        except Exception:
            logger.exception("Orchestrator failed")
            await self.ws.send_json({
                "type": "error",
                "message": "I'm having trouble thinking right now. Please try again.",
            })
            return

        response = self.session.get("last_tutor_response")
        if response is None:
            return

        # Publish to Redis channels (falls back to direct send if Redis down).
        await self._publish_or_send(response)

    async def _publish_or_send(self, response) -> None:
        """
        Publish speech and whiteboard to Redis channels for parallel delivery.
        Falls back to direct WebSocket send if Redis is unavailable.
        """
        speech_payload = json.dumps({
            "text": response.spoken_text,
            "emotion": response.emotion_signal,
        })
        wb_payload = (
            json.dumps([c.model_dump() for c in response.whiteboard_commands])
            if response.whiteboard_commands
            else None
        )

        # Publish speech — send immediately via Redis or direct.
        if self._redis is not None:
            await self._redis.publish(
                _channel_speech(self.child_id), speech_payload
            )
        else:
            await self.ws.send_json({
                "type": "tutor_speech",
                "text": response.spoken_text,
            })
            await self.ws.send_json({
                "type": "emotion",
                "signal": response.emotion_signal,
            })

        # Publish whiteboard commands independently.
        if wb_payload is not None:
            if self._redis is not None:
                await self._redis.publish(
                    _channel_whiteboard(self.child_id), wb_payload
                )
            else:
                await self.ws.send_json({
                    "type": "whiteboard",
                    "commands": [
                        c.model_dump() for c in response.whiteboard_commands
                    ],
                })

    async def _handle_session_end(self, data: dict[str, Any] | None = None) -> None:
        """Persist the session and close the connection."""
        await self._persist_session()
        await self.ws.send_json({
            "type": "tutor_speech",
            "text": "Great work today! Come back anytime.",
        })
        await self.ws.send_json({
            "type": "emotion",
            "signal": "encouraging",
        })
        await self.ws.close()

    # ---------------------------------------------------------------- #
    # Disconnect / persistence
    # ---------------------------------------------------------------- #

    async def _on_disconnect(self) -> None:
        """Persist session state when the client disconnects."""
        await self._persist_session()
        await self._cleanup()

    async def _persist_session(self) -> None:
        """Save the session to Postgres (idempotent, safe to call multiple times)."""
        if self.session is None:
            return

        try:
            async with async_session_factory() as db_sess:
                repo = __import__(
                    "app.db.repository", fromlist=["MemoryRepository"]
                ).MemoryRepository(db_sess)

                # Ensure child exists.
                child = await repo.get_child(self.child_id)
                if child is None:
                    db_sess.add(
                        Child(
                            id=self.child_id,
                            name=f"Child_{self.child_id[:8]}",
                            grade=5,
                        )
                    )
                    await db_sess.commit()

                # Upsert the DB session row.
                subject_id = self.session["subject"].lower().replace(" ", "_")
                topics = self.session.get("current_topic", "")
                topics_list = [topics] if topics else []

                db_session = DbSession(
                    id=self.db_session_id or str(
                        __import__("uuid").uuid4()
                    ),
                    child_id=self.child_id,
                    subject_id=subject_id,
                    ended_at=datetime.now(timezone.utc),
                    topics_covered=topics_list,
                )
                db_session = await db_sess.merge(db_session)
                await db_sess.commit()

                if self.db_session_id is None:
                    self.db_session_id = db_session.id

                logger.info(
                    "Session persisted: child=%s subject=%s",
                    self.child_id, subject_id,
                )
        except Exception:
            logger.exception("Failed to persist session")

    async def _cleanup(self) -> None:
        """Cancel background tasks and close Redis connections."""
        if self._listener_task is not None:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
        await self._close_redis()
