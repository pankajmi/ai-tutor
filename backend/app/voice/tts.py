"""
Text-to-Speech module for the local AI tutor.

Pipeline:
    text -> Kokoro TTS (kokoro-82m, chunked by sentence) -> streaming playback (sounddevice)

Design notes:
- Kokoro generates audio per-sentence/chunk rather than for the whole input
  at once, so we split the input text into smaller segments and feed them
  to Kokoro's generator API. Each chunk's audio is queued for playback as
  soon as it's ready — the child hears the tutor start speaking before the
  full response has finished synthesizing.
- Playback runs via a sounddevice OutputStream fed from an audio queue on a
  background thread, decoupled from generation. stop() clears the queue and
  halts the stream immediately, enabling fast barge-in when the child
  interrupts mid-sentence.
- Generation (Kokoro inference) is CPU-bound and blocking; it runs inside
  asyncio.to_thread() so the FastAPI event loop is never blocked.
"""

from __future__ import annotations

import asyncio
import logging
import queue
import re
import threading
from dataclasses import dataclass
from typing import Optional

import numpy as np
import sounddevice as sd

logger = logging.getLogger("ai_tutor.voice.tts")

SAMPLE_RATE = 24_000  # Kokoro's native output sample rate


@dataclass
class TTSConfig:
    """Kokoro TTS configuration."""

    # Kokoro's voice presets are named like "af_heart", "af_bella", "am_adam", etc.
    # af_heart is widely regarded as Kokoro's warmest, most natural English
    # voice — a calm, friendly female voice, well suited to a patient tutor
    # persona ("Nova"). af_bella is a good alternative if a different tone
    # is preferred.
    voice: str = "af_heart"
    lang_code: str = "a"  # "a" = American English in Kokoro's lang_code scheme
    speed: float = 1.0  # 1.0 = natural pace; slightly slower can aid comprehension for kids

    # Max characters per chunk sent to Kokoir at a time. Keeping chunks
    # sentence-sized lets playback start sooner (lower time-to-first-audio)
    # without fragmenting Kokoro's prosody too much.
    max_chunk_chars: int = 220


# --------------------------------------------------------------------------
# Text chunking
# --------------------------------------------------------------------------

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _split_into_chunks(text: str, max_chars: int) -> list[str]:
    """
    Splits text into sentence-sized chunks for incremental TTS generation.
    Falls back to splitting on commas/length if a single sentence exceeds
    max_chars (e.g. a long unbroken explanation).
    """
    text = text.strip()
    if not text:
        return []

    sentences = _SENTENCE_SPLIT_RE.split(text)
    chunks: list[str] = []

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence) <= max_chars:
            chunks.append(sentence)
            continue

        # Sentence too long — split further on commas, then hard-wrap as a
        # last resort so no single chunk blows past max_chars.
        parts = sentence.split(", ")
        buffer = ""
        for part in parts:
            candidate = f"{buffer}, {part}" if buffer else part
            if len(candidate) > max_chars and buffer:
                chunks.append(buffer)
                buffer = part
            else:
                buffer = candidate
        if buffer:
            chunks.append(buffer)

    return chunks


# --------------------------------------------------------------------------
# VoiceOutputManager
# --------------------------------------------------------------------------


