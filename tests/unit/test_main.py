"""Unit tests for the __main__ install helpers and CLI parsing."""

from __future__ import annotations

from pathlib import Path

import pytest

from sgk_voice_typer import __main__ as m


def test_exec_cmd_is_nonempty_string() -> None:
    assert isinstance(m._sgk_exec_cmd(), str)
    assert m._sgk_exec_cmd()


def test_version_flag_exits_zero(capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["sgk-voice-typer", "--version"])
    with pytest.raises(SystemExit) as ei:
        m._sgk_parse_args()
    assert ei.value.code == 0
    assert "sgk-voice-typer" in capsys.readouterr().out


def test_install_service_writes_all_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    apps = tmp_path / "applications" / "voice-typer.desktop"
    icon = tmp_path / "icons" / "voice-typer.png"
    autostart = tmp_path / "autostart" / "voice-typer.desktop"
    service = tmp_path / "systemd" / "sgk-voice-typer.service"
    monkeypatch.setattr(m, "_APPS_DST", apps)
    monkeypatch.setattr(m, "_ICON_DST", icon)
    monkeypatch.setattr(m, "_AUTOSTART_DST", autostart)
    monkeypatch.setattr(m, "_SERVICE_DST", service)
    monkeypatch.setattr(m.subprocess, "run", lambda *a, **k: None)

    m._sgk_install_service()

    assert "[Desktop Entry]" in apps.read_text()
    assert "X-GNOME-Autostart-enabled=true" in autostart.read_text()
    unit = service.read_text()
    assert "ExecStart=" in unit
    assert "LD_LIBRARY_PATH" not in unit
