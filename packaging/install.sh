#!/usr/bin/env bash
# VoiceTyper installer - targets GNOME Wayland (Ubuntu) with an NVIDIA GPU.
# Usage: bash packaging/install.sh
set -euo pipefail

echo "=== VoiceTyper installer ==="

# 1. System dependencies
echo "[1/5] Installing system dependencies..."
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
echo "[2/5] Setting up virtual environment in $VENV_PATH..."
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
echo "[3/5] Configuring input access..."
sudo cp packaging/99-sgk-voice-typer.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
sudo usermod -aG input "$USER"
echo "    NOTE: log out and back in for the 'input' group to take effect."

# 4. Icon + application menu entry + launch on login (XDG autostart)
echo "[4/5] Installing menu entry and autostart..."
"$VENV_PATH/bin/python3" -m sgk_voice_typer --install

# 5. Done
echo "[5/5] Done."
echo ""
echo "=== Installation complete ==="
echo "Start now:     launch VoiceTyper from the applications menu (or: sgk-voice-typer &)"
echo "It starts automatically on every login; toggle that in Settings -> General."
echo "Log file:      ~/.local/share/sgk-voice-typer/voice_typer.log"
echo ""
echo "Hotkeys:  hold F9 to type - hold Shift+F9 in a terminal - Ctrl+Pause on/off"
echo "Config:   ~/.config/sgk-voice-typer/config.json"
echo ""
echo "First run downloads the Whisper model (large-v3-turbo, ~1.6 GB)."
echo "If you were just added to the 'input' group, log out and back in first."
