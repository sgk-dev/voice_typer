from __future__ import annotations

import logging
import subprocess
import time

_logger = logging.getLogger(__name__)

_TERMINAL_APPS = {
    "gnome-terminal", "gnome-terminal-server",
    "alacritty", "kitty", "tilix", "xterm",
    "bash", "zsh", "tmux", "konsole",
}


def _get_active_wm_class() -> str:
    """Return lowercase WM_CLASS of the focused window, or '' on failure."""
    try:
        win_id = subprocess.check_output(
            ["xdotool", "getactivewindow"],
            stderr=subprocess.DEVNULL,
            timeout=1,
        ).decode().strip()
        raw = subprocess.check_output(
            ["xprop", "-id", win_id, "WM_CLASS"],
            stderr=subprocess.DEVNULL,
            timeout=1,
        ).decode()
        # WM_CLASS(STRING) = "code", "Code"
        parts = [p.strip().strip('"') for p in raw.split("=", 1)[-1].split(",")]
        return parts[0].lower() if parts else ""
    except Exception as exc:
        _logger.debug("WM_CLASS detection failed: %s", exc)
        return ""


def _is_terminal(wm_class: str) -> bool:
    return wm_class in _TERMINAL_APPS


def inject(text: str, terminal_apps: list[str] | None = None, sleep_after: float = 0.05) -> None:
    """Insert text at cursor using clipboard swap + wtype paste shortcut."""
    if not text:
        return

    apps = set(terminal_apps) if terminal_apps else _TERMINAL_APPS

    # Save current clipboard
    try:
        backup = subprocess.check_output(
            ["wl-paste", "--no-newline"],
            stderr=subprocess.DEVNULL,
            timeout=2,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        backup = None

    try:
        # Detect window type FIRST (closer to when user released PTT key)
        wm_class = _get_active_wm_class()
        is_term = wm_class in apps

        # Put recognized text into clipboard
        subprocess.run(["wl-copy", text], check=True, timeout=2)

        if is_term:
            _logger.debug("Terminal detected (%s) — using Ctrl+Shift+V", wm_class)
            subprocess.run(
                ["wtype", "-M", "ctrl", "-M", "shift", "-k", "v", "-m", "shift", "-m", "ctrl"],
                check=True, timeout=2,
            )
        else:
            _logger.debug("App detected (%s) — using Ctrl+V", wm_class)
            subprocess.run(
                ["wtype", "-M", "ctrl", "-k", "v", "-m", "ctrl"],
                check=True, timeout=2,
            )

        _logger.info("[INJECT] %r → %s", text[:60], wm_class or "unknown")
        time.sleep(sleep_after)

    finally:
        # Restore original clipboard
        if backup is not None:
            subprocess.run(["wl-copy", "--"], input=backup, timeout=2)
        else:
            subprocess.run(["wl-copy", "--clear"], timeout=2)
