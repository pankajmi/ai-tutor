from __future__ import annotations

import asyncio
import logging
import queue
from typing import Optional

import numpy as np
from fastapi import WebSocket

from .audio_base import AudioSink

logger = logging.getLogger("ai_tutor.voice.websocket_sink")

SAMPLE_RATE = 24_000

_SHUTDOWN_SENTINEL = object()


class WebSocketSink(AudioSink):
    """
    Audio sink that sends audio chunks as binary WebSocket frames.

    The VoiceOutputManager's playback thread calls write(audio) to enqueue
    audio. An async sender task consumes the queue and sends frames over
    the WebSocket. The sender stays alive across multiple speak()/stop()
    cycles until close() is called.
    """

    def __init__(self, websocket: WebSocket, sample_rate: int = SAMPLE_RATE) -> None:
        self._ws = websocket
        self._sample_rate = sample_rate
        self._audio_queue: "queue.Queue" = queue.Queue()
        self._sender_task: Optional[asyncio.Task] = None

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    async def start(self) -> None:
        self._sender_task = asyncio.create_task(self._sender_loop())
        logger.debug("WebSocketSink started.")

    def write(self, audio: np.ndarray) -> None:
        self._audio_queue.put(audio)

    async def stop(self) -> None:
        """
        Flush pending audio on barge-in / interruption.

        Also sends a {"type": "stop_audio"} JSON control frame to the browser
        so AudioPlayer can immediately clear its local queue and stop the
        currently-playing BufferSource. Without this, audio already transmitted
        to the browser keeps playing for up to ~1s after the server has stopped
        generating — making barge-in feel delayed from the child's perspective
        even though the server responded instantly.
        """
        while True:
            try:
                self._audio_queue.get_nowait()
            except queue.Empty:
                break
        # Fire-and-forget: send the stop signal without blocking the barge-in
        # path. Use ensure_future so this doesn't stall voice_loop.stop().
        try:
            asyncio.ensure_future(self._ws.send_json({"type": "stop_audio"}))
        except Exception:
            pass  # WebSocket may already be closing; not fatal

    async def close(self) -> None:
        """Permanent shutdown."""
        self._audio_queue.put(_SHUTDOWN_SENTINEL)
        if self._sender_task is not None:
            try:
                await asyncio.wait_for(self._sender_task, timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("WebSocketSink sender did not finish in time")
            self._sender_task = None

    async def _sender_loop(self) -> None:
        """
        Consumes audio from the thread-safe queue and sends binary frames
        via the WebSocket.
        """
        while True:
            item = await asyncio.to_thread(self._audio_queue.get)
            if item is _SHUTDOWN_SENTINEL:
                break
            try:
                await self._ws.send_bytes(item.tobytes())
            except Exception:
                logger.exception("WebSocketSink send error")
                break
