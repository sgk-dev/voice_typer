"""Bridges the evdev listener (background thread) onto the asyncio loop.

The evdev backend calls back with ``(name, phase)`` from its own thread; this
manager hops each event onto the loop and invokes the right handler:

* ``ptt`` / ``ptt_terminal`` press & release -> the async pipeline coroutines
  (``terminal`` is derived from which hotkey fired);
* ``toggle`` tap -> the sync enable/disable handler, debounced.

While paused, PTT events are dropped; ``toggle`` still works.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Coroutine

from sgk_voice_typer.input.evdev_backend import SgkEvdevHotkeyListener
from sgk_voice_typer.utils.logger import sgk_get_logger

_logger = sgk_get_logger(__name__)

_MIN_TOGGLE_INTERVAL = 0.4  # seconds - debounce the enable/disable key

_PTT_NAMES = {"ptt": False, "ptt_terminal": True}
_HOLD_NAMES = {"ptt", "ptt_terminal"}

PttHandler = Callable[[bool], Coroutine[Any, Any, None]]
ToggleHandler = Callable[[], None]


class SgkHotkeyManager:
    def __init__(self, hotkeys: dict[str, str]) -> None:
        self._hotkeys = dict(hotkeys)
        self._backend = SgkEvdevHotkeyListener(self._hotkeys, hold_hotkeys=_HOLD_NAMES)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._on_press: PttHandler | None = None
        self._on_release: PttHandler | None = None
        self._on_toggle: ToggleHandler | None = None
        self._last_toggle = 0.0
        self._paused = False

    # -- wiring -----------------------------------------------------

    def sgk_set_handlers(
        self,
        on_press: PttHandler,
        on_release: PttHandler,
        on_toggle: ToggleHandler,
    ) -> None:
        self._on_press = on_press
        self._on_release = on_release
        self._on_toggle = on_toggle

    def sgk_set_paused(self, paused: bool) -> None:
        self._paused = paused

    def sgk_is_paused(self) -> bool:
        return self._paused

    def sgk_start(self, loop: asyncio.AbstractEventLoop) -> bool:
        self._loop = loop
        if not self._backend.sgk_is_available():
            _logger.error(
                "sgk_hotkey_backend_unavailable",
                extra={"hint": "add your user to the 'input' group and re-login"},
            )
            return False
        self._backend.sgk_start(self._sgk_on_hotkey_raw)
        _logger.info("sgk_hotkey_manager_started", extra={"hotkeys": self._hotkeys})
        return True

    def sgk_stop(self) -> None:
        self._backend.sgk_stop()

    # -- evdev-thread callback ------------------------------------

    def _sgk_on_hotkey_raw(self, name: str, phase: str) -> None:
        loop = self._loop
        if loop is None:
            return

        if name in _PTT_NAMES:
            if self._paused:
                return
            terminal = _PTT_NAMES[name]
            handler = self._on_press if phase == "press" else (
                self._on_release if phase == "release" else None
            )
            if handler is not None:
                loop.call_soon_threadsafe(self._sgk_spawn, handler, terminal)
            return

        if name == "toggle" and phase == "tap" and self._on_toggle is not None:
            now = time.monotonic()
            if now - self._last_toggle < _MIN_TOGGLE_INTERVAL:
                return
            self._last_toggle = now
            loop.call_soon_threadsafe(self._on_toggle)

    def _sgk_spawn(self, handler: PttHandler, terminal: bool) -> None:
        assert self._loop is not None
        self._loop.create_task(handler(terminal))
