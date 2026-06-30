"""
Manual test script for OllamaClientManager.

Sends a simple, subject-agnostic question to the primary model and prints
the response. Deliberately uses a science topic (not math) to confirm the
client carries no subject-specific assumptions — any subject's question
should work identically.

Usage:
    uv run python backend/app/llm/test_client.py
    uv run python backend/app/llm/test_client.py --classifier   # use the small model instead
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import time

from client import OllamaConnectionError, get_ollama_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

SAMPLE_QUESTION = "Explain photosynthesis in simple terms, in 2-3 sentences."


async def main(use_classifier: bool) -> None:
    client = get_ollama_client()

    print(f"Checking Ollama health (base_url={client.base_url})...")
    try:
        await client.health_check()
        print("Health check passed.\n")
    except OllamaConnectionError as exc:
        print(f"Health check FAILED: {exc}")
        return

    model_label = "classifier (qwen2.5:1.5b)" if use_classifier else "primary (qwen2.5:7b)"
    llm = client.get_classifier_llm() if use_classifier else client.get_primary_llm()

    print(f"Sending question to {model_label}:")
    print(f"  {SAMPLE_QUESTION!r}\n")

    t0 = time.monotonic()
    try:
        response = await client.invoke_with_retry(llm, SAMPLE_QUESTION)
    except OllamaConnectionError as exc:
        print(f"Call FAILED after retries: {exc}")
        return
    elapsed = time.monotonic() - t0

    print(f"Response ({elapsed:.2f}s):\n")
    print(response.content)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--classifier",
        action="store_true",
        help="Use the classifier model (qwen2.5:1.5b) instead of primary",
    )
    args = parser.parse_args()
    asyncio.run(main(args.classifier))
