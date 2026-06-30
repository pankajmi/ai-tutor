"""
CLI test harness for the Orchestrator.

Runs an interactive session loop. Subject defaults to Math for consistency
with prior testing, but is passed as a parameter — no subject-specific
branching in the orchestrator itself.

Usage:
    uv run python agents/test_orchestrator.py
    uv run python agents/test_orchestrator.py --subject science
    uv run python agents/test_orchestrator.py --subject english
    uv run python agents/test_orchestrator.py --single-turn "I don't get fractions"
    uv run python agents/test_orchestrator.py --dry-run        # no LLM calls
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import textwrap

from agents.models import Message, TutorResponse
from agents.orchestrator import Orchestrator, SessionState

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# Suppress httpx INFO noise for cleaner output.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("langchain_ollama").setLevel(logging.WARNING)

# --------------------------------------------------------------------------- #
# Default session state factory
# --------------------------------------------------------------------------- #


def make_session(
    child_id: str = "test_child",
    subject: str = "Math",
    topic: str = "",
) -> SessionState:
    """Create a fresh session state for the test harness."""
    return SessionState(
        child_id=child_id,
        subject=subject,
        current_topic=topic,
        conversation_history=[],
        current_mode="teaching",
        last_tutor_response=None,
        pending_whiteboard_commands=[],
    )


# --------------------------------------------------------------------------- #
# Pretty-print helpers
# --------------------------------------------------------------------------- #


def _print_response(turn: int, response: TutorResponse | None) -> None:
    if response is None:
        return
    signal = response.emotion_signal
    signal_icon = {
        "encouraging": "🌟",
        "neutral": "💬",
        "redirecting": "🔄",
    }.get(signal, "💬")
    print(f"  Nova {signal_icon} ({signal}):")
    print(f"    {response.spoken_text}")
    if response.whiteboard_commands:
        for cmd in response.whiteboard_commands:
            print(f"    [whiteboard] {cmd.type} delay={cmd.delay_ms}ms")
    if response.topic_detected:
        print(f"    [topic: {response.topic_detected}]")
    print()


def _print_session_summary(session: SessionState) -> None:
    print()
    print("=" * 60)
    print("  Session Summary")
    print("=" * 60)
    print(f"  Child ID:    {session['child_id']}")
    print(f"  Subject:     {session['subject']}")
    print(f"  Topic:       {session['current_topic']}")
    print(f"  Mode:        {session['current_mode']}")
    print(f"  Turns:       {len(session['conversation_history']) // 2}")
    print("=" * 60)
    print()


# --------------------------------------------------------------------------- #
# Simulation loop
# --------------------------------------------------------------------------- #


async def run_session(
    subject: str,
    initial_topic: str = "",
    *,
    dry_run: bool = False,
) -> None:
    orch = Orchestrator()
    session = make_session(subject=subject, topic=initial_topic)

    print()
    print(f"{'='*60}")
    print(f"  AI Tutor — Session ({subject})")
    print(f"  Type 'quit' to exit, 'mode' to see current mode, 'problem' for a problem")
    print(f"{'='*60}")
    print()

    turn = 0
    first_turn = True

    while True:
        if first_turn:
            # Provide an opening message for the first turn.
            user_input = (
                f"I need help with {subject.lower()}. "
                f"I don't understand {initial_topic or 'the current topic'}."
            )
            print(f"  [auto] Child: {user_input}")
            first_turn = False
        else:
            try:
                user_input = input("  You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            break
        if user_input.lower() == "mode":
            print(f"  Current mode: {session['current_mode']}")
            print(f"  Current topic: {session['current_topic']}")
            continue

        if dry_run:
            print(f"  [DRY-RUN] Would route: {user_input!r}")
            print()
            turn += 1
            continue

        turn += 1

        try:
            session = await orch.ainvoke(user_input, session)
        except Exception as exc:
            print(f"  [ERROR] Orchestrator failed: {exc}")
            print("  (Is Ollama running? Try: ollama serve)")
            break

        response = session.get("last_tutor_response")
        _print_response(turn, response)

    _print_session_summary(session)


async def run_single_turn(
    message: str,
    subject: str,
    topic: str = "",
    *,
    dry_run: bool = False,
) -> None:
    """Process a single message and print the response."""
    orch = Orchestrator()
    session = make_session(subject=subject, topic=topic)

    print(f"  Subject: {subject}")
    print(f"  Child:   {message}")
    print()

    if dry_run:
        print("  [DRY-RUN] No LLM call.")
        return

    try:
        session = await orch.ainvoke(message, session)
    except Exception as exc:
        print(f"  [ERROR] {exc}")
        return

    response = session.get("last_tutor_response")
    _print_response(1, response)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="CLI test harness for the Orchestrator Agent.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
            Examples:
              %(prog)s                          # interactive session, Math
              %(prog)s --subject science         # Science session
              %(prog)s --subject english --topic grammar
              %(prog)s --single-turn "What is a fraction?" --subject math
              %(prog)s --dry-run                 # print routing, no LLM
        """),
    )
    parser.add_argument(
        "--subject",
        default="Math",
        help="Subject for the session (default: Math)",
    )
    parser.add_argument(
        "--topic",
        default="",
        help="Initial topic (default: empty — auto-detected)",
    )
    parser.add_argument(
        "--single-turn",
        metavar="MESSAGE",
        default=None,
        help="Process one message and exit (non-interactive)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print routing decisions without calling Ollama",
    )

    args = parser.parse_args()

    if args.single_turn:
        asyncio.run(
            run_single_turn(
                args.single_turn,
                args.subject,
                args.topic,
                dry_run=args.dry_run,
            )
        )
    else:
        asyncio.run(
            run_session(
                args.subject,
                args.topic,
                dry_run=args.dry_run,
            )
        )
