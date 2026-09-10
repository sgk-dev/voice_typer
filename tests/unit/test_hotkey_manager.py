"""Unit tests for SgkHotkeyManager event routing (no real evdev)."""

from __future__ import annotations

import asyncio

import pytest

from sgk_voice_typer.core.hotkey_manager import SgkHotkeyManager

HOTKEYS = {"ptt": "f9", "ptt_terminal": "shift+f9", "toggle": "ctrl+pause"}


def _manager():
    m = SgkHotkeyManager(HOTKEYS)
    m._loop = asyncio.get_event_loop()
    presses: list[bool] = []
    releases: list[bool] = []
    toggles: list[int] = []

    async def on_press(terminal: bool) -> None:
        presses.append(terminal)

    async def on_release(terminal: bool) -> None:
        releases.append(terminal)

    def on_toggle() -> None:
        toggles.append(1)

    m.sgk_set_handlers(on_press, on_release, on_toggle)
    return m, presses, releases, toggles


async def _flush() -> None:
    for _ in range(3):
        await asyncio.sleep(0)


async def test_ptt_press_release() -> None:
    m, presses, releases, _ = _manager()
    m._sgk_on_hotkey_raw("ptt", "press")
    m._sgk_on_hotkey_raw("ptt", "release")
    await _flush()
    assert presses == [False]
    assert releases == [False]


async def test_ptt_terminal_carries_true() -> None:
    m, presses, _, _ = _manager()
    m._sgk_on_hotkey_raw("ptt_terminal", "press")
    await _flush()
    assert presses == [True]


async def test_toggle_tap_fires() -> None:
    m, _, _, toggles = _manager()
    m._sgk_on_hotkey_raw("toggle", "tap")
    await _flush()
    assert toggles == [1]


async def test_toggle_is_debounced() -> None:
    m, _, _, toggles = _manager()
    m._sgk_on_hotkey_raw("toggle", "tap")
    m._sgk_on_hotkey_raw("toggle", "tap")  # immediately again - debounced
    await _flush()
    assert toggles == [1]


async def test_toggle_again_after_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    m, _, _, toggles = _manager()
    m._sgk_on_hotkey_raw("toggle", "tap")
    await _flush()
    m._last_toggle -= 10.0  # pretend enough time passed
    m._sgk_on_hotkey_raw("toggle", "tap")
    await _flush()
    assert toggles == [1, 1]


async def test_paused_drops_ptt_but_not_toggle() -> None:
    m, presses, releases, toggles = _manager()
    m.sgk_set_paused(True)
    m._sgk_on_hotkey_raw("ptt", "press")
    m._sgk_on_hotkey_raw("ptt", "release")
    m._sgk_on_hotkey_raw("toggle", "tap")
    await _flush()
    assert presses == [] and releases == []
    assert toggles == [1]
