"""Abstract base class for the push-to-talk hotkey listener backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable

# on_hotkey(name, phase) where phase is "press" | "release" | "tap".
# Hold hotkeys emit "press" then "release"; tap hotkeys emit a single "tap".
SgkHotkeyCallback = Callable[[str, str], None]


class SgkInputBackend(ABC):
    """Backend-agnostic interface for global hotkey interception."""

    @abstractmethod
    def sgk_start(self, on_hotkey: SgkHotkeyCallback) -> None:
        """Start listening. Calls on_hotkey(name, phase) from a background thread."""

    @abstractmethod
    def sgk_stop(self) -> None:
        """Stop listening and release all resources."""

    @abstractmethod
    def sgk_is_available(self) -> bool:
        """Return True if this backend can operate in the current environment."""
