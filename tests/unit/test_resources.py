"""Unit tests for generated packaging text."""

from __future__ import annotations

from sgk_voice_typer.utils.resources import sgk_desktop_entry, sgk_systemd_unit


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


def test_systemd_unit_basics() -> None:
    text = sgk_systemd_unit("/home/u/.local/bin/sgk-voice-typer")
    assert "[Unit]" in text and "[Service]" in text and "[Install]" in text
    assert "ExecStart=/home/u/.local/bin/sgk-voice-typer" in text
    assert "WantedBy=graphical-session.target" in text
    # CUDA libs are resolved at runtime by cuda_env, never hardcoded in the unit
    assert "LD_LIBRARY_PATH" not in text
