"""Unit tests for hotkey parsing and the push-to-talk dispatch state machine."""

from __future__ import annotations

from sgk_voice_typer.input.evdev_backend import (
    _KEY_DOWN,
    _KEY_HOLD,
    _KEY_UP,
    SgkEvdevHotkeyListener,
    _sgk_parse_hotkey,
    _sgk_pick_hotkey,
    _SgkHotkeySpec,
)

# Fake keycodes (values are arbitrary, only identity matters in the state machine).
CTRL, SHIFT = 29, 42
F9, PAUSE = 67, 119

MOD_MAP = {CTRL: "ctrl", SHIFT: "shift"}
TRIGGERS = {F9: "f9", PAUSE: "pause"}


class TestParseHotkey:
    def test_single_key(self) -> None:
        assert _sgk_parse_hotkey("f9") == (frozenset(), "f9")

    def test_shift_f9(self) -> None:
        assert _sgk_parse_hotkey("shift+f9") == (frozenset({"shift"}), "f9")

    def test_ctrl_pause(self) -> None:
        assert _sgk_parse_hotkey("ctrl+pause") == (frozenset({"ctrl"}), "pause")

    def test_gnome_style(self) -> None:
        assert _sgk_parse_hotkey("<Primary>Pause") == (frozenset({"ctrl"}), "pause")


def _specs() -> list[_SgkHotkeySpec]:
    return [
        _SgkHotkeySpec("ptt", frozenset(), "f9", hold=True),
        _SgkHotkeySpec("ptt_terminal", frozenset({"shift"}), "f9", hold=True),
        _SgkHotkeySpec("toggle", frozenset({"ctrl"}), "pause", hold=False),
    ]


class TestPickHotkey:
    def test_bare_f9_is_ptt(self) -> None:
        assert _sgk_pick_hotkey(set(), "f9", _specs()) == "ptt"

    def test_shift_f9_is_more_specific(self) -> None:
        assert _sgk_pick_hotkey({"shift"}, "f9", _specs()) == "ptt_terminal"

    def test_ctrl_pause_is_toggle(self) -> None:
        assert _sgk_pick_hotkey({"ctrl"}, "pause", _specs()) == "toggle"

    def test_pause_without_ctrl_no_match(self) -> None:
        assert _sgk_pick_hotkey(set(), "pause", _specs()) is None


class _Listener(SgkEvdevHotkeyListener):
    """Listener wired to a fake callback, for driving _sgk_dispatch directly."""

    def __init__(self) -> None:
        super().__init__(
            {"ptt": "f9", "ptt_terminal": "shift+f9", "toggle": "ctrl+pause"},
            hold_hotkeys={"ptt", "ptt_terminal"},
        )
        self.calls: list[tuple[str, str]] = []
        self._callback = lambda name, phase: self.calls.append((name, phase))


def _feed(lst: _Listener, mods: set[str], hold: dict[int, str], keycode: int, state: int) -> None:
    lst._sgk_dispatch(keycode, state, mods, hold, MOD_MAP, TRIGGERS)


class TestDispatchHoldMode:
    def test_press_then_release(self) -> None:
        lst, mods, hold = _Listener(), set(), {}
        _feed(lst, mods, hold, F9, _KEY_DOWN)
        _feed(lst, mods, hold, F9, _KEY_UP)
        assert lst.calls == [("ptt", "press"), ("ptt", "release")]
        assert hold == {}

    def test_autorepeat_does_not_refire_press(self) -> None:
        lst, mods, hold = _Listener(), set(), {}
        _feed(lst, mods, hold, F9, _KEY_DOWN)
        for _ in range(5):
            _feed(lst, mods, hold, F9, _KEY_HOLD)
        _feed(lst, mods, hold, F9, _KEY_UP)
        assert lst.calls == [("ptt", "press"), ("ptt", "release")]

    def test_stray_second_down_is_ignored(self) -> None:
        lst, mods, hold = _Listener(), set(), {}
        _feed(lst, mods, hold, F9, _KEY_DOWN)
        _feed(lst, mods, hold, F9, _KEY_DOWN)  # dropped-event glitch
        _feed(lst, mods, hold, F9, _KEY_UP)
        assert lst.calls == [("ptt", "press"), ("ptt", "release")]

    def test_shift_held_selects_terminal_variant(self) -> None:
        lst, mods, hold = _Listener(), set(), {}
        _feed(lst, mods, hold, SHIFT, _KEY_DOWN)
        _feed(lst, mods, hold, F9, _KEY_DOWN)
        _feed(lst, mods, hold, F9, _KEY_UP)
        _feed(lst, mods, hold, SHIFT, _KEY_UP)
        assert lst.calls == [("ptt_terminal", "press"), ("ptt_terminal", "release")]

    def test_shift_released_before_f9_still_ends_recording(self) -> None:
        lst, mods, hold = _Listener(), set(), {}
        _feed(lst, mods, hold, SHIFT, _KEY_DOWN)
        _feed(lst, mods, hold, F9, _KEY_DOWN)
        _feed(lst, mods, hold, SHIFT, _KEY_UP)   # let go of Shift early
        _feed(lst, mods, hold, F9, _KEY_UP)
        assert lst.calls == [("ptt_terminal", "press"), ("ptt_terminal", "release")]

    def test_release_without_prior_press_is_silent(self) -> None:
        lst, mods, hold = _Listener(), set(), {}
        _feed(lst, mods, hold, F9, _KEY_UP)  # daemon started with key already held
        assert lst.calls == []


class TestDispatchTapMode:
    def test_toggle_fires_once_on_down(self) -> None:
        lst, mods, hold = _Listener(), set(), {}
        _feed(lst, mods, hold, CTRL, _KEY_DOWN)
        _feed(lst, mods, hold, PAUSE, _KEY_DOWN)
        _feed(lst, mods, hold, PAUSE, _KEY_HOLD)
        _feed(lst, mods, hold, PAUSE, _KEY_UP)
        _feed(lst, mods, hold, CTRL, _KEY_UP)
        assert lst.calls == [("toggle", "tap")]

    def test_pause_without_ctrl_does_nothing(self) -> None:
        lst, mods, hold = _Listener(), set(), {}
        _feed(lst, mods, hold, PAUSE, _KEY_DOWN)
        assert lst.calls == []
