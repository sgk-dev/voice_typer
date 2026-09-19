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
| `__main__.py` | argparse (`--no-gui` / `--log-level` / `--install-desktop` / `--install` / `--version`), single-instance guard, signal handlers |
| `app.py` | `SgkApp` - wires everything; tray first, model loads on the executor, hotkeys start when it is ready; signal wakeup fd for Qt; shutdown |
| `asr/cuda_env.py` | find the pip CUDA libs, prepend `LD_LIBRARY_PATH`, re-exec once (guarded by `SGK_VT_CUDA_REEXEC`) |
| `asr/transcriber.py` | `SgkTranscriber` - faster-whisper wrapper, injectable model; `fast=True` = greedy (preview) |
| `core/recorder.py` | `SgkRecorder` - `sounddevice` capture, `snapshot(tail_s)` for preview, drops sub-`min_duration` clips |
| `core/pipeline.py` | `SgkDictationPipeline` - press→record, release→transcribe→type; hands-free lock; 20 s greedy preview loop; re-entrancy guard, duration cap |
| `core/hotkey_manager.py` | `SgkHotkeyManager` - evdev thread → asyncio loop; terminal flag by hotkey name; toggle debounce; pause gates *press* only |
| `input/base.py` | `SgkInputBackend` abstract, `(name, phase)` callback, `sgk_keys_held` |
| `input/evdev_backend.py` | `SgkEvdevHotkeyListener` - hold-mode dispatch state machine; 5 s hot-plug rescan; ignores "Virtual Keyboard" devices |
| `input/uinput_backend.py` | `SgkUinputInjector` - virtual keyboard, `sgk_paste(shift=...)` |
| `input/clipboard.py` | `SgkClipboard` - save/restore (`wl-paste --type text`) + `sgk_type` via `wl-copy` (stdin), waits for physical key release, synthetic paste |
| `feedback/cues.py` | `SgkSoundCues` - synthesised start/stop chimes, 6 styles |
| `gui/overlay.py` | `SgkListeningOverlay` - equaliser pill + live transcript, Qt-signal reconcile, paint timer only while visible |
| `gui/tray.py` | `SgkTrayIcon` - 5 states (loading/idle/recording/processing/paused), Qt-signal reconcile, About |
| `gui/config_dialog.py` | `SgkConfigDialog` - General/Model/Microphone/Hotkeys/Behavior tabs |
| `gui/i18n.py` | `sgk_tr` - en/ru string table, English fallback |
| `utils/config.py` | `SgkConfig` - load/save/deep-merge |
| `utils/logger.py` | structured JSON logging under the `sgk_voice_typer` hierarchy |
| `utils/single_instance.py` | flock guard |
| `utils/autostart.py` / `utils/resources.py` | XDG autostart entry, `.desktop` text (generated in code) |

## WHY

- **`uinput`, not `wtype`.** Mutter does not support `wtype`; the paste is a
  synthetic `Ctrl+V` (`Ctrl+Shift+V` for terminals) through a virtual keyboard.
- **Second hotkey for terminals**, not window detection. `org.gnome.Shell.Eval`
  is closed on GNOME 42+ and there is no public focused-window API on Wayland.
  `F9` → `Ctrl+V`, `Shift+F9` → `Ctrl+Shift+V`.
- **CUDA libs at runtime.** The `nvidia-*-cu12` wheels install under
  `site-packages/nvidia/*/lib`, off the linker path. `cuda_env` prepends them
  and re-execs once - never hardcode `LD_LIBRARY_PATH` anywhere.
- **One autostart scheme: the XDG entry.** It inherits the full session
  environment (DISPLAY for the xcb overlay, WAYLAND_DISPLAY, D-Bus) and the
  Settings checkbox toggles it. A systemd user unit was dropped in 0.4.0 - it
  lacked DISPLAY and doubled the launches.
- **Tray before model.** Model load takes 5-15 s; the tray shows "loading"
  meanwhile and the evdev listener starts only once the transcriber is set.
