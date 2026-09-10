from __future__ import annotations

import logging

import numpy as np
import sounddevice as sd

_logger = logging.getLogger(__name__)


def record_while_held(sample_rate: int = 16000, device: str | int | None = None) -> np.ndarray:
    """Record audio from mic until user presses Enter. Returns float32 numpy array."""
    chunks: list[np.ndarray] = []

    def _callback(indata: np.ndarray, frames: int, time, status) -> None:
        chunks.append(indata.copy())

    _logger.info("Recording... press Enter to stop.")
    with sd.InputStream(
        samplerate=sample_rate,
        channels=1,
        dtype="float32",
        device=device,
        callback=_callback,
    ):
        input()

    if not chunks:
        return np.zeros(0, dtype="float32")

    audio = np.concatenate(chunks, axis=0).flatten()
    return audio
