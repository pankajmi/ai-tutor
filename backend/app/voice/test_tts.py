"""
Manual test script for VoiceOutputManager.

Speaks a sample math tutoring explanation aloud via Kokoro TTS, demonstrating
streaming playback. Also exercises stop() mid-utterance to verify barge-in
interruption works.

Usage:
    uv run python backend/app/voice/test_tts.py
    uv run python backend/app/voice/test_tts.py --interrupt   # tests stop() mid-speech
    uv run python backend/app/voice/test_tts.py --voice af_bella
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import time

from tts import TTSConfig, VoiceOutputManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

SAMPLE_EXPLANATION = (
    "Let's think about fractions together. Imagine you have a pizza, and "
    "you cut it into four equal slices. If you eat one slice, you've eaten "
    "one out of four parts, which we write as one fourth. Now, what do you "
    "think would happen if we cut the same pizza into eight slices instead? "
    "Would each slice be bigger or smaller than before? Take your time, "
    "there's no rush."
)


async def run_basic(voice: str) -> None:
    manager = VoiceOutputManager(config=TTSConfig(voice=voice))

    print(f"Loading Kokoro TTS pipeline (voice={voice})...")
    t0 = time.monotonic()
    await manager.start()
    print(f"Loaded in {time.monotonic() - t0:.1f}s.\n")

    print("Speaking sample explanation...")
    t0 = time.monotonic()
    await manager.speak(SAMPLE_EXPLANATION)
    print(f"Done speaking. Total time: {time.monotonic() - t0:.1f}s")

    await manager.shutdown()


async def run_interrupt_test(voice: str) -> None:
    """Starts speaking, then interrupts after ~2s to verify stop() works."""
    manager = VoiceOutputManager(config=TTSConfig(voice=voice))

    print(f"Loading Kokoro TTS pipeline (voice={voice})...")
    await manager.start()
    print("Loaded.\n")

    print("Speaking sample explanation (will interrupt after 2s)...")
    speak_task = asyncio.create_task(manager.speak(SAMPLE_EXPLANATION))

    await asyncio.sleep(2.0)
    print(">>> Simulating child interruption — calling stop() now <<<")
    manager.stop()

    await speak_task
    print(f"is_speaking() after stop: {manager.is_speaking()}")
    assert manager.is_speaking() is False, "Expected playback to be stopped"
    print("Interrupt test passed: playback halted on stop().")

    await manager.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--voice", default="af_heart", help="Kokoro voice preset")
    parser.add_argument(
        "--interrupt",
        action="store_true",
        help="Run the barge-in / stop() interruption test instead of the basic test",
    )
    args = parser.parse_args()

    if args.interrupt:
        asyncio.run(run_interrupt_test(args.voice))
    else:
        asyncio.run(run_basic(args.voice))
