from __future__ import annotations

import logging
import threading
from typing import Callable

import evdev
from evdev import ecodes

_logger = logging.getLogger(__name__)


def _find_keyboards() -> list[evdev.InputDevice]:
    """Return all input devices that have F9 key capability."""
    devices = []
    for path in evdev.list_devices():
        try:
            dev = evdev.InputDevice(path)
            caps = dev.capabilities()
            keys = caps.get(ecodes.EV_KEY, [])
            if ecodes.KEY_F9 in keys:
                devices.append(dev)
                _logger.debug("Found keyboard: %s — %s", dev.path, dev.name)
        except Exception as exc:
            _logger.debug("Skipping %s: %s", path, exc)
    return devices


class PttListener:
    """
    Listens for a PTT key on all keyboards.
    Calls on_press() when key is pressed, on_release() when released.
    Runs in a daemon thread — stop() to shut down.
    """

    def __init__(
        self,
        key: int,
        on_press: Callable[[], None],
        on_release: Callable[[], None],
    ) -> None:
        self._key = key
        self._on_press = on_press
        self._on_release = on_release
        self._stop_event = threading.Event()
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        keyboards = _find_keyboards()
        if not keyboards:
            _logger.warning("No keyboards with PTT key found — listener inactive")
            return
        for dev in keyboards:
            t = threading.Thread(
                target=self._read_device,
                args=(dev,),
                daemon=True,
                name=f"ptt-{dev.path}",
            )
            t.start()
            self._threads.append(t)
        _logger.info("PTT listener started on %d device(s)", len(keyboards))

    def stop(self) -> None:
        self._stop_event.set()

    def _read_device(self, dev: evdev.InputDevice) -> None:
        try:
            for event in dev.read_loop():
                if self._stop_event.is_set():
                    break
                if event.type != ecodes.EV_KEY or event.code != self._key:
                    continue
                if event.value == 1:   # key down
                    self._on_press()
                elif event.value == 0: # key up
                    self._on_release()
        except OSError as exc:
            _logger.warning("Device read error (%s): %s", dev.path, exc)
