"""
Voice I/O for the AI tutor: STT (whisper.cpp + Silero VAD), TTS (Kokoro),
and the real-time VoiceLoop connecting both with barge-in support.
"""
from .stt import VoiceInputManager, VADConfig, STTConfig
from .tts import VoiceOutputManager, TTSConfig
from .voice_loop import VoiceLoop, VoiceLoopConfig
from .voice_session import VoiceSession, VoiceSessionConfig

__all__ = [
    "VoiceInputManager",
    "VADConfig",
    "STTConfig",
    "VoiceOutputManager",
    "TTSConfig",
    "VoiceLoop",
    "VoiceLoopConfig",
    "VoiceSession",
    "VoiceSessionConfig",
]
