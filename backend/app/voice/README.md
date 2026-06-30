# backend/app/voice

Speech-to-Text (`stt.py`), Text-to-Speech (`tts.py`), and the real-time
`VoiceLoop` (`voice_loop.py`) connecting both with barge-in support.

## STT — `stt.py`

`VoiceInputManager`: mic capture (sounddevice) -> Silero VAD (speech boundary
detection) -> whisper.cpp `medium.en` (Metal-accelerated transcription).

### How it works

1. Audio streams in continuously at 16kHz, 32ms frames.
2. Each frame is scored by Silero VAD for speech probability.
3. On speech start: buffer begins, seeded with a short pre-roll so the first
   phoneme isn't clipped.
4. On speech end (silence sustained for `end_of_speech_silence_ms`): the
   buffered utterance is finalized.
5. Utterances under `min_utterance_ms` (default 500ms) are discarded as
   noise/taps/coughs.
6. Finalized utterances are transcribed via whisper.cpp in a thread executor
   (`asyncio.to_thread`) so the event loop stays responsive.
7. Transcribed text is pushed to an async queue, consumable via
   `manager.listen()` (async generator) or an `on_transcription` callback.

### Latency budget (~1.5s target)

- `end_of_speech_silence_ms` (default 600ms) — time to confirm the child
  stopped talking. Lower = faster but risks cutting off mid-sentence pauses.
- whisper.cpp `medium.en` inference on M2 (Metal) — typically several hundred
  ms for short utterances.
- These two dominate total latency; tune `VADConfig.end_of_speech_silence_ms`
  first if the 1.5s target isn't met in practice.

### Edge cases handled

| Case | Handling |
|---|---|
| Background noise | VAD probability threshold filters non-speech; short blips still pass `min_utterance_ms` filter |
| Utterances < 0.5s | Discarded before reaching whisper (coughs, taps, mic bumps) |
| Silence / no speech | No whisper call is ever made — VAD gate prevents it |
| Tutor (TTS) is speaking | `manager.paused = True` set externally; mic input is dropped, in-progress utterance reset, prevents agent hearing itself |
| Runaway open mic | `max_utterance_ms` safety valve forces a cutoff and transcription |
| Empty whisper output | Filtered before being queued/dispatched |

### Pausing during TTS playback

The orchestrator / voice loop (later layer) is expected to set
`manager.paused = True` while `VoiceOutputManager` is speaking, and
`False` once playback ends, to prevent feedback loops. This wiring happens
in Build Layer 4 (Voice Loop).

## TTS — `tts.py`

`VoiceOutputManager`: text -> Kokoro TTS (kokoro-82m, chunked by sentence) ->
streaming playback via sounddevice, with immediate interrupt support.

### How it works

1. Input text is split into sentence-sized chunks (`_split_into_chunks`),
   capped at `max_chunk_chars` (default 220). Long sentences without
   punctuation breaks fall back to comma-splitting, then hard-wrapping.
2. Each chunk is synthesized via Kokoro in a thread executor
   (`asyncio.to_thread`) so generation never blocks the event loop.
3. Synthesized audio chunks are pushed onto a queue consumed by a dedicated
   playback thread, which writes them to a `sounddevice.OutputStream`.
4. Because playback starts as soon as the first chunk is ready — not after
   the full text is synthesized — perceived latency (time-to-first-audio)
   is much lower than batch synthesis.
5. `stop()` sets an interrupt flag, drains the queue, and aborts the active
   stream immediately, enabling fast barge-in when a child starts talking
   over the tutor.

### Voice choice

Default voice is `af_heart` — Kokoro's warmest, calmest English voice,
well suited to a patient tutor persona. Override via `TTSConfig(voice=...)`;
`af_bella` is a reasonable alternative if a different tone is preferred.

### API

```python
manager = VoiceOutputManager()
await manager.start()              # loads Kokoro pipeline once

await manager.speak("Let's think about this differently.")
manager.is_speaking()              # True while audio is playing/queued
manager.stop()                     # immediate interrupt (barge-in)

await manager.shutdown()
```

Calling `speak()` again while already speaking automatically interrupts the
previous utterance first — mirrors a tutor responding to a new prompt rather
than queuing speech behind the old one.

