"""Wayland/evdev global hotkey listener with a push-to-talk hold mode.

Reads keyboard events straight from ``/dev/input/event*`` (needs the ``input``
group). Two kinds of hotkey:

* **hold** (``ptt``, ``ptt_terminal``) - emits ``press`` when the trigger key
  goes down with its modifiers satisfied, and ``release`` when that same
  trigger key comes back up. The modifier state is *not* re-checked on release:
  letting go of Shift before F9 must still end the recording.
* **tap** (``toggle``) - emits a single ``tap`` on key-down.

Three things the dispatch has to get right:

1. keyboard auto-repeat (``key_hold`` events, value 2) is ignored for trigger
   keys - otherwise holding F9 would fire a stream of ``press`` events;
2. a ``release`` is only emitted if a matching ``press`` was seen (tracked per
   trigger keycode in ``active_hold``);
3. when two hotkeys share a trigger key (F9 vs Shift+F9) the more specific one
   - the one with more modifiers - wins, and it is locked in at press time.
"""

from __future__ import annotations

import glob
import os
import select
import threading
from dataclasses import dataclass
from typing import Any

from sgk_voice_typer.input.base import SgkHotkeyCallback, SgkInputBackend
from sgk_voice_typer.utils.logger import sgk_get_logger

_logger = sgk_get_logger(__name__)

# evdev KeyEvent.keystate values.
_KEY_UP, _KEY_DOWN, _KEY_HOLD = 0, 1, 2

_SGK_MODIFIER_KEY_NAMES: dict[str, list[str]] = {
    "ctrl":  ["KEY_LEFTCTRL", "KEY_RIGHTCTRL"],
    "shift": ["KEY_LEFTSHIFT", "KEY_RIGHTSHIFT"],
    "alt":   ["KEY_LEFTALT", "KEY_RIGHTALT"],
    "super": ["KEY_LEFTMETA", "KEY_RIGHTMETA"],
}

_SGK_MODIFIER_ALIASES: dict[str, str] = {
    "control": "ctrl",
    "primary": "ctrl",
    "meta": "super",
    "logo": "super",
    "win": "super",
}


@dataclass(frozen=True)
class _SgkHotkeySpec:
    name: str
    modifiers: frozenset[str]
    key: str
    hold: bool


def _sgk_parse_hotkey(hotkey_str: str) -> tuple[frozenset[str], str]:
    """Parse ``shift+f9`` or GNOME-style ``<Shift>F9`` into (modifiers, key)."""
    s = hotkey_str.replace("<", "+").replace(">", "+")
    parts = [p.strip().lower() for p in s.split("+") if p.strip()]
    if not parts:
        return frozenset(), ""
    key = parts[-1]
    mods = {_SGK_MODIFIER_ALIASES.get(p, p) for p in parts[:-1]}
    return frozenset(mods), key


def _sgk_pick_hotkey(
    pressed_mods: set[str],
    trigger_key: str,
    specs: list[_SgkHotkeySpec],
) -> str | None:
    """Name of the most specific hotkey satisfied by the current modifier state."""
    best: _SgkHotkeySpec | None = None
    for spec in specs:
        if spec.key != trigger_key:
            continue
        if not spec.modifiers.issubset(pressed_mods):
            continue
        if best is None or len(spec.modifiers) > len(best.modifiers):
            best = spec
    return best.name if best else None


