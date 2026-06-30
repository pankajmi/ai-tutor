from __future__ import annotations

import asyncio
import logging
from typing import Optional

import numpy as np
import sounddevice as sd

from .audio_base import AudioSource

logger = logging.getLogger("ai_tutor.voice.sounddevice_source")

SAMPLE_RATE = 16_000
FRAME_DURATION_MS = 32
FRAME_SAMPLES = int(SAMPLE_RATE * FRAME_DURATION_MS / 1000)


class SoundDeviceSource(AudioSource):
    """Captures mic audio via sounddevice and produces frames."""

    def __init__(
        self,
        device: Optional[int | str] = None,
        sample_rate: int = SAMPLE_RATE,
        frame_size: int = FRAME_SAMPLES,
    ) -> None:
        self._device = device
        self._sample_rate = sample_rate
        self._frame_size = frame_size

        self._stream: Optional[sd.InputStream] = None
        self._queue: asyncio.Queue[np.ndarray] = asyncio.Queue()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def frame_size(self) -> int:
        return self._frame_size

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()

        def _callback(indata, frames, time_info, status):
            if status:
                logger.warning("Audio input status: %s", status)
            mono = indata[:, 0].copy()
            if self._loop is not None:
                self._loop.call_soon_threadsafe(
                    self._queue.put_nowait, mono
                )

        self._stream = sd.InputStream(
            samplerate=self._sample_rate,
            channels=1,
            dtype="float32",
            blocksize=self._frame_size,
            device=self._device,
            callback=_callback,
        )
        self._stream.start()
        logger.debug("SoundDeviceSource started.")

    async def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        logger.debug("SoundDeviceSource stopped.")

    async def read_frame(self) -> Optional[np.ndarray]:
        return await self._queue.get()
