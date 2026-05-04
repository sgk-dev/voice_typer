#!/usr/bin/env bash
set -euo pipefail

VENV="/home/sgk/.venvs/transcribe"
PROJECT="/home/sgk/voice_typer"

echo "[1/5] Adding user to input group..."
sudo usermod -aG input "$USER"

echo "[2/5] Installing Python dependencies..."
"$VENV/bin/pip" install evdev sounddevice pystray Pillow dbus-python

echo "[3/5] Installing udev rule..."
sudo cp "$PROJECT/setup/99-voice-typer.rules" /etc/udev/rules.d/
sudo udevadm control --reload-rules

echo "[4/5] Installing systemd user service..."
mkdir -p ~/.config/systemd/user
cp "$PROJECT/systemd/voice-typer.service" ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable voice-typer

echo "[5/5] Installing CLI symlink..."
mkdir -p ~/.local/bin
ln -sf "$VENV/bin/python $PROJECT/cli/voice_typer_cli.py" ~/.local/bin/voice-typer

echo ""
echo "Done. Log out and back in for input group to take effect."
echo "Then: systemctl --user start voice-typer"
