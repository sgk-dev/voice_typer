from __future__ import annotations

import logging
import numpy as np
from faster_whisper import WhisperModel

from voice_typer.config import Config

_logger = logging.getLogger(__name__)


class Transcriber:
    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        _logger.info("Loading Whisper model %s on %s...", cfg.model_name, cfg.device)
        self._model = WhisperModel(
            cfg.model_name,
            device=cfg.device,
            compute_type=cfg.compute_type,
        )
        _logger.info("Model loaded.")

    def transcribe(self, audio: np.ndarray) -> str | None:
        """Return transcribed text, or None if silence/no speech detected."""
        if audio.size == 0:
            return None

        language = self._cfg.language if self._cfg.language != "auto" else None

        segments, info = self._model.transcribe(
            audio,
            language=language,
            beam_size=5,
            vad_filter=True,
            no_speech_threshold=0.5,
        )

        lines = []
        for segment in segments:
            text = segment.text.strip()
            if text:
                lines.append(text)

        if not lines:
            return None

        result = " ".join(lines)
        _logger.info("[TRANSCRIBE] %r (lang=%s, duration=%.1fs)", result, info.language, info.duration)
        return result
