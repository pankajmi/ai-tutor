"""
Manual test script for VoiceInputManager.

Speak into the mic; transcriptions print to console as utterances complete.
Ctrl+C to stop.

Usage:
    uv run python backend/app/voice/test_stt.py
    uv run python backend/app/voice/test_stt.py --device 2   # specific mic
    uv run python backend/app/voice/test_stt.py --list-devices
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import time

from stt import STTConfig, VADConfig, VoiceInputManager
from sounddevice_source import SoundDeviceSource

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def list_devices() -> None:
    import sounddevice as sd

    print(sd.query_devices())


async def main(device: int | str | None) -> None:
    source = SoundDeviceSource(device=device) if device is not None else None
    manager = VoiceInputManager(
        vad_config=VADConfig(),
        stt_config=STTConfig(model_name="medium.en"),
        source=source,
    )

    print("Loading models (whisper.cpp medium.en + Silero VAD)...")
    t0 = time.monotonic()
    await manager.start()
    print(f"Models loaded in {time.monotonic() - t0:.1f}s. Listening...")
    print("Speak now. Ctrl+C to stop.\n")

    try:
        async for text in manager.listen():
            print(f">> {text}")
    except KeyboardInterrupt:
        pass
    finally:
        await manager.stop()
        print("\nStopped.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--device", type=str, default=None, help="sounddevice input device index/name"
    )
    parser.add_argument(
        "--list-devices", action="store_true", help="List available audio devices and exit"
    )
    args = parser.parse_args()

    if args.list_devices:
        list_devices()
    else:
        device = args.device
        if device is not None and device.isdigit():
            device = int(device)
        asyncio.run(main(device))
