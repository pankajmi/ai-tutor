"""
Real-time voice loop connecting VoiceInputManager (STT) and
VoiceOutputManager (TTS) for the AI tutor.

Design notes:

- Naively "pausing" STT entirely while TTS plays would make barge-in
  impossible — there'd be nothing listening to detect the child starting to
  talk. So VAD-level listening (VoiceInputManager) is never fully stopped;
  instead we use VoiceInputManager.paused as a *transcription/utterance-
  buffering gate*, not a capture gate. A second, lightweight watcher runs
  alongside it specifically to detect barge-in while paused.

- Concretely:
    * Tutor idle (not speaking):  VoiceInputManager fully active.
      Any transcribed utterance -> on_user_speech callback.
    * Tutor speaking (TTS active): VoiceInputManager.paused = True
      (prevents the mic loop from buffering/transcribing the tutor's own
      audio bleed — see VoiceInputManager._process_audio_loop, which resets
      any in-progress utterance and skips frames while paused). A
      *separate*, cheap VAD-only watcher (`_BargeInWatcher`) is fed a copy
      of every raw mic frame via a non-blocking tap, and watches for
      genuine speech onset. The instant it fires, we immediately:
          1. call VoiceOutputManager.stop()      (cut the tutor off)
          2. un-pause VoiceInputManager           (resume real transcription)
      The child's actual utterance is then captured and transcribed
      normally by VoiceInputManager once unpaused, and delivered via the
      same on_user_speech callback.

- Frame tapping: VoiceInputManager owns the single audio_queue consumed by
  its own processing loop. Rather than competing for items on that queue
  (which would race/duplicate consumption), VoiceLoop installs itself as a
  `frame_observer` callback on VoiceInputManager — fired once per captured
  frame, independent of and in addition to VoiceInputManager's own internal
  consumption. This requires VoiceInputManager to support an optional
  `frame_observer` hook (see stt.py); each frame is delivered to exactly one
  primary consumer (VoiceInputManager's own loop) and fanned out to zero or
  more observers (this barge-in watcher) with no shared-queue contention.

- Everything is asyncio-native; the loop subscribes to
  VoiceInputManager.listen() (an async generator) as its primary driver.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional, Union

import numpy as np

from .stt import VoiceInputManager
from .tts import VoiceOutputManager

logger = logging.getLogger("ai_tutor.voice.loop")

OnUserSpeech = Callable[[str], Union[None, Awaitable[None]]]


@dataclass
class VoiceLoopConfig:
    # Probability threshold for the barge-in watcher to consider a frame
    # "speech" while the tutor is talking. Kept on the higher side relative
    # to normal VAD to reduce false positives from the tutor's own audio
    # leaking into the mic (especially on laptop built-in mic/speaker setups
    # without headphones).
    barge_in_speech_threshold: float = 0.65

    # Consecutive speech frames required before triggering a barge-in. A
    # single frame is too noise-prone; a short run of frames confirms
    # genuine sustained speech rather than a click/pop.
    barge_in_consecutive_frames: int = 3


class _BargeInWatcher:
    """
    Lightweight, dedicated speech-onset detector used only while the tutor
    is speaking. Reuses the same Silero VAD model already loaded by
    VoiceInputManager (no duplicate model load) but runs its own frame
    accumulation logic, independent of the full utterance-buffering /
    transcription pipeline in VoiceInputManager.
    """

    def __init__(self, vad_predict_fn, config: VoiceLoopConfig) -> None:
        self._vad_predict = vad_predict_fn
        self._config = config
        self._consecutive_speech_frames = 0

    def reset(self) -> None:
        self._consecutive_speech_frames = 0

    async def check(self, frame: np.ndarray) -> bool:
        """Returns True the moment sustained speech onset is detected."""
        prob = await asyncio.to_thread(self._vad_predict, frame)
        if prob >= self._config.barge_in_speech_threshold:
            self._consecutive_speech_frames += 1
        else:
            self._consecutive_speech_frames = 0

        return self._consecutive_speech_frames >= self._config.barge_in_consecutive_frames


class VoiceLoop:
    """
    Wires VoiceInputManager and VoiceOutputManager into a continuous,
    barge-in-aware conversational loop.

    Usage:
        async def handle_speech(text: str):
            response = await get_tutor_response(text)
            await loop.speak(response)

        loop = VoiceLoop(on_user_speech=handle_speech)
        await loop.start()
        ...
        await loop.stop()
    """

    def __init__(
        self,
        on_user_speech: OnUserSpeech,
        voice_input: Optional[VoiceInputManager] = None,
        voice_output: Optional[VoiceOutputManager] = None,
        config: Optional[VoiceLoopConfig] = None,
    ) -> None:
        self.on_user_speech = on_user_speech
        self.voice_input = voice_input or VoiceInputManager()
        self.voice_output = voice_output or VoiceOutputManager()
        self.config = config or VoiceLoopConfig()

        self._barge_in_watcher: Optional[_BargeInWatcher] = None
        self._running = False

        self._listen_task: Optional[asyncio.Task] = None
        self._current_speak_task: Optional[asyncio.Task] = None

        # Frames are fanned out to this queue via VoiceInputManager's
        # frame_observer hook (fired once per captured frame, in addition
        # to — not instead of — VoiceInputManager's own internal
        # consumption). No contention: VoiceInputManager's processing loop
        # is the sole consumer of its own audio_queue; this is a separate,
        # additional sink.
        self._barge_in_frame_queue: "asyncio.Queue[np.ndarray]" = asyncio.Queue()
        self._barge_in_task: Optional[asyncio.Task] = None

    # ---------------------------------------------------------------- #
    # Lifecycle
    # ---------------------------------------------------------------- #

    async def start(self) -> None:
        # Install the frame tap before starting capture so no frames are
        # missed once the input stream opens.
        self.voice_input.frame_observer = self._on_raw_frame

        await self.voice_input.start()
        await self.voice_output.start()

        self._barge_in_watcher = _BargeInWatcher(
            vad_predict_fn=self.voice_input._vad_predict,  # reuse loaded VAD model
            config=self.config,
        )

        self._running = True
        self._listen_task = asyncio.create_task(self._listen_loop())
        self._barge_in_task = asyncio.create_task(self._barge_in_loop())
        logger.info("VoiceLoop started.")

    async def stop(self) -> None:
        self._running = False
        self.voice_input.frame_observer = None

        for task in (self._listen_task, self._barge_in_task, self._current_speak_task):
            if task is not None:
                task.cancel()

        for task in (self._listen_task, self._barge_in_task, self._current_speak_task):
            if task is not None:
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        await self.voice_output.shutdown()
        await self.voice_input.stop()
        logger.info("VoiceLoop stopped.")

    def _on_raw_frame(self, frame: np.ndarray) -> None:
        """
        Called synchronously by VoiceInputManager for every captured frame
        (regardless of paused state). Only relevant to the barge-in watcher
        while the tutor is speaking; we fan out unconditionally and let the
        barge-in loop decide whether to act on it, keeping this hook itself
        trivial and non-blocking.
        """
        try:
            self._barge_in_frame_queue.put_nowait(frame)
        except asyncio.QueueFull:
            # Should not happen (unbounded queue), but never let a frame
            # tap raise into VoiceInputManager's capture path.
            pass

    # ---------------------------------------------------------------- #
    # Speaking (tutor turn)
    # ---------------------------------------------------------------- #

    async def speak(self, text: str) -> None:
        """
        Speak `text` via the tutor's voice. Pauses STT transcription/
        utterance-buffering for the duration — the barge-in watcher remains
        active throughout via the independent frame tap.
        """
        self.voice_input.paused = True
        if self._barge_in_watcher is not None:
            self._barge_in_watcher.reset()

        try:
            self._current_speak_task = asyncio.create_task(self.voice_output.speak(text))
            await self._current_speak_task
        except asyncio.CancelledError:
            # Cancelled due to barge-in or shutdown — voice_output.stop()
            # has already been (or will be) called by the barge-in path.
            pass
        finally:
            self._current_speak_task = None
            # Only resume listening here if we weren't interrupted — the
            # barge-in path handles its own un-pause sequencing directly.
            if not self.voice_output.is_speaking():
                self.voice_input.paused = False

    # ---------------------------------------------------------------- #
    # Main listening loop (drives on_user_speech)
    # ---------------------------------------------------------------- #

    async def _listen_loop(self) -> None:
        """
        Consumes finalized transcriptions from VoiceInputManager and
        dispatches them to on_user_speech. VoiceInputManager itself only
        produces transcriptions while unpaused — i.e. tutor is idle, or a
        barge-in has just unpaused it — so no additional gating is needed
        here.
        """
        async for text in self.voice_input.listen():
            if not self._running:
                break
            logger.info("Child said: %r", text)
            await self._dispatch(text)

    async def _dispatch(self, text: str) -> None:
        result = self.on_user_speech(text)
        if asyncio.iscoroutine(result):
            await result

    # ---------------------------------------------------------------- #
    # Barge-in watcher loop (active only while tutor is speaking)
    # ---------------------------------------------------------------- #

    async def _barge_in_loop(self) -> None:
        """
        Consumes the frame tap fed by _on_raw_frame and watches for
        sustained speech onset while the tutor is currently talking. On
        trigger: stops TTS and un-pauses VoiceInputManager so the
        interrupting utterance gets captured and transcribed normally by
        VoiceInputManager's own pipeline from that point forward.
        """
        assert self._barge_in_watcher is not None

        while self._running:
            frame = await self._barge_in_frame_queue.get()

            if not self.voice_output.is_speaking():
                # Tutor isn't talking — no barge-in possible right now.
                # VoiceInputManager's own pipeline is already handling
                # this frame independently; nothing to do here.
                self._barge_in_watcher.reset()
                continue

            triggered = await self._barge_in_watcher.check(frame)
            if triggered:
                logger.info("Barge-in detected — child is speaking over the tutor.")
                self.voice_output.stop()
                if self._current_speak_task is not None:
                    self._current_speak_task.cancel()
                self.voice_input.paused = False
                self._barge_in_watcher.reset()
