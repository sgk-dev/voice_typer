"""Unit tests for SgkSoundCues (sounddevice faked)."""

from __future__ import annotations

import sys
from types import ModuleType

import numpy as np
import pytest

from sgk_voice_typer.feedback.cues import SgkSoundCues, _blip


class _FakeSd:
    def __init__(self) -> None:
        self.played: list[tuple[np.ndarray, int]] = []
        self.raise_exc: Exception | None = None

    def play(self, wave, sr):
        if self.raise_exc is not None:
            raise self.raise_exc
        self.played.append((wave, sr))


@pytest.fixture
def fake_sd(monkeypatch: pytest.MonkeyPatch) -> _FakeSd:
    fake = _FakeSd()
    mod = ModuleType("sounddevice")
    mod.play = fake.play  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sounddevice", mod)
    return fake


def test_blip_is_nonempty_float32() -> None:
    w = _blip((440.0, 880.0))
    assert w.dtype == np.float32
    assert w.size > 1000
    assert abs(float(w.max())) <= 1.0


def test_start_and_stop_play_distinct_waves(fake_sd: _FakeSd) -> None:
    cues = SgkSoundCues(enabled=True, volume=0.5)
    cues.play_start()
    cues.play_stop()
    assert len(fake_sd.played) == 2
    start_wave, stop_wave = fake_sd.played[0][0], fake_sd.played[1][0]
    assert not np.array_equal(start_wave, stop_wave)
    assert float(np.abs(start_wave).max()) <= 0.5 + 1e-6


def test_disabled_plays_nothing(fake_sd: _FakeSd) -> None:
    SgkSoundCues(enabled=False, volume=0.5).play_start()
    assert fake_sd.played == []


def test_zero_volume_plays_nothing(fake_sd: _FakeSd) -> None:
    SgkSoundCues(enabled=True, volume=0.0).play_start()
    assert fake_sd.played == []


def test_playback_exception_is_swallowed(fake_sd: _FakeSd) -> None:
    fake_sd.raise_exc = RuntimeError("no output device")
    SgkSoundCues(enabled=True, volume=0.5).play_start()  # must not raise


def test_sgk_set_updates_volume(fake_sd: _FakeSd) -> None:
    cues = SgkSoundCues(enabled=True, volume=0.1)
    cues.sgk_set(enabled=True, volume=0.4)
    cues.play_start()
    assert float(np.abs(fake_sd.played[0][0]).max()) <= 0.4 + 1e-6
