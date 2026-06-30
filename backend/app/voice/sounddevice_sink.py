from __future__ import annotations

import logging
from typing import Optional

import numpy as np

import numpy as np
import sounddevice as sd

from .audio_base import AudioSink

logger = logging.getLogger("ai_tutor.voice.sounddevice_sink")

SAMPLE_RATE = 24_000


class SoundDeviceSink(AudioSink):
    """Plays audio chunks via sounddevice."""

    def __init__(self, sample_rate: int = SAMPLE_RATE) -> None:
        self._sample_rate = sample_rate
        self._stream: Optional[sd.OutputStream] = None

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    async def start(self) -> None:
        self._stream = sd.OutputStream(
            samplerate=self._sample_rate,
            channels=1,
            dtype="float32",
        )
        self._stream.start()
        logger.debug("SoundDeviceSink started.")

    def write(self, audio: np.ndarray) -> None:
        if self._stream is None:
            return
        try:
            self._stream.write(audio)
        except sd.PortAudioError:
            logger.exception("SoundDeviceSink write error")

    async def stop(self) -> None:
        if self._stream is not None and self._stream.active:
            self._stream.abort()

    async def close(self) -> None:
        await self.stop()
        if self._stream is not None:
            self._stream.close()
            self._stream = None
        logger.debug("SoundDeviceSink closed.")