class VoiceOutputManager:
    """
    Synthesizes and plays speech via Kokoro TTS with streaming, interruptible
    playback.

    Usage:
        manager = VoiceOutputManager()
        await manager.start()

        await manager.speak("Let's think about this differently.")
        manager.is_speaking()  # True while audio is playing
        manager.stop()         # interrupt immediately (barge-in)

        await manager.shutdown()
    """

    def __init__(self, config: Optional[TTSConfig] = None) -> None:
        self.config = config or TTSConfig()

        self._pipeline = None  # lazy-loaded Kokoro pipeline

        # Audio chunks ready for playback, consumed by the playback thread.
        # A small queue is fine — we want generation to stay just ahead of
        # playback, not race arbitrarily far ahead.
        self._audio_queue: "queue.Queue[Optional[np.ndarray]]" = queue.Queue(maxsize=8)

        self._stream: Optional[sd.OutputStream] = None
        self._playback_thread: Optional[threading.Thread] = None

        self._speaking = threading.Event()
        self._stop_requested = threading.Event()
        self._playback_lock = threading.Lock()

        self._current_speak_task: Optional[asyncio.Task] = None

    # ---------------------------------------------------------------- #
    # Lifecycle
    # ---------------------------------------------------------------- #

    async def start(self) -> None:
        """Load the Kokoro model. Call once before first speak()."""
        logger.info("Loading Kokoro TTS pipeline...")
        self._pipeline = await asyncio.to_thread(self._load_pipeline)
        logger.info("Kokoro TTS pipeline loaded (voice=%s).", self.config.voice)

    async def shutdown(self) -> None:
        """Stop any playback and release resources."""
        self.stop()
        if self._stream is not None:
            self._stream.close()
            self._stream = None

    def _load_pipeline(self):
        """
        Loads Kokoro via the `kokoro` package's KPipeline interface.
        lang_code "a" selects the American-English voice set, which includes
        the af_heart / af_bella voices used here.
        """
        from kokoro import KPipeline

        return KPipeline(lang_code=self.config.lang_code)

    # ---------------------------------------------------------------- #
    # Public API
    # ---------------------------------------------------------------- #

    async def speak(self, text: str) -> None:
        """
        Synthesize and play `text`, streaming audio chunk-by-chunk so
        playback begins before generation fully completes.

        If called while already speaking, the previous utterance is
        interrupted first (last call wins) — mirrors how a human tutor
        would stop and respond to a new prompt rather than queueing speech.
        """
        if self._pipeline is None:
            raise RuntimeError("VoiceOutputManager.start() must be called before speak().")

        # Interrupt any in-flight speech before starting the new one.
        self.stop()

        self._stop_requested.clear()
        self._speaking.set()
        self._ensure_playback_thread()

        chunks = _split_into_chunks(text, self.config.max_chunk_chars)
        if not chunks:
            self._speaking.clear()
            return

        try:
            for chunk_text in chunks:
                if self._stop_requested.is_set():
                    break
                audio = await asyncio.to_thread(self._synthesize_chunk, chunk_text)
                if audio is None or self._stop_requested.is_set():
                    break
                await self._enqueue_audio(audio)

            # Signal end-of-utterance to the playback thread so it knows no
            # more chunks are coming once the queue drains.
            if not self._stop_requested.is_set():
                await self._enqueue_audio(None)

            # Wait for playback to actually finish draining the queue.
            while (
                not self._stop_requested.is_set()
                and (not self._audio_queue.empty() or self._is_stream_active())
            ):
                await asyncio.sleep(0.05)
        finally:
            self._speaking.clear()

    def stop(self) -> None:
        """
        Immediately interrupt playback (e.g. child starts talking over the
        tutor). Safe to call even if nothing is currently speaking.
        """
        if not self._speaking.is_set():
            return

        self._stop_requested.set()
        # Drain any queued chunks so the playback thread doesn't keep
        # playing stale audio after stop() returns.
        with self._playback_lock:
            while True:
                try:
                    self._audio_queue.get_nowait()
                except queue.Empty:
                    break
            if self._stream is not None and self._stream.active:
                self._stream.abort()
        self._speaking.clear()
        logger.debug("Playback stopped (interrupted).")

    def is_speaking(self) -> bool:
        """True while audio is actively playing or queued to play."""
        return self._speaking.is_set()

    # ---------------------------------------------------------------- #
    # Synthesis
    # ---------------------------------------------------------------- #

    def _synthesize_chunk(self, text: str) -> Optional[np.ndarray]:
        """
        Blocking Kokoro inference for a single chunk. Run via asyncio.to_thread.

        Kokoro's pipeline is a generator yielding (graphemes, phonemes, audio)
        tuples per segment; for a single short chunk we expect one segment,
        but we concatenate defensively in case it splits internally.
        """
        segments = self._pipeline(
            text,
            voice=self.config.voice,
            speed=self.config.speed,
        )

        audio_parts = []
        for _graphemes, _phonemes, audio in segments:
            audio_parts.append(np.asarray(audio, dtype=np.float32))

        if not audio_parts:
            return None
        return np.concatenate(audio_parts) if len(audio_parts) > 1 else audio_parts[0]

    async def _enqueue_audio(self, audio: Optional[np.ndarray]) -> None:
        """Put a (possibly None / end-marker) audio chunk on the playback queue."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._audio_queue.put, audio)

    # ---------------------------------------------------------------- #
    # Playback (background thread, decoupled from generation/event loop)
    # ---------------------------------------------------------------- #

    def _ensure_playback_thread(self) -> None:
        if self._playback_thread is not None and self._playback_thread.is_alive():
            return
        self._playback_thread = threading.Thread(
            target=self._playback_loop, daemon=True, name="tts-playback"
        )
        self._playback_thread.start()

    def _is_stream_active(self) -> bool:
        return self._stream is not None and self._stream.active

    def _playback_loop(self) -> None:
        """
        Runs on a dedicated thread for the lifetime of the manager. Opens an
        output stream per speak() call's audio sequence and writes chunks as
        they arrive, exiting cleanly on the end-of-utterance marker or a
        stop() interruption.
        """
        with self._playback_lock:
            self._stream = sd.OutputStream(
                samplerate=SAMPLE_RATE, channels=1, dtype="float32"
            )
            self._stream.start()

        while True:
            try:
                audio = self._audio_queue.get(timeout=0.5)
            except queue.Empty:
                if self._stop_requested.is_set():
                    break
                continue

            if audio is None:
                # End-of-utterance marker for this speak() call.
                break
            if self._stop_requested.is_set():
                break

            try:
                self._stream.write(audio)
            except sd.PortAudioError:
                # Stream was aborted by stop() concurrently; exit quietly.
                break
