"""faster-whisper wrapper.

The model is loaded once and kept resident (VRAM on CUDA). ``transcribe`` takes
a float32 mono waveform and returns the recognised text, or ``None`` when
Whisper is not confident speech occurred.

Privacy: at INFO level only the character count, language and durations are
logged - never the recognised text. The text itself goes to DEBUG only.
"""

from __future__ import annotations

import time
from typing import Any

import numpy as np

from sgk_voice_typer.utils.logger import sgk_get_logger

_logger = sgk_get_logger(__name__)


class SgkTranscriber:
    def __init__(
        self,
        name: str = "large-v3-turbo",
        device: str = "cuda",
        compute_type: str = "float16",
        language: str = "auto",
        beam_size: int = 5,
        no_speech_threshold: float = 0.5,
        model: Any | None = None,
    ) -> None:
        self._language = None if language == "auto" else language
        self._beam_size = beam_size
        self._no_speech_threshold = no_speech_threshold

        if model is not None:
            self._model = model
            return

        from faster_whisper import WhisperModel

        _logger.info(
            "sgk_model_loading",
            extra={"name": name, "device": device, "compute_type": compute_type},
        )
        t0 = time.monotonic()
        self._model = WhisperModel(name, device=device, compute_type=compute_type)
        _logger.info(
            "sgk_model_loaded", extra={"load_s": round(time.monotonic() - t0, 1)}
        )

    def transcribe(self, audio: np.ndarray) -> str | None:
        """Return recognised text, or None on silence / low confidence."""
        if audio is None or audio.size == 0:
            return None

        t0 = time.monotonic()
        segments, info = self._model.transcribe(
            audio,
            language=self._language,
            beam_size=self._beam_size,
            vad_filter=True,
            no_speech_threshold=self._no_speech_threshold,
        )

        parts = [s.text.strip() for s in segments if s.text and s.text.strip()]
        if not parts:
            _logger.info(
                "sgk_transcribe_empty",
                extra={
                    "lang": getattr(info, "language", None),
                    "audio_s": round(getattr(info, "duration", 0.0), 1),
                    "infer_s": round(time.monotonic() - t0, 2),
                },
            )
            return None

        text = " ".join(parts)
        _logger.info(
            "sgk_transcribe",
            extra={
                "chars": len(text),
                "lang": getattr(info, "language", None),
                "audio_s": round(getattr(info, "duration", 0.0), 1),
                "infer_s": round(time.monotonic() - t0, 2),
            },
        )
        _logger.debug("sgk_transcribe_text", extra={"text": text})
        return text
