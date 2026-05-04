# voice_typer — CLAUDE.md

## What this is

Linux background daemon for push-to-talk voice input on Ubuntu/Wayland.
Transcribes speech via faster-whisper (large-v3-turbo, CUDA) and injects text
into the active window using clipboard swap + wtype.

Full spec: `~/docs/superpowers/specs/2026-05-04-voice-typer-design.md`

## Runtime

- Python venv: `~/.venvs/transcribe`
- Run wrapper: `~/.venvs/transcribe/bin/python voice_typer/main.py`
- CUDA libs path (required): set in systemd unit `LD_LIBRARY_PATH`
- systemd: `systemctl --user start/stop/status voice-typer`
- CLI: `voice-typer start/stop/status/reload/log`
- Config: `~/.config/voice_typer/config.toml`
- Log: `~/.local/share/voice_typer/voice_typer.log`
- UNIX socket: `/tmp/voice_typer.sock`

## Architecture

Single process, 3 threads:
1. `listener.py` — evdev PTT key → START/STOP into Queue
2. `recorder.py` — sounddevice capture → audio bytes into Queue
3. `inference.py` — faster-whisper → injector

Main thread: pystray tray icon + UNIX socket server (for CLI).

## Key invariants

- Model is loaded once at startup, stays in VRAM
- If `no_speech_prob > 0.5` → do NOT inject (silence/cough guard)
- Text injection: `wl-copy` → `wtype Ctrl+V` (or `Ctrl+Shift+V` for terminals)
- Terminal detection: D-Bus GNOME Shell `FocusApp` → WM_CLASS check
- Clipboard is always restored after inject (50ms delay)
- All evdev access requires user in `input` group

## Module map

| File | Responsibility |
|------|---------------|
| `main.py` | Entry point, thread orchestration, shutdown |
| `config.py` | Load/reload `config.toml`, `Config` dataclass |
| `listener.py` | evdev keyboard reader, PTT events |
| `recorder.py` | sounddevice capture, BytesIO buffer |
| `inference.py` | faster-whisper inference, calls injector |
| `injector.py` | wl-copy + wtype, D-Bus window detection |
| `tray.py` | pystray icon states: idle / recording |
| `cli/voice_typer_cli.py` | CLI commands via UNIX socket |

## Setup

```bash
# Add user to input group (one-time)
sudo usermod -aG input $USER

# Install new deps into existing venv
~/.venvs/transcribe/bin/pip install evdev sounddevice pystray Pillow dbus-python

# Install udev rule
sudo cp setup/99-voice-typer.rules /etc/udev/rules.d/
sudo udevadm control --reload

# Enable autostart
cp systemd/voice-typer.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now voice-typer
```

## Known gotchas

- `wtype` garbles Cyrillic if typed directly — always use clipboard method
- `dbus-python` may need `apt install python3-dbus` on some setups
- If clipboard restore feels slow, increase `sleep_after_paste` in config
- evdev requires `/dev/input/event*` access — check with `ls -la /dev/input/`
