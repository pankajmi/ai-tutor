from __future__ import annotations

import asyncio
import logging
from typing import Optional

import numpy as np

from .audio_base import AudioSource

logger = logging.getLogger("ai_tutor.voice.websocket_source")


class WebSocketSource(AudioSource):
    """
    Audio source that receives frames externally (pushed from a WebSocket
    handler) and provides them via read_frame().

    The WebSocket handler calls push_frame() for each binary message.
    VoiceInputManager's processing loop calls read_frame() to consume them.
    """

    def __init__(
        self,
        sample_rate: int = 16_000,
        frame_size: int = 512,
    ) -> None:
        self._sample_rate = sample_rate
        self._frame_size = frame_size
        self._queue: asyncio.Queue[Optional[np.ndarray]] = asyncio.Queue()

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def frame_size(self) -> int:
        return self._frame_size

    async def start(self) -> None:
        logger.debug("WebSocketSource started.")

    async def stop(self) -> None:
        # Push sentinel to unblock any waiting read_frame()
        self._queue.put_nowait(None)
        logger.debug("WebSocketSource stopped.")

    def push_frame(self, frame: np.ndarray) -> None:
        """Called by the WebSocket handler to feed audio data."""
        try:
            self._queue.put_nowait(frame)
        except asyncio.QueueFull:
            logger.warning("WebSocketSource queue full, dropping frame")

    async def read_frame(self) -> Optional[np.ndarray]:
        return await self._queue.get()