### Edge cases handled

| Case | Handling |
|---|---|
| Child interrupts mid-sentence | `stop()` aborts the output stream and drains queued audio within ms |
| Very long explanation | Chunked synthesis — playback begins on first sentence, not after full generation |
| Single sentence longer than `max_chunk_chars` | Falls back to comma-splitting, then hard-wrap, to avoid Kokoro choking on oversized input |
| `speak()` called while already speaking | Previous utterance is stopped first; new one takes over (no queueing) |
| Empty/whitespace-only text | No-op, returns immediately |
| Stream aborted concurrently by `stop()` | Playback thread catches `PortAudioError` and exits quietly instead of crashing |

### Testing

```bash
uv run python backend/app/voice/test_tts.py                  # speaks a sample explanation
uv run python backend/app/voice/test_tts.py --interrupt       # tests stop() mid-speech
uv run python backend/app/voice/test_tts.py --voice af_bella  # try a different voice
```

## VoiceLoop — `voice_loop.py`

Connects `VoiceInputManager` and `VoiceOutputManager` into a continuous,
barge-in-aware conversational loop.

### The pause/barge-in tension

The requirements ask for two things that are in tension: pause listening
while the tutor speaks (avoid feedback), but still detect and react if the
child interrupts. These are reconciled with two layers:

1. **Transcription gate** (`VoiceInputManager.paused`): while the tutor is
   speaking, full STT (utterance buffering + whisper transcription) is
   paused, so the tutor's own voice is never transcribed as if the child
   said it.
2. **Barge-in watcher** (`_BargeInWatcher`, always active): a lightweight,
   independent VAD check runs on every raw mic frame via a `frame_observer`
   hook on `VoiceInputManager` — fired in addition to, not instead of,
   VoiceInputManager's own internal processing, so there's no contention
   over its audio queue. It uses a higher speech-probability threshold and
   requires several consecutive speech frames before triggering, to avoid
   false positives from the tutor's own audio leaking into the mic.

On barge-in detection: `VoiceOutputManager.stop()` is called immediately,
the in-flight `speak()` task is cancelled, and `VoiceInputManager.paused`
is flipped back to `False` — so the interrupting utterance is captured and
transcribed normally by VoiceInputManager's own pipeline from that point.

### API

```python
async def on_user_speech(text: str):
    response = await get_tutor_response(text)
    await loop.speak(response)

loop = VoiceLoop(on_user_speech=on_user_speech)
await loop.start()
...
await loop.stop()
```

### Edge cases handled

| Case | Handling |
|---|---|
| Tutor's own voice picked up by mic | Transcription paused during TTS playback; only the dedicated barge-in watcher (higher threshold) is active |
| Child interrupts mid-sentence | Barge-in watcher triggers after N consecutive speech frames -> TTS stopped, listening resumes immediately |
| False-positive barge-in (echo/noise) | Higher probability threshold + consecutive-frame requirement reduces spurious triggers vs. normal VAD |
| Loop shutdown mid-speech | `stop()` cancels all tasks (listen, barge-in, in-flight speak) cleanly |
| `on_user_speech` callback is sync or async | `_dispatch` handles both transparently |

### Testing (echo mode, no LLM)

```bash
uv run python backend/app/voice/test_voice_loop.py
```

Speak into the mic — the tutor echoes back "You said: ...". Try
interrupting the echo mid-sentence to manually verify barge-in: the echo
should cut off immediately and the loop should pick up your new utterance.
This validates the full loop end-to-end before any LLM/agent is wired in
(that begins at Build Layer 7 — Tutor Agent).

## Testing (STT)

```bash
uv run python backend/app/voice/test_stt.py --list-devices
uv run python backend/app/voice/test_stt.py
uv run python backend/app/voice/test_stt.py --device 2
```

Speak into the mic; transcriptions print as utterances complete.

## Prerequisites

- `whispercpp` package installed with Metal-enabled wheels (Apple Silicon)
- `kokoro` package (kokoro-82m model weights download on first run, then cached)
- Internet access on first run only, to download model weights for both
  whisper.cpp and Kokoro (cached locally afterward — no further network
  dependency)
- A working microphone and speaker accessible to `sounddevice` / PortAudio
