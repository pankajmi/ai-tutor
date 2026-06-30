#!/usr/bin/env python3
"""
Combined entry point: FastAPI server (HTTP + WebSocket) + local voice session.

Starts Uvicorn on port 8000 for browser connections and simultaneously
runs the local VoiceSession (mic → STT → Orchestrator → TTS → speaker).
Whiteboard commands from the voice session are published via Redis Pub/Sub
and forwarded by the WebSocket session manager to connected browsers.

Usage:
    uv run python run_server.py
    uv run python run_server.py --subject Science --topic "Photosynthesis"
    uv run python run_server.py --port 8001
    uv run python run_server.py --no-voice          # server only, no mic/speaker
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import sys

import redis.asyncio as aioredis

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)-5s [%(name)s] %(message)s",
    stream=sys.stderr,
)

# Squelch noisy libs
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("multipart").setLevel(logging.WARNING)

logger = logging.getLogger("ai_tutor.run_server")

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")


def _whiteboard_channel(child_id: str) -> str:
    return f"tutor:{child_id}:whiteboard"


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="AI Tutor — Combined Server + Voice Session"
    )
    parser.add_argument("--port", "-p", type=int, default=8000, help="Server port")
    parser.add_argument("--subject", "-s", default="Math", help="CBSE subject")
    parser.add_argument("--topic", "-t", default="", help="Topic")
    parser.add_argument("--child-id", "-c", default="local_child", help="Child ID")
    parser.add_argument(
        "--no-voice",
        action="store_true",
        help="Start server only (no mic/speaker voice session)",
    )
    args = parser.parse_args()

    # ── Import FastAPI app ──────────────────────────────────────────────
    from app.main import app

    # ── Import voice session (if enabled) ──────────────────────────────
    whiteboard_bridge = None
    voice_session = None

    if not args.no_voice:
        from app.voice.voice_session import VoiceSession, VoiceSessionConfig

        # Set up a Redis-based whiteboard bridge: when the tutor generates
        # whiteboard commands, publish them to Redis where the WebSocket
        # session manager's listener picks them up and forwards to the browser.
        redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)

        async def _bridge(commands: list[dict]) -> None:
            """Publish whiteboard commands to Redis for WS relay."""
            try:
                payload = json.dumps(commands)
                await redis_client.publish(
                    _whiteboard_channel(args.child_id), payload
                )
            except Exception:
                logger.exception("Redis publish failed")

        whiteboard_bridge = _bridge

        config = VoiceSessionConfig(
            subject=args.subject,
            topic=args.topic,
            child_id=args.child_id,
        )
        voice_session = VoiceSession(config=config, whiteboard_bridge=whiteboard_bridge)

    # ── Run ─────────────────────────────────────────────────────────────
    import uvicorn

    # Uvicorn config
    uvicorn_config = uvicorn.Config(
        app=app,
        host="0.0.0.0",
        port=args.port,
        log_level="info",
    )
    server = uvicorn.Server(uvicorn_config)

    # Handle Ctrl+C
    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        logger.info("Shutdown signal received...")
        stop_event.set()

    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGINT, _signal_handler)
    loop.add_signal_handler(signal.SIGTERM, _signal_handler)

    # Start the server and voice session concurrently
    async def run_server() -> None:
        await server.serve()

    if voice_session is not None:
        logger.info(
            "Starting combined server (port=%d) + voice session (subject=%s)...",
            args.port, args.subject,
        )

        async def run_voice() -> None:
            await voice_session.start()
            print(
                f"\n🎙️  AI Tutor running on http://localhost:{args.port}\n"
                f"   Subject: {args.subject}\n"
                f"   Speak to the tutor or open the browser whiteboard.\n"
                f"   Press Ctrl+C to stop.\n"
            )
            await stop_event.wait()

        await asyncio.gather(run_server(), run_voice())
    else:
        logger.info("Starting server only on port %d...", args.port)
        print(f"\n🌐  AI Tutor server running on http://localhost:{args.port}")
        print("   Connect your browser to the whiteboard or dashboard.\n")
        await run_server()


if __name__ == "__main__":
    asyncio.run(main())
