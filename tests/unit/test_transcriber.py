"""Unit tests for SgkTranscriber (fake faster-whisper model)."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import numpy as np
import pytest

from sgk_voice_typer.asr.transcriber import SgkTranscriber


class _FakeModel:
    def __init__(self, segments: list[str], language: str = "ru", duration: float = 2.0) -> None:
        self._segments = segments
        self._info = SimpleNamespace(language=language, duration=duration)
        self.last_kwargs: dict = {}

    def transcribe(self, audio, **kwargs):
        self.last_kwargs = kwargs
        segs = [SimpleNamespace(text=t, no_speech_prob=0.01) for t in self._segments]
        return iter(segs), self._info


def _audio(n: int = 16000) -> np.ndarray:
    return np.zeros(n, dtype="float32")


def test_joins_segments() -> None:
    t = SgkTranscriber(model=_FakeModel([" Привет", " мир "]))
    assert t.transcribe(_audio()) == "Привет мир"


def test_empty_segments_return_none() -> None:
    t = SgkTranscriber(model=_FakeModel([]))
    assert t.transcribe(_audio()) is None


def test_empty_audio_returns_none_without_calling_model() -> None:
    fm = _FakeModel(["x"])
    t = SgkTranscriber(model=fm)
    assert t.transcribe(np.zeros(0, dtype="float32")) is None
    assert fm.last_kwargs == {}


def test_auto_language_passes_none() -> None:
    fm = _FakeModel(["hi"])
    SgkTranscriber(model=fm, language="auto").transcribe(_audio())
    assert fm.last_kwargs["language"] is None


def test_explicit_language_is_forwarded() -> None:
    fm = _FakeModel(["hi"])
    SgkTranscriber(model=fm, language="ru").transcribe(_audio())
    assert fm.last_kwargs["language"] == "ru"


def test_info_log_does_not_contain_recognised_text(caplog: pytest.LogCaptureFixture) -> None:
    t = SgkTranscriber(model=_FakeModel(["secret words here"]))
    with caplog.at_level(logging.INFO, logger="sgk_voice_typer.asr.transcriber"):
        t.transcribe(_audio())
    info_records = [r for r in caplog.records if r.levelno == logging.INFO]
    assert info_records
    for r in info_records:
        assert "secret" not in r.getMessage()
        assert "secret" not in str(getattr(r, "text", ""))
        assert getattr(r, "chars", None) == len("secret words here")
