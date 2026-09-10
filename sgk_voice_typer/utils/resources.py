"""Generated packaging text (`.desktop` entry, systemd user unit).

Built in code so ``--install-desktop`` / ``--install-service`` work from a pip
or pipx install, where the repo's ``packaging/`` directory is not present.
"""

from __future__ import annotations

_DESKTOP = """\
[Desktop Entry]
Type=Application
Name=VoiceTyper
GenericName=Voice Input
Comment=Push-to-talk speech-to-text that types into the focused window
Exec={exec_cmd}
Icon=voice-typer
Categories=Utility;AudioVideo;Accessibility;
Keywords=voice;speech;dictation;transcribe;whisper;microphone;
Terminal=false
NoDisplay=false
StartupNotify=false
"""

_AUTOSTART_EXTRA = "X-GNOME-Autostart-enabled=true\nX-GNOME-Autostart-Delay=3\n"

_SYSTEMD_UNIT = """\
[Unit]
Description=VoiceTyper - push-to-talk speech daemon
Documentation=https://github.com/sgk-dev/voice_typer
After=graphical-session.target
PartOf=graphical-session.target
StartLimitIntervalSec=60
StartLimitBurst=5

[Service]
Type=simple
ExecStart={exec_cmd}
Restart=on-failure
RestartSec=3s
Environment=PYTHONUNBUFFERED=1
PassEnvironment=WAYLAND_DISPLAY XDG_CURRENT_DESKTOP XDG_SESSION_TYPE DBUS_SESSION_BUS_ADDRESS PATH

[Install]
WantedBy=graphical-session.target
"""


def sgk_desktop_entry(exec_cmd: str, autostart: bool = False) -> str:
    text = _DESKTOP.format(exec_cmd=exec_cmd)
    if autostart:
        text += _AUTOSTART_EXTRA
    return text


def sgk_systemd_unit(exec_cmd: str) -> str:
    return _SYSTEMD_UNIT.format(exec_cmd=exec_cmd)
