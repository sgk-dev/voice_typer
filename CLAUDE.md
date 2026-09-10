# CLAUDE.md - VoiceTyper

Guidance for Claude Code working in this repo. Written in English; domain terms
in Russian/Ukrainian explained in parentheses.

## WHAT

Push-to-talk voice input daemon for **Ubuntu / GNOME Wayland**. Hold `F9`, speak,
release: the clip is transcribed on the GPU with faster-whisper and pasted into
the focused window.

- **Package:** `sgk_voice_typer` · **dist:** `sgk-voice-typer` · **command:** `sgk-voice-typer`
- **Python:** 3.12, dev venv `~/.venvs/transcribe`
- **Config:** `~/.config/sgk-voice-typer/config.json` (JSON, deep-merged onto defaults)
- **Log:** `~/.local/share/sgk-voice-typer/voice_typer.log` (structured JSON, rotating)
- **License:** GPL-3.0-or-later

### Module map

| Path | Responsibility |
|------|----------------|
| `__main__.py` | argparse (`--no-gui` / `--log-level` / `--install-desktop` / `--install-service` / `--version`), single-instance guard, signal handlers |
| `app.py` | `SgkApp` - builds and wires everything, owns the asyncio loop thread + Qt main thread, shutdown |
| `asr/cuda_env.py` | find the pip CUDA libs, prepend `LD_LIBRARY_PATH`, re-exec once (guarded by `SGK_VT_CUDA_REEXEC`) |
| `asr/transcriber.py` | `SgkTranscriber` - faster-whisper wrapper, injectable model |
| `core/recorder.py` | `SgkRecorder` - `sounddevice` capture, drops sub-`min_duration` clips |
| `core/pipeline.py` | `SgkDictationPipeline` - press→record, release→transcribe→type; re-entrancy guard, duration cap |
| `core/hotkey_manager.py` | `SgkHotkeyManager` - evdev thread → asyncio loop; terminal flag by hotkey name; toggle debounce; pause gating |
| `input/base.py` | `SgkInputBackend` abstract, `(name, phase)` callback |
| `input/evdev_backend.py` | `SgkEvdevHotkeyListener` - hold-mode dispatch state machine |
| `input/uinput_backend.py` | `SgkUinputInjector` - virtual keyboard, `sgk_paste(shift=...)` |
| `input/clipboard.py` | `SgkClipboard` - save/restore + `sgk_type` via `wl-copy` (stdin) + synthetic paste |
| `gui/tray.py` | `SgkTrayIcon` - 4 states (idle/recording/processing/paused), QTimer reconcile, About |
| `gui/config_dialog.py` | `SgkConfigDialog` - General/Model/Audio/Hotkeys/Behavior tabs |
| `gui/i18n.py` | `sgk_tr` - en/ru string table, English fallback |
| `utils/config.py` | `SgkConfig` - load/save/deep-merge |
| `utils/logger.py` | structured JSON logging under the `sgk_voice_typer` hierarchy |
| `utils/single_instance.py` | flock guard |
| `utils/autostart.py` / `utils/resources.py` | XDG autostart entry, `.desktop` + systemd unit text (generated in code) |
| `utils/display_server.py` | X11 / Wayland detection |

## WHY

- **`uinput`, not `wtype`.** Mutter does not support `wtype`; the paste is a
  synthetic `Ctrl+V` (`Ctrl+Shift+V` for terminals) through a virtual keyboard.
- **Second hotkey for terminals**, not window detection. `org.gnome.Shell.Eval`
  is closed on GNOME 42+ and there is no public focused-window API on Wayland.
  `F9` → `Ctrl+V`, `Shift+F9` → `Ctrl+Shift+V`.
- **CUDA libs at runtime.** The `nvidia-*-cu12` wheels install under
  `site-packages/nvidia/*/lib`, off the linker path. `cuda_env` prepends them
  and re-execs once - never hardcode `LD_LIBRARY_PATH` in the systemd unit.
- **Privacy.** INFO logs only char count / language / durations. The recognised
  text is DEBUG-only.
- **JSON config + PyQt6.** So the settings dialog can round-trip the config.
- This project mirrors the architecture of `~/wordwrap` (same author, same
  environment); most of `utils/` and `input/uinput_backend.py` are ports.

## HOW

### Run / operate

```bash
python -m sgk_voice_typer --no-gui --log-level DEBUG   # headless
python -m sgk_voice_typer                              # with tray
bash packaging/install.sh                              # deploy (venv + service + udev)
systemctl --user {start,stop,status} sgk-voice-typer
journalctl --user -u sgk-voice-typer -f
```

Physical smoke test: hold `F9` in a text field → text appears; hold `Shift+F9`
in a terminal → text appears; the clipboard is restored; Cyrillic is intact.

### Tests / checks

```bash
~/.venvs/transcribe/bin/python -m pytest tests/unit -q   # ~112 tests
~/.venvs/transcribe/bin/ruff check sgk_voice_typer tests
~/.venvs/transcribe/bin/mypy sgk_voice_typer
```

`tests/conftest.py` runs Qt with `QT_QPA_PLATFORM=offscreen`.

### Conventions

- Prefix `sgk_` on custom classes / methods / public functions; `sgk-` on CSS
  (n/a here). Structured logging only - no `print()` except CLI user output in
  `__main__.py`.
- **Never** use a reserved `LogRecord` attribute as an `extra=` key (`name`,
  `module`, `process`, `msg`, ...). `tests/unit/test_logger.py` scans for this;
  the stdlib raises `KeyError` and kills the calling thread.
- Bump `__version__` in `sgk_voice_typer/__init__.py` and `version` in
  `pyproject.toml` together; keep `packaging/debian/changelog` in step.
- Branches: `master` and `staging` only. Work on `staging`, PR into `master`.
  Single-project repo → **no `[module]` prefix** in commit messages.

### Gotchas

- **`run_in_executor(None, ...)`** (the asyncio default executor) spawns threads
  that are never joined and segfault the interpreter at exit. The pipeline opens
  the mic inline (~10 ms); only transcription uses a dedicated, shut-down executor.
- The evdev hold-mode dispatch must ignore auto-repeat (`value == 2`), emit
  `release` on the trigger key-up **without** re-checking modifiers, and only
  emit `release` after a matching `press` (`active_hold` per keycode).
- `wl-copy` gets text on **stdin**, never argv (leading `-`). The clipboard is
  restored only when the save actually succeeded - a failed read must not clear it.
- First run downloads `large-v3-turbo` (~1.6 GB) to the HF cache.
- Qt objects are only ever touched on the Qt thread; the tray takes state from
  other threads as plain values and a 250 ms `QTimer` reconciles.

### History note

Commit history was rewritten once (2026-09-10): `[voice_typer]` prefixes
stripped, committed `*.pyc` and `GEMINI.md` purged. Local backups on
`backup/pre-rewrite*`. `origin/master` still needs a force-push to match.
