"""Unit tests for SgkRecorder (fake sounddevice stream)."""

from __future__ import annotations

import sys
import time
from types import ModuleType

import numpy as np
import pytest

from sgk_voice_typer.core.recorder import SgkRecorder


class _FakeStream:
    instances: list["_FakeStream"] = []

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.callback = kwargs.get("callback")
        self.started = False
        self.closed = False
        _FakeStream.instances.append(self)

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False

    def close(self) -> None:
        self.closed = True

    def feed(self, samples: np.ndarray) -> None:
        self.callback(samples.reshape(-1, 1), len(samples), None, None)


@pytest.fixture(autouse=True)
def _fake_sounddevice(monkeypatch: pytest.MonkeyPatch):
    _FakeStream.instances.clear()
    mod = ModuleType("sounddevice")
    mod.InputStream = _FakeStream  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sounddevice", mod)
    yield


def test_normal_capture_returns_concatenated_float32() -> None:
    rec = SgkRecorder(sample_rate=16000, min_duration_s=0.1)
    assert rec.start() is True
    assert rec.is_recording is True

    stream = _FakeStream.instances[-1]
    stream.feed(np.ones(8000, dtype="float32"))
    stream.feed(np.ones(8000, dtype="float32") * 0.5)
    rec._t0 = time.monotonic() - 1.0  # pretend 1 s elapsed

    audio = rec.stop()
    assert audio is not None
    assert audio.dtype == np.float32
    assert audio.shape == (16000,)
    assert rec.is_recording is False
    assert stream.closed is True


def test_too_short_clip_is_dropped() -> None:
    rec = SgkRecorder(min_duration_s=0.5)
    rec.start()
    _FakeStream.instances[-1].feed(np.ones(1000, dtype="float32"))
    rec._t0 = time.monotonic() - 0.05  # 50 ms - below threshold
    assert rec.stop() is None


def test_empty_capture_returns_none() -> None:
    rec = SgkRecorder(min_duration_s=0.0)
    rec.start()
    rec._t0 = time.monotonic() - 1.0
    assert rec.stop() is None


def test_stop_without_start_is_none() -> None:
    assert SgkRecorder().stop() is None


def test_double_start_keeps_single_stream() -> None:
    rec = SgkRecorder()
    assert rec.start() is True
    assert rec.start() is True
    assert len(_FakeStream.instances) == 1


def test_mic_open_failure_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(**kwargs):
        raise OSError("no such device")

    sys.modules["sounddevice"].InputStream = _boom  # type: ignore[attr-defined]
    rec = SgkRecorder()
    assert rec.start() is False
    assert rec.is_recording is False
