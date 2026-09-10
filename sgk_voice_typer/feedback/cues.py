"""Soft start / stop chimes, in the spirit of a Telegram voice message.

Two gentle notes synthesised with numpy and played through sounddevice - no
audio files, no extra dependencies. A rising pair when recording starts, a
falling pair when it stops. Sine tone plus a quiet octave for warmth, a
raised-cosine attack and an exponential decay so it reads as a soft "pop"
rather than a beep. Playback is non-blocking and every failure is swallowed.
"""

from __future__ import annotations

import numpy as np

from sgk_voice_typer.utils.logger import sgk_get_logger

_logger = sgk_get_logger(__name__)

_SR = 44100
_NOTE_S = 0.11
_GAP_S = 0.028
_ATTACK_S = 0.018
_DECAY = 5.5            # exponential decay rate over the note

# Soft, consonant intervals (C5 and G5).
_LOW, _HIGH = 523.25, 783.99


def _note(freq: float) -> np.ndarray:
    n = int(_SR * _NOTE_S)
    t = np.linspace(0.0, _NOTE_S, n, endpoint=False)
    tone = np.sin(2.0 * np.pi * freq * t) + 0.28 * np.sin(2.0 * np.pi * 2.0 * freq * t)

    env = np.exp(-_DECAY * t).astype("float32")
    a = int(_SR * _ATTACK_S)
    if a > 0 and a < n:
        env[:a] *= 0.5 * (1.0 - np.cos(np.linspace(0.0, np.pi, a)))
    r = min(a, n)
    if r > 0:
        env[-r:] *= 0.5 * (1.0 + np.cos(np.linspace(0.0, np.pi, r)))

    wave = (tone * env).astype("float32")
    peak = float(np.abs(wave).max()) or 1.0
    return wave / peak


def _chime(a: float, b: float) -> np.ndarray:
    gap = np.zeros(int(_SR * _GAP_S), dtype="float32")
    return np.concatenate([_note(a), gap, _note(b)]) * 0.7


class SgkSoundCues:
    def __init__(self, enabled: bool = True, volume: float = 0.18) -> None:
        self._enabled = enabled
        self._volume = max(0.0, min(1.0, volume))
        self._rebuild()

    def _rebuild(self) -> None:
        self._start = _chime(_LOW, _HIGH) * self._volume
        self._stop = _chime(_HIGH, _LOW) * self._volume

    def sgk_set(self, enabled: bool, volume: float) -> None:
        self._enabled = enabled
        self._volume = max(0.0, min(1.0, volume))
        self._rebuild()

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
