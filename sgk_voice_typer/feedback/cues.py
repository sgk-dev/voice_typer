"""Short start / stop sound cues, like a Telegram voice message.

Two two-note blips synthesised with numpy and played through sounddevice - no
audio files, no extra dependencies. Rising on record start, falling on stop.
Playback is non-blocking and every failure is swallowed: a missing output
device must never break dictation.
"""

from __future__ import annotations

import numpy as np

from sgk_voice_typer.utils.logger import sgk_get_logger

_logger = sgk_get_logger(__name__)

_SR = 44100
_NOTE_S = 0.070
_GAP_S = 0.010
_FADE_S = 0.006


def _tone(freq: float, seconds: float) -> np.ndarray:
    t = np.linspace(0.0, seconds, int(_SR * seconds), endpoint=False)
    wave = np.sin(2.0 * np.pi * freq * t).astype("float32")
    fade = int(_SR * _FADE_S)
    if fade > 0 and wave.size > 2 * fade:
        ramp = np.linspace(0.0, 1.0, fade, dtype="float32")
        wave[:fade] *= ramp
        wave[-fade:] *= ramp[::-1]
    return wave


def _blip(freqs: tuple[float, float]) -> np.ndarray:
    gap = np.zeros(int(_SR * _GAP_S), dtype="float32")
    return np.concatenate([_tone(freqs[0], _NOTE_S), gap, _tone(freqs[1], _NOTE_S)])


class SgkSoundCues:
    def __init__(self, enabled: bool = True, volume: float = 0.25) -> None:
        self._enabled = enabled
        self._volume = max(0.0, min(1.0, volume))
        self._start = _blip((660.0, 990.0)) * self._volume
        self._stop = _blip((990.0, 660.0)) * self._volume

    def sgk_set(self, enabled: bool, volume: float) -> None:
        self._enabled = enabled
        self._volume = max(0.0, min(1.0, volume))
        self._start = _blip((660.0, 990.0)) * self._volume
        self._stop = _blip((990.0, 660.0)) * self._volume

    def play_start(self) -> None:
        self._play(self._start)

    def play_stop(self) -> None:
        self._play(self._stop)

    def _play(self, wave: np.ndarray) -> None:
        if not self._enabled or self._volume <= 0.0:
            return
        try:
            import sounddevice as sd

            sd.play(wave, _SR)
        except Exception as exc:
            _logger.debug("sgk_cue_play_failed", extra={"error": str(exc)})
