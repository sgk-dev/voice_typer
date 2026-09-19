"""Unit tests for generated packaging text."""

from __future__ import annotations

from sgk_voice_typer.utils.resources import sgk_desktop_entry


def test_desktop_entry_basics() -> None:
    text = sgk_desktop_entry("/usr/bin/sgk-voice-typer")
    assert text.startswith("[Desktop Entry]")
    assert "Name=VoiceTyper" in text
    assert "Exec=/usr/bin/sgk-voice-typer" in text
    assert "NoDisplay=false" in text
    assert "X-GNOME-Autostart-enabled" not in text


def test_desktop_entry_autostart_flag() -> None:
    text = sgk_desktop_entry("cmd", autostart=True)
    assert "X-GNOME-Autostart-enabled=true" in text
