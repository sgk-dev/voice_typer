<div align="center">

<img src="https://raw.githubusercontent.com/sgk-dev/voice_typer/master/sgk_voice_typer/gui/icon.png" alt="VoiceTyper logo" width="128">

# VoiceTyper

**Push-to-talk voice input for Linux — hold a key, speak, release, the text appears where your cursor is.**

Hold **F9**, say a sentence, let go: it is transcribed on your GPU with
faster-whisper and pasted into whatever window has focus — editor, browser,
chat, terminal.

![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![Platform](https://img.shields.io/badge/platform-GNOME%20Wayland-e95420)
![License](https://img.shields.io/badge/license-GPLv3-blue)

</div>

---

## Why

Dictation tools for Linux are either cloud-bound or fiddly. VoiceTyper runs
entirely on your machine: the model is loaded once into VRAM and stays there,
so a five-second phrase comes back in well under a second on an RTX 3060.

It is **push-to-talk on purpose**: it records only while you hold the key and
never listens otherwise.

## How it works

1. The push-to-talk key is caught with evdev (needs the `input` group).
2. Audio is captured while the key is held (`sounddevice`).
3. On release the clip goes to faster-whisper (`large-v3-turbo`, CUDA).
4. The result is placed on the clipboard and pasted with a synthetic **Ctrl+V**
   (**Ctrl+Shift+V** when you use the terminal hotkey) through a `uinput`
   virtual keyboard — `wtype` is unsupported by Mutter, so this is the reliable
   path.
5. Your clipboard is saved before and restored after.

## Hotkeys

| Action | Hotkey |
|--------|--------|
| Record and type | hold `F9` |
| Record and type (terminal — pastes with `Ctrl+Shift+V`) | hold `Shift+F9` |
| Enable / disable the daemon | `Ctrl+Pause` |

All configurable in Settings or `~/.config/sgk-voice-typer/config.json`.

## Tray and settings

The tray icon shows the state: idle, recording, transcribing, or paused.
Right-click for the menu:

- **Enabled / Paused**
- **Settings…** — microphone, model, recognition language, hotkeys, UI
  language, launch on login, behavior timings
- **About**
- **Quit**

## Install (GNOME Wayland / Ubuntu)

```bash
bash packaging/install.sh
# log out and back in once (for the 'input' group), then:
systemctl --user start sgk-voice-typer
```

Requires: an NVIDIA GPU with CUDA, `wl-clipboard`, `python3-pyqt6`,
`python3-evdev`, and membership in the `input` group (for the evdev listener and
the `uinput` virtual keyboard).

On the first run the model (`large-v3-turbo`, ~1.6 GB) is downloaded to the
Hugging Face cache.

## Run in the foreground

```bash
python -m sgk_voice_typer --log-level DEBUG      # with tray
python -m sgk_voice_typer --no-gui               # headless
```

## Configuration

`~/.config/sgk-voice-typer/config.json` (created on first run) holds the
hotkeys, the model and device, the audio device, and the clipboard timings.
Model and hotkey changes take effect after a restart; microphone and UI
language changes apply immediately.

## Notes and limitations

- **GNOME Wayland only.** X11 / KDE / wlroots are out of scope for this release.
- **Non-text clipboard** (image / files) is lost when the clipboard is restored;
  only text is kept.
- **Terminals** need a separate hotkey (`Shift+F9`) because focused-window
  detection is not available on GNOME Wayland.
- Speech recognition is not streaming: a long phrase means a few seconds of
  silence before the text lands.

## License

VoiceTyper is free software under the **GNU General Public License v3.0 or
later** (see [`LICENSE`](LICENSE)). Distributed in the hope that it will be
useful, but WITHOUT ANY WARRANTY.

Copyright (c) 2026 SGK (sidash.seo@gmail.com)

The **VoiceTyper** name and logo are not covered by the GPL and remain the
property of SGK; forks must use a different name and their own artwork.

---

<div align="center">

Developed by SGK with ❤️

</div>
