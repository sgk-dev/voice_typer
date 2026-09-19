"""Generated packaging text (the `.desktop` entry, also used for XDG autostart).

Built in code so ``--install`` works from a pip or pipx install, where the
repo's ``packaging/`` directory is not present. Launch-on-login is the XDG
autostart entry only: it inherits the full session environment (DISPLAY,
WAYLAND_DISPLAY, D-Bus) and the settings dialog can toggle it.
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



def sgk_desktop_entry(exec_cmd: str, autostart: bool = False) -> str:
    text = _DESKTOP.format(exec_cmd=exec_cmd)
    if autostart:
        text += _AUTOSTART_EXTRA
    return text
