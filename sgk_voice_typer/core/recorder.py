"""Microphone capture for push-to-talk.

``start()`` opens a ``sounddevice`` input stream immediately (called straight
from the hotkey press handler, no polling loop) and ``stop()`` closes it and
returns the captured mono float32 waveform.

Clips shorter than ``min_duration_s`` are dropped - they are almost always a
stray key tap. The hard cap at ``max_duration_s`` against a stuck key is
enforced by the caller (the pipeline), which also owns the transcription
trigger.
"""

from __future__ import annotations

import threading
import time

import numpy as np

from sgk_voice_typer.utils.logger import sgk_get_logger

_logger = sgk_get_logger(__name__)


class SgkRecorder:
    def __init__(
        self,
        sample_rate: int = 16000,
        device: str | int | None = None,
        min_duration_s: float = 0.3,
    ) -> None:
        self._sample_rate = sample_rate
        self._device = device
        self._min_duration_s = min_duration_s
        self._lock = threading.Lock()
        self._chunks: list[np.ndarray] = []
        self._stream = None
        self._t0 = 0.0

    @property
    def is_recording(self) -> bool:
        return self._stream is not None

    def elapsed_s(self) -> float:
        return time.monotonic() - self._t0 if self._stream is not None else 0.0

    def start(self) -> bool:
        """Open the input stream. Returns False if the mic could not be opened."""
        if self._stream is not None:
            return True
        import sounddevice as sd

        with self._lock:
            self._chunks = []

        def _callback(indata, frames, time_info, status) -> None:  # noqa: ANN001
            if status:
                _logger.debug("sgk_audio_status", extra={"status": str(status)})
            with self._lock:
                self._chunks.append(indata.copy())

        try:
            stream = sd.InputStream(
                samplerate=self._sample_rate,
                channels=1,
                dtype="float32",
                device=self._device,
                callback=_callback,
            )
            stream.start()
        except Exception as exc:
            _logger.error("sgk_mic_open_failed", extra={"error": str(exc)})
            return False

        self._stream = stream

        self._t0 = time.monotonic()
        _logger.debug("sgk_recording_started")
        return True

    def stop(self) -> np.ndarray | None:
        """Close the stream and return the waveform, or None if too short/empty."""
        stream, self._stream = self._stream, None
        if stream is None:
            return None
        try:
            stream.stop()
            stream.close()
        except Exception as exc:
            _logger.debug("sgk_mic_close_error", extra={"error": str(exc)})

        duration = time.monotonic() - self._t0
        with self._lock:
            chunks, self._chunks = self._chunks, []

        if not chunks:
            _logger.info("sgk_recording_empty")
            return None

        audio = np.concatenate(chunks, axis=0).reshape(-1).astype("float32")
        if duration < self._min_duration_s:
            _logger.info("sgk_recording_too_short", extra={"dur_s": round(duration, 2)})
            return None

        _logger.debug(
            "sgk_recording_stopped",
            extra={"dur_s": round(duration, 2), "samples": int(audio.size)},
        )
        return audio
