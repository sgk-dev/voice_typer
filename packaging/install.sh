#!/usr/bin/env bash
# VoiceTyper installer - targets GNOME Wayland (Ubuntu) with an NVIDIA GPU.
# Usage: bash packaging/install.sh
set -euo pipefail

echo "=== VoiceTyper installer ==="

# 1. System dependencies
echo "[1/6] Installing system dependencies..."
if command -v apt-get &>/dev/null; then
    sudo apt-get update -qq
    sudo apt-get install -y \
        wl-clipboard \
        python3-pyqt6 python3-evdev python3-venv \
        libportaudio2 \
        2>/dev/null || true
fi

# 2. Virtual environment. Reuses apt-installed PyQt6 / evdev; faster-whisper and
#    the CUDA wheels (nvidia-*-cu12, ~2 GB) come from PyPI.
VENV_PATH="$HOME/.local/share/sgk-voice-typer/venv"
echo "[2/6] Setting up virtual environment in $VENV_PATH..."
mkdir -p "$(dirname "$VENV_PATH")"
python3 -m venv --system-site-packages "$VENV_PATH"
"$VENV_PATH/bin/pip" install --upgrade pip -q
"$VENV_PATH/bin/pip" install -q .

mkdir -p "$HOME/.local/bin"
cat > "$HOME/.local/bin/sgk-voice-typer" <<EOF
#!/usr/bin/env bash
exec "$VENV_PATH/bin/python3" -m sgk_voice_typer "\$@"
EOF
chmod +x "$HOME/.local/bin/sgk-voice-typer"

# 3. Input access (evdev PTT listener + uinput virtual keyboard)
echo "[3/6] Configuring input access..."
sudo cp packaging/99-sgk-voice-typer.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
sudo usermod -aG input "$USER"
echo "    NOTE: log out and back in for the 'input' group to take effect."

# 4. Icon + application menu entry + autostart + systemd user service
echo "[4/6] Installing menu entry, autostart and service..."
"$VENV_PATH/bin/python3" -m sgk_voice_typer --install-service

# 5. Import the session environment so the unit can reach Wayland / D-Bus
echo "[5/6] Importing session environment..."
systemctl --user import-environment WAYLAND_DISPLAY XDG_CURRENT_DESKTOP \
    XDG_SESSION_TYPE DISPLAY DBUS_SESSION_BUS_ADDRESS 2>/dev/null || true
systemctl --user daemon-reload
systemctl --user enable sgk-voice-typer

# 6. Done
echo "[6/6] Done."
echo ""
echo "=== Installation complete ==="
echo "Start now:     systemctl --user start sgk-voice-typer"
echo "Or launch it from the applications menu: VoiceTyper"
echo "Check status:  systemctl --user status sgk-voice-typer"
echo "View logs:     journalctl --user -u sgk-voice-typer -f"
echo ""
echo "Hotkeys:  hold F9 to type - hold Shift+F9 in a terminal - Ctrl+Pause on/off"
echo "Config:   ~/.config/sgk-voice-typer/config.json"
echo ""
echo "First run downloads the Whisper model (large-v3-turbo, ~1.6 GB)."
echo "If you were just added to the 'input' group, log out and back in first."
