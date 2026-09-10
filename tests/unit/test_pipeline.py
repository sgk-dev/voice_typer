"""Unit tests for SgkDictationPipeline."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest

from sgk_voice_typer.core.pipeline import (
    SGK_IDLE,
    SGK_PROCESSING,
    SGK_RECORDING,
    SgkDictationPipeline,
)


class _FakeRecorder:
    def __init__(self, audio) -> None:
        self._audio = audio
        self.starts = 0
        self.stops = 0

    def start(self) -> bool:
        self.starts += 1
        return True

    def stop(self):
        self.stops += 1
        return self._audio


class _FakeTranscriber:
    def __init__(self, text) -> None:
        self._text = text
        self.calls = 0

    def transcribe(self, audio):
        self.calls += 1
        return self._text


class _FakeClipboard:
    def __init__(self) -> None:
        self.events: list[str] = []

    async def sgk_save(self) -> None:
        self.events.append("save")

    async def sgk_type(self, text: str, terminal: bool = False) -> bool:
        self.events.append(f"type:{text}:{terminal}")
        return True

    async def sgk_restore(self) -> None:
        self.events.append("restore")


@pytest.fixture
def executor():
    ex = ThreadPoolExecutor(max_workers=1)
    yield ex
    ex.shutdown(wait=True)


def _make(recorder, transcriber, clipboard, executor, max_duration_s=60.0):
    loop = asyncio.get_event_loop()
    p = SgkDictationPipeline(
        recorder, transcriber, clipboard, loop, executor, max_duration_s=max_duration_s
    )
    states: list[str] = []
    p.sgk_set_state_listener(states.append)
    return p, states


AUDIO = np.zeros(16000, dtype="float32")


async def test_happy_path_order_and_states(executor) -> None:
    clip = _FakeClipboard()
    p, states = _make(_FakeRecorder(AUDIO), _FakeTranscriber("привет"), clip, executor)

    await p.sgk_on_press(terminal=False)
    await p.sgk_on_release(terminal=False)

    assert clip.events == ["save", "type:привет:False", "restore"]
    assert states == [SGK_RECORDING, SGK_PROCESSING, SGK_IDLE]


async def test_terminal_flag_flows_through(executor) -> None:
    clip = _FakeClipboard()
    p, _ = _make(_FakeRecorder(AUDIO), _FakeTranscriber("ls"), clip, executor)
    await p.sgk_on_press(terminal=True)
    await p.sgk_on_release(terminal=True)
    assert "type:ls:True" in clip.events


async def test_second_press_while_active_is_ignored(executor) -> None:
    rec = _FakeRecorder(AUDIO)
    p, _ = _make(rec, _FakeTranscriber("x"), _FakeClipboard(), executor)
    await p.sgk_on_press(terminal=False)
    await p.sgk_on_press(terminal=False)
    assert rec.starts == 1
    await p.sgk_on_release(terminal=False)


async def test_release_without_press_is_noop(executor) -> None:
    clip = _FakeClipboard()
    p, _ = _make(_FakeRecorder(AUDIO), _FakeTranscriber("x"), clip, executor)
    await p.sgk_on_release(terminal=False)
    assert clip.events == []


async def test_empty_audio_skips_injection(executor) -> None:
    clip = _FakeClipboard()
    p, _ = _make(_FakeRecorder(None), _FakeTranscriber("x"), clip, executor)
    await p.sgk_on_press(terminal=False)
    await p.sgk_on_release(terminal=False)
    assert clip.events == []


async def test_no_text_skips_injection(executor) -> None:
    clip = _FakeClipboard()
    p, _ = _make(_FakeRecorder(AUDIO), _FakeTranscriber(None), clip, executor)
    await p.sgk_on_press(terminal=False)
    await p.sgk_on_release(terminal=False)
    assert clip.events == []


async def test_duration_cap_forces_finish(executor) -> None:
    rec = _FakeRecorder(AUDIO)
    clip = _FakeClipboard()
    p, _ = _make(rec, _FakeTranscriber("long"), clip, executor, max_duration_s=0.05)

    await p.sgk_on_press(terminal=False)
    await asyncio.sleep(0.2)
    assert clip.events == ["save", "type:long:False", "restore"]

    # the real release afterwards must do nothing
    await p.sgk_on_release(terminal=False)
    assert rec.stops == 1
