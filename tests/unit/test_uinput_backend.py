"""Unit tests for SgkUinputInjector key/combo emission.

A fake UInput records every (type, code, value) write so we can assert the exact
press/release ordering without touching /dev/uinput.
"""

from __future__ import annotations

import pytest
from evdev import ecodes

from sgk_voice_typer.input.uinput_backend import SgkUinputInjector


class _FakeUInput:
    def __init__(self) -> None:
        self.events: list = []
        self.closed = False

    def write(self, etype: int, code: int, value: int) -> None:
        self.events.append((etype, code, value))

    def syn(self) -> None:
        self.events.append(("SYN", 0, 0))

    def close(self) -> None:
        self.closed = True

    def key_events(self) -> list[tuple[int, int]]:
        return [(c, v) for (t, c, v) in self.events if t == ecodes.EV_KEY]


@pytest.fixture
def injector() -> SgkUinputInjector:
    return SgkUinputInjector(ui=_FakeUInput())


class TestPaste:
    def test_plain_paste_is_ctrl_v(self, injector: SgkUinputInjector) -> None:
        injector.sgk_paste(shift=False)
        assert injector._ui.key_events() == [
            (ecodes.KEY_LEFTCTRL, 1),
            (ecodes.KEY_V, 1),
            (ecodes.KEY_V, 0),
            (ecodes.KEY_LEFTCTRL, 0),
        ]

    def test_terminal_paste_is_ctrl_shift_v(self, injector: SgkUinputInjector) -> None:
        injector.sgk_paste(shift=True)
        assert injector._ui.key_events() == [
            (ecodes.KEY_LEFTCTRL, 1),
            (ecodes.KEY_LEFTSHIFT, 1),
            (ecodes.KEY_V, 1),
            (ecodes.KEY_V, 0),
            (ecodes.KEY_LEFTSHIFT, 0),
            (ecodes.KEY_LEFTCTRL, 0),
        ]


class TestAvailability:
    def test_unavailable_injector_is_noop(self) -> None:
        inj = SgkUinputInjector(ui=None)
        assert inj.sgk_is_available() is False
        inj.sgk_paste()          # must not raise
        inj.sgk_send_combo("ctrl+v")

    def test_available_with_fake_device(self, injector: SgkUinputInjector) -> None:
        assert injector.sgk_is_available() is True


class TestClose:
    def test_close_closes_device(self, injector: SgkUinputInjector) -> None:
        fake = injector._ui
        injector.sgk_close()
        assert fake.closed is True
        assert injector._ui is None
