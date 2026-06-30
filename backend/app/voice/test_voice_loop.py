"""
Echo test for VoiceLoop — validates the full STT <-> TTS loop end-to-end
without an LLM in the path.

Behavior: whatever the child says is transcribed and immediately spoken
back by the tutor ("You said: ..."). This is the simplest possible
on_user_speech handler and is useful for verifying:
    - mic capture + VAD + whisper transcription works
    - TTS playback works
    - listening correctly pauses while the tutor echoes back
    - listening resumes immediately after the echo finishes
    - barge-in works: interrupt the echo mid-sentence by speaking again

Usage:
    uv run python -m app.voice.test_voice_loop
    uv run python -m app.voice.test_voice_loop --device 1   # specific mic

Try this manually:
    1. Say something short -> tutor echoes it back.
    2. Say something longer, then immediately interrupt the echo by
       speaking again before it finishes -> echo should cut off and the
       loop should pick up your new utterance.
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from app.voice.stt import VoiceInputManager
from app.voice.sounddevice_source import SoundDeviceSource
from app.voice.voice_loop import VoiceLoop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger("echo_test")


async def main(device: int | str | None = None) -> None:
    loop_ref: dict[str, VoiceLoop] = {}

    async def on_user_speech(text: str) -> None:
        print(f"\n>> Child said: {text!r}")
        response = f"You said: {text}"
        print(f"<< Tutor echoing: {response!r}\n")
        await loop_ref["loop"].speak(response)

    source = SoundDeviceSource(device=device) if device is not None else None
    voice_input = VoiceInputManager(source=source) if source is not None else None
    voice_loop = VoiceLoop(
        on_user_speech=on_user_speech,
        voice_input=voice_input,
    )
    loop_ref["loop"] = voice_loop

    print("Loading models (this may take a moment)...")
    await voice_loop.start()
    print("\nReady. Speak into the mic — the tutor will echo back what you said.")
    print("Try interrupting the echo mid-sentence to test barge-in.")
    print("Ctrl+C to stop.\n")

    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        print("\nShutting down...")
        await voice_loop.stop()
        print("Stopped.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Echo test for VoiceLoop")
    parser.add_argument("--device", type=int, default=None, help="Input device index")
    args = parser.parse_args()
    asyncio.run(main(device=args.device))
