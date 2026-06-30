#!/usr/bin/env python3
"""
Entry point for the fully local AI tutor voice session.

Usage:
    uv run python run.py                           # default: Math
    uv run python run.py --subject Science --topic "Photosynthesis"
    uv run python run.py --subject English --topic "Nouns"
    uv run python run.py --dry-run                  # log without speaking/listening
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys

_log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, _log_level, logging.INFO),
    format="%(levelname)-5s [%(name)s] %(message)s",
    stream=sys.stderr,
)
logging.info("Log level set to %s", _log_level)

# Squelch noisy libs
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


async def main() -> None:
    parser = argparse.ArgumentParser(description="AI Tutor — Local Voice Session")
    parser.add_argument(
        "--subject", "-s",
        default="Math",
        help="CBSE subject (e.g. Math, Science, English, Social_Studies)",
    )
    parser.add_argument(
        "--topic", "-t",
        default="",
        help="Topic within the subject (e.g. Fractions, Photosynthesis)",
    )
    parser.add_argument(
        "--child-id", "-c",
        default="local_child",
        help="Child identifier for session persistence",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log intent/responses without STT/TTS hardware access",
    )
    args = parser.parse_args()

    if args.dry_run:
        from agents.orchestrator import Orchestrator, SessionState

        session = SessionState(
            child_id=args.child_id,
            subject=args.subject,
            current_topic=args.topic,
            conversation_history=[],
            current_mode="teaching",
            last_tutor_response=None,
            pending_whiteboard_commands=[],
        )
        orch = Orchestrator()

        print(f"AI Tutor — Dry Run (subject={args.subject}, topic={args.topic})")
        print("Type your messages below. Press Ctrl+C to exit.\n")

        while True:
            try:
                text = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: input("You: ")
                )
            except (EOFError, KeyboardInterrupt):
                break
            if not text.strip():
                continue

            session = await orch.ainvoke(text, session)
            resp = session.get("last_tutor_response")
            if resp:
                print(f"Nova: {resp.spoken_text}")
                if resp.whiteboard_commands:
                    print(f"  [whiteboard: {len(resp.whiteboard_commands)} cmds]")
                print()
        return

    # ---- Full voice session ----
    from app.voice.voice_session import VoiceSession, VoiceSessionConfig

    config = VoiceSessionConfig(
        subject=args.subject,
        topic=args.topic,
        child_id=args.child_id,
    )

    session = VoiceSession(config=config)

    # Handle Ctrl+C cleanly
    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        stop_event.set()

    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGINT, _signal_handler)
    loop.add_signal_handler(signal.SIGTERM, _signal_handler)

    try:
        await session.start()
        print(f"\n🎙️  AI Tutor started — subject={args.subject}, topic={args.topic}")
        print("Speak to the tutor. Press Ctrl+C to stop.\n")
        await stop_event.wait()
    finally:
        await session.stop()


if __name__ == "__main__":
    asyncio.run(main())
