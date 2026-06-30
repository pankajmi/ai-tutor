"""
Manual test script for the Tutor Agent (persona "Nova").

Simulates a 3-turn tutoring conversation. Defaults to a math topic (fractions)
for consistency with prior testing, but runs a science turn as well to confirm
the agent has no hardcoded math-only assumptions.

Usage:
    uv run python agents/test_tutor_agent.py                   # math (fractions)
    uv run python agents/test_tutor_agent.py --subject science  # science
    uv run python agents/test_tutor_agent.py --subject english  # english
    uv run python agents/test_tutor_agent.py --dry-run          # skip LLM, print prompt only
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import textwrap
import time

from agents.models import ChildContext, Message
from agents.tutor_agent import _build_system_prompt, TutorAgent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# --------------------------------------------------------------------------- #
# Simulated conversations by subject
# --------------------------------------------------------------------------- #

SUBJECT_SCENARIOS: dict[str, list[dict]] = {
    "math": [
        {
            "child_context": ChildContext(
                grade=5,
                subject="Math",
                weak_topics=["fractions"],
                current_topic="comparing fractions",
            ),
            "message": "I don't get how to tell which fraction is bigger.",
        },
        {
            "message": "Hmm, I'm not sure. Maybe one third?",
        },
        {
            "message": "Oh! So if the bottoms are the same, I just look at the tops?",
        },
    ],
    "science": [
        {
            "child_context": ChildContext(
                grade=7,
                subject="Science",
                weak_topics=["photosynthesis"],
                current_topic="plant nutrition",
            ),
            "message": "How do plants get food if they don't eat like we do?",
        },
        {
            "message": "So the sun is like their food? Then what's soil for?",
        },
        {
            "message": "Oh, so the plant makes its own food using sunlight, water, and air?",
        },
    ],
}

# --------------------------------------------------------------------------- #
# Test runner
# --------------------------------------------------------------------------- #


async def run_simulation(scenario: list[dict], dry_run: bool = False) -> None:
    agent = TutorAgent()
    history: list[Message] = []
    subject = scenario[0]["child_context"].subject

    print(f"\n{'='*60}")
    print(f"  Simulating: {subject}")
    print(f"{'='*60}\n")

    for turn_idx, turn in enumerate(scenario):
        ctx = turn.get("child_context", scenario[0]["child_context"])
        msg = turn["message"]

        print(f"--- Turn {turn_idx + 1} ---")
        print(f"  Child: {msg}\n")

        if dry_run:
            prompt = _build_system_prompt(ctx)
            print(f"  [DRY-RUN] System prompt ({subject}):")
            for line in prompt.split("\n"):
                print(f"    {line}")
            print()

            # Simulate a mock response for dry-run mode
            if turn_idx == 0:
                resp_text = (
                    f"Great question! Let's start with what you already know "
                    f"about {ctx.current_topic}."
                )
            elif turn_idx == 1:
                resp_text = (
                    "That's a good guess! Let's break this down. "
                    "What do you notice about the denominators?"
                )
            else:
                resp_text = (
                    "Exactly right! You've got it. "
                    "Now let's try another example to practice."
                )
            tutor_response = type(
                "obj",
                (object,),
                {
                    "spoken_text": resp_text,
                    "emotion_signal": "encouraging",
                    "topic_detected": ctx.current_topic,
                    "whiteboard_commands": None,
                },
            )
        else:
            # Try to load the test_client for health check, but don't fail
            # if Ollama isn't running — let the agent handle it gracefully.
            try:
                t0 = time.monotonic()
                tutor_response = await agent.ainvoke(
                    child_message=msg,
                    child_context=ctx,
                    conversation_history=history,
                )
                elapsed = time.monotonic() - t0
                print(f"  [LLM took {elapsed:.1f}s]")
            except Exception as exc:
                print(f"  [ERROR] {exc}")
                print("  (Is Ollama running? Try: ollama serve)")
                return

        print(f"  Nova ({tutor_response.emotion_signal}):")
        print(f"    {tutor_response.spoken_text}")
        if tutor_response.topic_detected:
            print(f"  [topic_detected: {tutor_response.topic_detected}]")
        print()

        history.append(Message(role="user", content=msg))
        history.append(Message(role="assistant", content=tutor_response.spoken_text))

    print(f"{'='*60}")
    print(f"  Simulation complete ({len(scenario)} turns).")
    print(f"{'='*60}\n")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Manual test script for the Tutor Agent.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
            Examples:
              %(prog)s                    # math (fractions)
              %(prog)s --subject science  # photosynthesis
              %(prog)s --subject english  # grammar / composition
              %(prog)s --dry-run          # show prompts without calling Ollama
        """),
    )
    parser.add_argument(
        "--subject",
        default="math",
        choices=list(SUBJECT_SCENARIOS.keys()),
        help="Subject scenario to simulate (default: math)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print system prompt and mock responses without calling Ollama",
    )
    args = parser.parse_args()

    scenario = SUBJECT_SCENARIOS[args.subject]

    if args.dry_run:
        asyncio.run(run_simulation(scenario, dry_run=True))
    else:
        asyncio.run(run_simulation(scenario, dry_run=False))
