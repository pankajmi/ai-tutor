"""
Speech-to-Text module for the local AI tutor.

Pipeline:
    mic (sounddevice) -> Silero VAD (speech boundary detection) -> whisper.cpp (medium.en)

Design notes:
- VAD runs continuously on small audio frames to decide speech vs silence.
  Whisper is only invoked once a complete utterance (speech_start -> speech_end)
  has been captured, so we never waste GPU/CPU transcribing silence.
- Whisper inference is synchronous/CPU-or-GPU-bound, so it is run in a thread
  executor via asyncio.to_thread() to stay non-blocking for FastAPI's event loop.
- Target latency: transcription ready within ~1.5s of the child finishing
  speaking. This is dominated by (a) VAD's end-of-speech hangover window and
  (b) whisper.cpp's inference time on M2 (Metal-accelerated, medium.en).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np
import sounddevice as sd

logger = logging.getLogger("ai_tutor.voice.stt")

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

SAMPLE_RATE = 16_000  # required by both Silero VAD and whisper.cpp
FRAME_DURATION_MS = 32  # Silero VAD operates on fixed-size frames
FRAME_SAMPLES = int(SAMPLE_RATE * FRAME_DURATION_MS / 1000)


@dataclass
class VADConfig:
    """Tunable parameters for speech boundary detection."""

    # Probability threshold above which a frame is considered speech.
    speech_threshold: float = 0.5

    # How many consecutive ms of silence after speech before we consider
    # the utterance finished. Children naturally pause 1-2 seconds to
    # think mid-sentence; setting this too short causes the tutor to
    # barge in with a partial utterance. 1500ms gives enough room for
    # thinking pauses without feeling sluggish on actual end-of-speech.
    end_of_speech_silence_ms: int = 1500

    # Minimum utterance duration to bother transcribing. Filters out coughs,
    # taps, "um" stubs, and other sub-0.5s noise blips.
    min_utterance_ms: int = 500

    # Maximum utterance duration as a safety valve (avoids unbounded buffers
    # if VAD fails to detect end-of-speech, e.g. child leaves mic open).
    max_utterance_ms: int = 30_000

    # Rolling pre-roll buffer kept before speech is detected, so the very
    # first phoneme of an utterance isn't clipped while VAD "warms up".
    pre_roll_ms: int = 300


@dataclass
class STTConfig:
    """Whisper.cpp model configuration."""

    model_name: str = "medium.en"
    # whispercpp uses Metal acceleration automatically on Apple Silicon when
    # built with the appropriate backend; no explicit device flag is needed
    # for the high-level Python binding, but we keep this for clarity/future use.
    use_gpu: bool = True
    language: str = "en"
    # Number of threads for any CPU-side work whisper.cpp still performs.
    n_threads: int = 4


@dataclass
class _UtteranceBuffer:
    """Accumulates raw audio frames for a single in-progress utterance."""

    frames: list[np.ndarray] = field(default_factory=list)
    started_at: float = 0.0

    def append(self, frame: np.ndarray) -> None:
        self.frames.append(frame)

    def duration_ms(self) -> float:
        total_samples = sum(len(f) for f in self.frames)
        return (total_samples / SAMPLE_RATE) * 1000

    def as_array(self) -> np.ndarray:
        if not self.frames:
            return np.array([], dtype=np.float32)
        return np.concatenate(self.frames)

    def clear(self) -> None:
        self.frames.clear()


# --------------------------------------------------------------------------
# VoiceInputManager
# --------------------------------------------------------------------------


class VoiceInputManager:
    """
    Captures microphone audio, detects speech segments with Silero VAD,
    and transcribes completed utterances with whisper.cpp.

    Usage:
        manager = VoiceInputManager()
        await manager.start()

        async for text in manager.listen():
            print("Child said:", text)

        await manager.stop()

    Or, with a callback style:
        manager = VoiceInputManager(on_transcription=handle_text)
        await manager.start()
        ...
        await manager.stop()
    """

    def __init__(
        self,
        vad_config: Optional[VADConfig] = None,
        stt_config: Optional[STTConfig] = None,
        on_transcription: Optional[Callable[[str], None]] = None,
        device: Optional[int | str] = None,
    ) -> None:
        self.vad_config = vad_config or VADConfig()
        self.stt_config = stt_config or STTConfig()
        self._on_transcription = on_transcription
        self._device = device

        self._vad_model = None  # lazy-loaded Silero VAD model
        self._whisper_model = None  # lazy-loaded whisper.cpp model

        self._stream: Optional[sd.InputStream] = None
        self._audio_queue: asyncio.Queue[np.ndarray] = asyncio.Queue()
        self._transcription_queue: asyncio.Queue[str] = asyncio.Queue()

        self._is_speaking = False
        self._utterance = _UtteranceBuffer()
        self._pre_roll: list[np.ndarray] = []
        self._silence_ms_since_speech = 0.0

        self._running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._processing_task: Optional[asyncio.Task] = None

        # Paused while TTS is speaking (set externally by the voice loop /
        # orchestrator layer to avoid the tutor hearing itself).
        self.paused = False

        # Optional callback invoked synchronously once per captured raw
        # audio frame, regardless of `paused` state. Used by VoiceLoop
        # (Layer 4) to feed an independent barge-in detector without
        # contending with this manager's own audio_queue consumption.
        # Signature: (frame: np.ndarray) -> None. Must be cheap/non-blocking
        # since it runs inline in the audio processing loop.
        self.frame_observer: Optional[Callable[[np.ndarray], None]] = None

    # ---------------------------------------------------------------- #
    # Lifecycle
    # ---------------------------------------------------------------- #

    async def start(self) -> None:
        """Load models and begin capturing microphone audio."""
        self._loop = asyncio.get_running_loop()

        logger.info("Loading Silero VAD model...")
        self._vad_model = await asyncio.to_thread(self._load_vad_model)

        logger.info("Loading whisper.cpp model: %s", self.stt_config.model_name)
        self._whisper_model = await asyncio.to_thread(self._load_whisper_model)

        self._running = True
        self._open_input_stream()
        self._processing_task = asyncio.create_task(self._process_audio_loop())
        logger.info("VoiceInputManager started.")

    async def stop(self) -> None:
        """Stop capturing and release resources."""
        self._running = False
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        if self._processing_task is not None:
            self._processing_task.cancel()
            try:
                await self._processing_task
            except asyncio.CancelledError:
                pass
        logger.info("VoiceInputManager stopped.")

    async def listen(self):
        """
        Async generator yielding transcribed text as utterances complete.

        Example:
            async for text in manager.listen():
                ...
        """
        while self._running:
            text = await self._transcription_queue.get()
            yield text

    # ---------------------------------------------------------------- #
    # Model loading (run in thread executor — these are blocking calls)
    # ---------------------------------------------------------------- #

    def _load_vad_model(self):
        """
        Loads Silero VAD via the `silero-vad` package.

        silero-vad exposes a simple load_silero_vad() + get_speech_timestamps()
        API as of recent versions, but for streaming frame-by-frame use we use
        the underlying model's forward() call directly, which returns a
        speech probability per audio chunk.
        """
        from silero_vad import load_silero_vad

        model = load_silero_vad()
        return model

    def _load_whisper_model(self):
        """
        Loads whisper.cpp via the `pywhispercpp` package.

        On Apple Silicon, pywhispercpp uses Metal acceleration automatically
        on M-series chips.
        """
        from pywhispercpp.model import Model

        model = Model(
            self.stt_config.model_name,
            n_threads=self.stt_config.n_threads,
        )
        return model

    # ---------------------------------------------------------------- #
    # Audio capture (sounddevice callback -> asyncio queue bridge)
    # ---------------------------------------------------------------- #

    def _open_input_stream(self) -> None:
        def _callback(indata, frames, time_info, status):
            if status:
                logger.warning("Audio input status: %s", status)
            # Copy because sounddevice reuses the buffer.
            mono = indata[:, 0].copy()
            if self._loop is not None:
                self._loop.call_soon_threadsafe(self._audio_queue.put_nowait, mono)

        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=FRAME_SAMPLES,
            device=self._device,
            callback=_callback,
        )
        self._stream.start()

    # ---------------------------------------------------------------- #
    # VAD + utterance assembly loop
    # ---------------------------------------------------------------- #

    async def _process_audio_loop(self) -> None:
        """
        Consumes raw audio frames, runs VAD per frame, and assembles complete
        utterances. On end-of-speech, dispatches to whisper for transcription.
        """
        frame_duration_ms = FRAME_DURATION_MS

        while self._running:
            frame = await self._audio_queue.get()

            if self.frame_observer is not None:
                self.frame_observer(frame)

            if self.paused:
                # Tutor is currently speaking (TTS) — drop input to avoid
                # the mic picking up the agent's own voice. Also reset any
                # in-progress utterance so we don't stitch together audio
                # from before/after the pause.
                if self._is_speaking:
                    self._reset_utterance_state()
                continue

            speech_prob = await asyncio.to_thread(self._vad_predict, frame)
            is_speech_frame = speech_prob >= self.vad_config.speech_threshold

            if is_speech_frame:
                if not self._is_speaking:
                    # Speech just started — seed buffer with pre-roll so we
                    # don't clip the first phoneme.
                    self._is_speaking = True
                    self._utterance.clear()
                    self._utterance.started_at = time.monotonic()
                    for pre_frame in self._pre_roll:
                        self._utterance.append(pre_frame)
                    logger.debug("Speech started.")

                self._utterance.append(frame)
                self._silence_ms_since_speech = 0.0

                if self._utterance.duration_ms() >= self.vad_config.max_utterance_ms:
                    logger.warning("Max utterance duration reached, forcing cutoff.")
                    await self._finalize_utterance()

            else:
                # Maintain a short rolling pre-roll buffer even during silence,
                # so the next utterance has lead-in context.
                self._pre_roll.append(frame)
                max_pre_roll_frames = max(
                    1, int(self.vad_config.pre_roll_ms / frame_duration_ms)
                )
                if len(self._pre_roll) > max_pre_roll_frames:
                    self._pre_roll.pop(0)

                if self._is_speaking:
                    self._utterance.append(frame)  # include trailing silence
                    self._silence_ms_since_speech += frame_duration_ms

                    if (
                        self._silence_ms_since_speech
                        >= self.vad_config.end_of_speech_silence_ms
                    ):
                        await self._finalize_utterance()

    def _vad_predict(self, frame: np.ndarray) -> float:
        """Run Silero VAD on a single audio frame, returning speech probability."""
        import torch

        tensor = torch.from_numpy(frame)
        with torch.no_grad():
            prob = self._vad_model(tensor, SAMPLE_RATE).item()
        return prob

    def _reset_utterance_state(self) -> None:
        self._is_speaking = False
        self._utterance.clear()
        self._silence_ms_since_speech = 0.0

    async def _finalize_utterance(self) -> None:
        """
        Called when end-of-speech is detected (or max duration safety valve
        triggers). Filters out too-short blips, then dispatches to whisper.
        """
        duration_ms = self._utterance.duration_ms()
        audio = self._utterance.as_array()
        self._reset_utterance_state()

        if duration_ms < self.vad_config.min_utterance_ms:
            logger.debug(
                "Discarding short utterance (%.0fms < %.0fms threshold) — "
                "likely noise/cough/tap.",
                duration_ms,
                self.vad_config.min_utterance_ms,
            )
            return

        logger.debug("Utterance complete (%.0fms). Transcribing...", duration_ms)
        start = time.monotonic()
        text = await asyncio.to_thread(self._transcribe, audio)
        elapsed = time.monotonic() - start
        logger.debug("Transcription took %.2fs: %r", elapsed, text)

        text = text.strip()
        if not text:
            # Whisper sometimes returns empty string for non-speech noise
            # that slipped past VAD (e.g. low-confidence murmurs).
            logger.debug("Empty transcription, discarding.")
            return

        await self._transcription_queue.put(text)
        if self._on_transcription is not None:
            self._on_transcription(text)

    def _transcribe(self, audio: np.ndarray) -> str:
        """Blocking whisper.cpp inference call. Run via asyncio.to_thread."""
        segments = self._whisper_model.transcribe(audio)
        return " ".join(seg.text for seg in segments if seg.text).strip()