- **No idle polling.** Tray / overlay setters emit a Qt signal (cross-thread
  emit is queued by Qt); the overlay paint timer runs only while visible;
  evdev blocks in `select` (5 s timeout doubles as the hot-plug rescan).
  Measured idle: 0-0.3% CPU.
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
sgk-voice-typer --install                              # menu entry + XDG autostart
bash packaging/install.sh                              # deploy (venv + udev + install)
```

Restarting the live daemon from a tool session: kill by PID only
(`kill $(pgrep -f "python3 -m [s]gk_voice_typer")` - `pkill -f` kills the
tool's own shell), then `setsid nohup python3 -m sgk_voice_typer ... &` in a
separate call. Log: `~/.local/share/sgk-voice-typer/voice_typer.log`.

Physical smoke test: hold `F9` in a text field → text appears; hold `Shift+F9`
in a terminal → text appears; the clipboard is restored; Cyrillic is intact.

### Tests / checks

```bash
~/.venvs/transcribe/bin/python -m pytest tests/unit -q   # ~150 tests
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
- Version lives only in `sgk_voice_typer/__init__.py` (`pyproject.toml` is
  `dynamic`); keep `packaging/debian/changelog` in step.
- Config access in `app.py` indexes keys directly: `SgkConfig` always deep-merges
  onto the defaults, so the defaults table in `utils/config.py` is the single
  source of fallbacks - do not re-add `.get(k, literal)` there.
- Branches: `master` and `staging` only. Work on `staging`, then
  `git branch -f master staging`, push both. Single-project repo → **no
  `[module]` prefix**, one-line commits, no AI attribution footers.
- Release: bump version, changelog, `python -m build` in a clean venv +
  `twine check`, tag `vX.Y.Z`, `gh release create`; PyPI upload is manual
  (`twine upload dist/*`).

### Gotchas

- **`run_in_executor(None, ...)`** (the asyncio default executor) spawns threads
  that are never joined and segfault the interpreter at exit. The pipeline opens
  the mic inline (~10 ms); only transcription uses a dedicated, shut-down executor.
- The evdev hold-mode dispatch must ignore auto-repeat (`value == 2`), emit
  `release` on the trigger key-up **without** re-checking modifiers, and only
  emit `release` after a matching `press` (`active_hold` per keycode).
- `wl-copy` gets text on **stdin**, never argv (leading `-`). The clipboard is
  restored only when the save actually succeeded - a failed read must not clear it.
  `wl-paste --type text` returns rc != 0 for an image: that is "no text", restore
  clears rather than writing binary garbage back.
- The paste waits up to 600 ms for `sgk_keys_held()` to clear - a Shift still
  down after Shift+F9 would turn the synthetic Ctrl+V into another combo.
- The live preview must stay windowed (`_PREVIEW_TAIL_S`) and greedy: a full
  beam-search re-transcription every 1.5 s is O(n²) on long dictations and the
  final pass queues behind it on the single-worker executor.
- A silent microphone (`audio.device` = an ALSA plumbing alias such as
  `sysdefault`) shows as `sgk_transcribe_empty` with growing `audio_s`; the
  device list in Settings filters `_SGK_ALSA_NOISE`, but a hand-edited config can
  still pick one.
- First run downloads `large-v3-turbo` (~1.6 GB) to the HF cache.
- Qt objects are only ever touched on the Qt thread; tray / overlay setters
  store plain values and emit a `pyqtSignal` from any thread.
- Python signal handlers do not run while the main thread sits in Qt's
  `exec()`; `app.py` installs `signal.set_wakeup_fd` + `QSocketNotifier` so
  SIGTERM is delivered without a polling timer. Keep it if timers ever return.

### History note

Commit history was rewritten once (2026-09-10): `[voice_typer]` prefixes
stripped, committed `*.pyc` and `GEMINI.md` purged; `origin` matches since
the v0.2.0 force-push. Local `backup/pre-rewrite*` branches can be deleted.