class SgkEvdevHotkeyListener(SgkInputBackend):
    """Global push-to-talk hotkey listener using Linux evdev."""

    def __init__(
        self,
        hotkeys: dict[str, str],
        hold_hotkeys: set[str] | None = None,
    ) -> None:
        hold_hotkeys = hold_hotkeys or set()
        self._hotkeys = dict(hotkeys)
        self._specs: list[_SgkHotkeySpec] = []
        for name, combo in self._hotkeys.items():
            mods, key = _sgk_parse_hotkey(combo)
            if key:
                self._specs.append(
                    _SgkHotkeySpec(name, mods, key, hold=name in hold_hotkeys)
                )
        self._by_name = {s.name: s for s in self._specs}
        self._callback: SgkHotkeyCallback | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._stop_pipe: tuple[int, int] | None = None

    # -- SgkInputBackend ------------------------------------------------

    def sgk_is_available(self) -> bool:
        try:
            import evdev  # noqa: F401
        except ImportError:
            return False
        try:
            kbds = self._sgk_find_keyboards()
        except PermissionError:
            _logger.warning(
                "sgk_evdev_no_permission",
                extra={"hint": "sudo usermod -aG input $USER, then re-login"},
            )
            return False
        for dev in kbds:
            try:
                dev.close()
            except Exception:
                pass
        return len(kbds) > 0

    def sgk_start(self, on_hotkey: SgkHotkeyCallback) -> None:
        self._callback = on_hotkey
        self._running = True
        self._stop_pipe = os.pipe()
        self._thread = threading.Thread(
            target=self._sgk_run_loop, name="sgk-evdev", daemon=True
        )
        self._thread.start()
        _logger.info("sgk_evdev_listener_started", extra={"hotkeys": self._hotkeys})

    def sgk_stop(self) -> None:
        self._running = False
        if self._stop_pipe:
            try:
                os.write(self._stop_pipe[1], b"\x00")
            except OSError:
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        if self._stop_pipe:
            for fd in self._stop_pipe:
                try:
                    os.close(fd)
                except OSError:
                    pass
            self._stop_pipe = None
        _logger.info("sgk_evdev_listener_stopped")

    # -- device discovery --------------------------------------------

    def _sgk_find_keyboards(self) -> list:
        import evdev

        keyboards = []
        for path in sorted(glob.glob("/dev/input/event*")):
            try:
                dev = evdev.InputDevice(path)
                caps = dev.capabilities()
                if (
                    evdev.ecodes.EV_KEY in caps
                    and evdev.ecodes.KEY_A in caps[evdev.ecodes.EV_KEY]
                ):
                    keyboards.append(dev)
                else:
                    dev.close()
            except (PermissionError, OSError):
                continue
            except Exception as exc:
                _logger.debug(
                    "sgk_evdev_device_skip", extra={"path": path, "error": str(exc)}
                )
        return keyboards

    def _sgk_build_code_maps(self, evdev):
        """keycode -> modifier-name, and trigger keycode -> trigger-name."""
        mod_code_to_name: dict[int, str] = {}
        for mod_name, key_names in _SGK_MODIFIER_KEY_NAMES.items():
            for kn in key_names:
                code = getattr(evdev.ecodes, kn, None)
                if code is not None:
                    mod_code_to_name[code] = mod_name

        trigger_codes: dict[int, str] = {}
        for spec in self._specs:
            code = getattr(evdev.ecodes, f"KEY_{spec.key.upper()}", None)
            if code is None:
                _logger.error("sgk_evdev_unknown_trigger_key", extra={"key": spec.key})
                continue
            trigger_codes[code] = spec.key
        return mod_code_to_name, trigger_codes

    # -- event loop -------------------------------------------------

    def _sgk_run_loop(self) -> None:
        keyboards = []
        try:
            import evdev

            keyboards = self._sgk_find_keyboards()
            if not keyboards:
                _logger.error("sgk_evdev_no_keyboards")
                return

            mod_code_to_name, trigger_codes = self._sgk_build_code_maps(evdev)
            if not trigger_codes:
                _logger.error("sgk_evdev_no_valid_hotkeys")
                return

            pressed_mods: set[str] = set()
            active_hold: dict[int, str] = {}
            stop_r = self._stop_pipe[0] if self._stop_pipe else None
            fds: dict[int, Any] = {dev.fd: dev for dev in keyboards}
            if stop_r is not None:
                fds[stop_r] = None

            while self._running:
                try:
                    readable, _, _ = select.select(list(fds.keys()), [], [], 1.0)
                except (ValueError, OSError):
                    break

                for fd in readable:
                    if fd == stop_r:
                        return
                    dev = fds.get(fd)
                    if dev is None:
                        continue
                    try:
                        for event in dev.read():
                            if event.type != evdev.ecodes.EV_KEY:
                                continue
                            try:
                                ke = evdev.categorize(event)
                                self._sgk_dispatch(
                                    ke.scancode, ke.keystate,  # type: ignore[union-attr]
                                    pressed_mods, active_hold,
                                    mod_code_to_name, trigger_codes,
                                )
                            except Exception as exc:
                                _logger.error(
                                    "sgk_evdev_event_error", extra={"error": str(exc)}
                                )
                    except (OSError, BlockingIOError):
                        fds.pop(fd, None)
        except Exception as exc:
            _logger.error("sgk_evdev_loop_error", extra={"error": str(exc)})
        finally:
            for dev in keyboards:
                try:
                    dev.close()  # type: ignore[union-attr]
                except Exception:
                    pass

    def _sgk_dispatch(
        self,
        keycode: int,
        state: int,
        pressed_mods: set[str],
        active_hold: dict[int, str],
        mod_code_to_name: dict[int, str],
        trigger_codes: dict[int, str],
    ) -> None:
        """Pure state machine: raw (keycode, state) -> hotkey callbacks.

        Kept free of evdev objects so it can be unit-tested with plain ints.
        """
        if keycode in mod_code_to_name:
            mod = mod_code_to_name[keycode]
            if state == _KEY_DOWN:
                pressed_mods.add(mod)
            elif state == _KEY_UP:
                pressed_mods.discard(mod)
            return

        if keycode not in trigger_codes:
            return

        if state == _KEY_HOLD:
            return  # auto-repeat - never a new press

        if state == _KEY_DOWN:
            if keycode in active_hold:
                return  # already held, stray repeated down
            name = _sgk_pick_hotkey(set(pressed_mods), trigger_codes[keycode], self._specs)
            if name is None:
                return
            if self._by_name[name].hold:
                active_hold[keycode] = name
                self._sgk_emit(name, "press")
            else:
                self._sgk_emit(name, "tap")
            return

        if state == _KEY_UP:
            name = active_hold.pop(keycode, None)
            if name is not None:
                self._sgk_emit(name, "release")

    def _sgk_emit(self, name: str, phase: str) -> None:
        _logger.debug("sgk_hotkey", extra={"hotkey": name, "phase": phase})
        if self._callback:
            self._callback(name, phase)
