"""Unit tests for display-server detection."""

from __future__ import annotations

import pytest

from sgk_voice_typer.utils.display_server import (
    sgk_detect_display_server,
    sgk_is_wayland,
)


def test_xdg_session_type_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setenv("DISPLAY", ":0")
    assert sgk_detect_display_server() == "wayland"
    assert sgk_is_wayland() is True


def test_falls_back_to_wayland_display(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XDG_SESSION_TYPE", raising=False)
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.delenv("DISPLAY", raising=False)
    assert sgk_detect_display_server() == "wayland"


def test_defaults_to_x11_when_nothing_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XDG_SESSION_TYPE", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("DISPLAY", raising=False)
    assert sgk_detect_display_server() == "x11"
