from __future__ import annotations

import numpy as np
from abc import ABC, abstractmethod
from typing import Optional


class AudioSource(ABC):
    """Produces audio frames for VoiceInputManager."""

    @abstractmethod
    async def start(self) -> None:
        ...

    @abstractmethod
    async def stop(self) -> None:
        ...

    @abstractmethod
    async def read_frame(self) -> Optional[np.ndarray]:
        """Return next audio frame or None when stream ends."""
        ...

    @property
    @abstractmethod
    def sample_rate(self) -> int:
        ...

    @property
    @abstractmethod
    def frame_size(self) -> int:
        ...


class AudioSink(ABC):
    """Consumes audio chunks from VoiceOutputManager."""

    @abstractmethod
    async def start(self) -> None:
        ...

    @abstractmethod
    def write(self, audio: np.ndarray) -> None:
        """Write audio chunk for playback. Called from playback thread."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Stop playback and flush."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Release resources."""
        ...

    @property
    @abstractmethod
    def sample_rate(self) -> int:
        ...
