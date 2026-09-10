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


def _make(recorder, transcriber, clipboard, executor, max_duration_s=300.0, lock_hold_s=3.0):
    loop = asyncio.get_event_loop()
    p = SgkDictationPipeline(
        recorder, transcriber, clipboard, loop, executor,
        max_duration_s=max_duration_s, lock_hold_s=lock_hold_s,
    )
    states: list[str] = []
    locks: list[bool] = []
    p.sgk_set_state_listener(states.append)
    p.sgk_set_lock_listener(locks.append)
    p._locks = locks  # type: ignore[attr-defined]
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


async def test_hold_engages_lock_and_release_keeps_recording(executor) -> None:
    rec = _FakeRecorder(AUDIO)
    clip = _FakeClipboard()
    p, _ = _make(rec, _FakeTranscriber("hands free"), clip, executor, lock_hold_s=0.05)

    await p.sgk_on_press(terminal=False)
    await asyncio.sleep(0.15)                 # held past the lock threshold
    assert p._locks == [True]

    await p.sgk_on_release(terminal=False)    # letting go must NOT stop it
    assert rec.stops == 0
    assert clip.events == []

    await p.sgk_on_press(terminal=False)      # a fresh press is the stop
    assert rec.stops == 1
    assert clip.events == ["save", "type:hands free:False", "restore"]
    assert p._locks == [True, False]


async def test_quick_release_does_not_lock(executor) -> None:
    rec = _FakeRecorder(AUDIO)
    clip = _FakeClipboard()
    p, _ = _make(rec, _FakeTranscriber("quick"), clip, executor, lock_hold_s=0.5)

    await p.sgk_on_press(terminal=False)
    await p.sgk_on_release(terminal=False)    # released well before 0.5 s
    assert p._locks == []
    assert clip.events == ["save", "type:quick:False", "restore"]


async def test_lock_hold_zero_disables_locking(executor) -> None:
    rec = _FakeRecorder(AUDIO)
    p, _ = _make(rec, _FakeTranscriber("x"), _FakeClipboard(), executor, lock_hold_s=0.0)
    await p.sgk_on_press(terminal=False)
    await asyncio.sleep(0.1)
    assert p._locks == []
    await p.sgk_on_release(terminal=False)
    assert rec.stops == 1


async def test_duration_cap_clears_lock(executor) -> None:
    rec = _FakeRecorder(AUDIO)
    clip = _FakeClipboard()
    p, _ = _make(rec, _FakeTranscriber("capped"), clip, executor,
                 max_duration_s=0.12, lock_hold_s=0.04)
    await p.sgk_on_press(terminal=False)
    await asyncio.sleep(0.3)
    assert p._locks == [True, False]
    assert clip.events == ["save", "type:capped:False", "restore"]


class _SnapRecorder(_FakeRecorder):
    """Recorder whose snapshot() grows over time."""

    def __init__(self, audio) -> None:
        super().__init__(audio)
        self.snaps = 0

    def snapshot(self):
        self.snaps += 1
        return self._audio


async def test_live_preview_emits_partials_and_final_is_authoritative(executor) -> None:
    rec = _SnapRecorder(AUDIO)
    clip = _FakeClipboard()
    partials: list[str] = []
    loop = asyncio.get_event_loop()
    p = SgkDictationPipeline(
        rec, _FakeTranscriber("partial and final"), clip, loop, executor,
        preview_interval_s=0.05,
    )
    p.sgk_set_partial_listener(partials.append)

    await p.sgk_on_press(terminal=False)
    await asyncio.sleep(0.22)                 # a few preview ticks
    await p.sgk_on_release(terminal=False)
    await asyncio.sleep(0.05)

    assert rec.snaps >= 2
    assert partials and all(t == "partial and final" for t in partials)
    assert clip.events == ["save", "type:partial and final:False", "restore"]
    assert p._preview_task is None           # cancelled on finish


async def test_preview_disabled_by_zero_interval(executor) -> None:
    rec = _SnapRecorder(AUDIO)
    partials: list[str] = []
    loop = asyncio.get_event_loop()
    p = SgkDictationPipeline(
        rec, _FakeTranscriber("x"), _FakeClipboard(), loop, executor,
        preview_interval_s=0.0,
    )
    p.sgk_set_partial_listener(partials.append)
    await p.sgk_on_press(terminal=False)
    await asyncio.sleep(0.15)
    await p.sgk_on_release(terminal=False)
    assert partials == []
    assert rec.snaps == 0
