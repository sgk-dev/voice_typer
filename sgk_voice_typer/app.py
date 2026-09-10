"""Application lifecycle: SgkApp.

Wires everything together:

* config + logging
* CUDA library resolution (may re-exec the process once)
* the faster-whisper model, the mic recorder, the clipboard injector
* the dictation pipeline (asyncio loop in its own thread)
* the evdev push-to-talk listener
* the Qt tray, when a display and PyQt6 are available

Qt owns the main thread; the asyncio loop runs in a daemon thread. Shutdown is
driven from SIGTERM/SIGINT in __main__.
"""

from __future__ import annotations

import asyncio
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from sgk_voice_typer import __version__
from sgk_voice_typer.asr.cuda_env import sgk_ensure_cuda_libs
from sgk_voice_typer.core.hotkey_manager import SgkHotkeyManager
from sgk_voice_typer.core.pipeline import SgkDictationPipeline
from sgk_voice_typer.core.recorder import SgkRecorder
from sgk_voice_typer.feedback.cues import SgkSoundCues
from sgk_voice_typer.input.clipboard import SgkClipboard
from sgk_voice_typer.input.uinput_backend import SgkUinputInjector
from sgk_voice_typer.utils.config import SgkConfig
from sgk_voice_typer.utils.logger import sgk_configure_logging, sgk_get_logger

_logger = sgk_get_logger(__name__)


class SgkApp:
    def __init__(self, log_level_override: str | None = None, no_gui: bool = False) -> None:
        self._log_level_override = log_level_override
        self._no_gui = no_gui

        self._config = SgkConfig()
        self._cfg: dict[str, Any] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None
        self._executor: ThreadPoolExecutor | None = None
        self._hotkeys: SgkHotkeyManager | None = None
        self._pipeline: SgkDictationPipeline | None = None
        self._uinput: SgkUinputInjector | None = None
        self._cues: SgkSoundCues | None = None
        self._tray: Any = None
        self._overlay: Any = None
        self._qt_app: Any = None
        self._stopped = False

    # ------------------------------------------------------------------
    # start
    # ------------------------------------------------------------------

    def sgk_start(self) -> None:
        self._cfg = self._config.sgk_load()
        self._sgk_configure_logging()

        model_cfg = self._cfg.get("model", {})
        # May replace the process (re-exec with LD_LIBRARY_PATH). Guarded so it
        # happens at most once; everything above is cheap to redo.
        sgk_ensure_cuda_libs(model_cfg.get("device", "cuda"))

        _logger.info("sgk_app_starting", extra={"version": __version__})

        behavior = self._cfg.get("behavior", {})
        audio = self._cfg.get("audio", {})
        feedback = self._cfg.get("feedback", {})

        self._cues = SgkSoundCues(
            enabled=feedback.get("sound_enabled", True),
            volume=feedback.get("sound_volume", 0.25),
        )

        from sgk_voice_typer.asr.transcriber import SgkTranscriber

        transcriber = SgkTranscriber(
            name=model_cfg.get("name", "large-v3-turbo"),
            device=model_cfg.get("device", "cuda"),
            compute_type=model_cfg.get("compute_type", "float16"),
            language=model_cfg.get("language", "auto"),
            beam_size=model_cfg.get("beam_size", 5),
            no_speech_threshold=behavior.get("no_speech_threshold", 0.5),
        )

        self._uinput = SgkUinputInjector()
        clipboard = SgkClipboard(
            self._uinput,
            clipboard_settle_ms=behavior.get("clipboard_settle_ms", 80),
            paste_settle_ms=behavior.get("paste_settle_ms", 80),
            restore_clipboard=behavior.get("restore_clipboard", True),
        )
        recorder = SgkRecorder(
            sample_rate=audio.get("sample_rate", 16000),
            device=audio.get("device"),
            min_duration_s=behavior.get("min_duration_s", 0.3),
        )

        self._loop = asyncio.new_event_loop()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sgk-asr")
        self._pipeline = SgkDictationPipeline(
            recorder,
            transcriber,
            clipboard,
            self._loop,
            self._executor,
            max_duration_s=behavior.get("max_duration_s", 300.0),
            lock_hold_s=behavior.get("lock_hold_s", 3.0),
        )
        self._pipeline.sgk_set_state_listener(self._sgk_on_state)
        self._pipeline.sgk_set_lock_listener(self._sgk_on_lock)

        self._loop_thread = threading.Thread(
            target=self._loop.run_forever, name="sgk-asyncio", daemon=True
        )
        self._loop_thread.start()

        self._hotkeys = SgkHotkeyManager(self._cfg.get("hotkeys", {}))
        self._hotkeys.sgk_set_handlers(
            on_press=self._pipeline.sgk_on_press,
            on_release=self._pipeline.sgk_on_release,
            on_toggle=self._sgk_toggle_enabled,
        )
        if not behavior.get("enabled_on_start", True):
            self._hotkeys.sgk_set_paused(True)
        if not self._hotkeys.sgk_start(self._loop):
            _logger.error("sgk_hotkeys_unavailable_continuing_without_ptt")

        _logger.info(
            "sgk_app_ready",
            extra={"hotkeys": self._cfg.get("hotkeys", {}), "no_gui": self._no_gui},
        )

        if not self._no_gui and self._sgk_start_gui():
            assert self._qt_app is not None
            try:
                sys.exit(self._qt_app.exec())
            except SystemExit:
                pass
            finally:
                self.sgk_stop()
            return

        self._sgk_block_until_stopped()

    # ------------------------------------------------------------------
    # stop
    # ------------------------------------------------------------------

    def sgk_stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        _logger.info("sgk_app_stopping")

        if self._hotkeys is not None:
            self._hotkeys.sgk_stop()
        if self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._loop_thread is not None and self._loop_thread.is_alive():
            self._loop_thread.join(timeout=2.0)
        if self._loop is not None and not self._loop.is_running():
            self._loop.close()
        if self._executor is not None:
            # wait=True joins the worker thread - a dangling executor thread
            # racing native-extension teardown segfaults the interpreter at exit.
            self._executor.shutdown(wait=True, cancel_futures=True)
        if self._uinput is not None:
            self._uinput.sgk_close()
        for gui_obj in (self._overlay, self._tray):
            if gui_obj is not None:
                try:
                    gui_obj.sgk_destroy()
                except Exception:
                    pass
        if self._qt_app is not None:
            try:
                self._qt_app.quit()
            except Exception:
                pass
        _logger.info("sgk_app_stopped")

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _sgk_configure_logging(self) -> None:
        log_cfg = self._cfg.get("logging", {})
        level = self._log_level_override or log_cfg.get("level", "INFO")
        sgk_configure_logging(
            level=level,
            log_file=log_cfg.get("file"),
            max_bytes=log_cfg.get("max_bytes", 5_242_880),
            backup_count=log_cfg.get("backup_count", 3),
        )

    def _sgk_toggle_enabled(self) -> None:
        if self._hotkeys is None:
            return
        paused = not self._hotkeys.sgk_is_paused()
        self._hotkeys.sgk_set_paused(paused)
        _logger.info("sgk_toggle", extra={"paused": paused})
        if self._tray is not None:
            try:
                self._tray.sgk_set_paused(paused)
            except Exception:
                pass

    def _sgk_start_gui(self) -> bool:
        """Start the Qt tray + overlay. Returns False (fall back to headless) if
        PyQt6 is not available."""
        try:
            from PyQt6.QtWidgets import QApplication

            from sgk_voice_typer.gui.overlay import SgkListeningOverlay
            from sgk_voice_typer.gui.tray import SgkTrayIcon
        except ImportError as exc:
            _logger.warning("sgk_gui_unavailable", extra={"error": str(exc)})
            return False

        self._sgk_pick_qt_platform()
        self._qt_app = QApplication.instance() or QApplication(sys.argv)
        self._qt_app.setQuitOnLastWindowClosed(False)

        ui_cfg = self._cfg.get("ui", {})
        self._tray = SgkTrayIcon(
            on_pause_toggle=self._sgk_toggle_enabled,
            on_open_settings=self._sgk_open_settings,
            on_quit=self.sgk_stop,
            is_paused_getter=lambda: bool(self._hotkeys and self._hotkeys.sgk_is_paused()),
            lang=ui_cfg.get("language", "en"),
            icon_style=ui_cfg.get("tray_icon_style", "color"),
        )
        self._tray.sgk_create()

        fb_cfg = self._cfg.get("feedback", {})
        if fb_cfg.get("overlay_enabled", True) and self._pipeline is not None:
            self._overlay = SgkListeningOverlay(
                level_getter=self._pipeline.sgk_current_level,
                position=fb_cfg.get("overlay_position", "bottom-center"),
                screen=fb_cfg.get("overlay_screen", "auto"),
            )
            self._overlay.sgk_create()

        _logger.info("sgk_gui_started")
        return True

    def _sgk_on_state(self, state: str) -> None:
        """Pipeline state fan-out. Called from the asyncio thread - the sink
        objects only store flags / play sound, never touch Qt directly."""
        if state == "recording":
            if self._cues is not None:
                self._cues.play_start()
        elif state == "processing":
            if self._cues is not None:
                self._cues.play_stop()
        if self._tray is not None:
            self._tray.sgk_set_state(state)
        if self._overlay is not None:
            self._overlay.sgk_set_listening(state == "recording")

    def _sgk_on_lock(self, locked: bool) -> None:
        if self._overlay is not None:
            self._overlay.sgk_set_locked(locked)

    @staticmethod
    def _sgk_pick_qt_platform() -> None:
        """On GNOME Wayland, Mutter ignores client window positions, so the
        overlay cannot sit bottom-centre. Running the GUI through XWayland
        (xcb) fixes that - use it when the xcb-cursor lib and an X display are
        both present, and the user has not forced a platform."""
        import ctypes.util

        if os.environ.get("QT_QPA_PLATFORM"):
            return
        if os.environ.get("XDG_SESSION_TYPE", "").lower() != "wayland":
            return
        if os.environ.get("DISPLAY") and ctypes.util.find_library("xcb-cursor"):
            os.environ["QT_QPA_PLATFORM"] = "xcb"
            _logger.info("sgk_qt_platform", extra={"platform": "xcb"})
        else:
            _logger.info(
                "sgk_qt_platform",
                extra={"platform": "wayland",
                       "hint": "install libxcb-cursor0 for correct overlay placement"},
            )

    def _sgk_open_settings(self) -> None:
        try:
            from sgk_voice_typer.gui.config_dialog import SgkConfigDialog
        except ImportError:
            return
        SgkConfigDialog(
            self._cfg,
            on_save=self._sgk_on_settings_saved,
            on_ui_changed=self._sgk_apply_ui,
        ).sgk_show()

    def _sgk_apply_ui(self, lang: str, icon_style: str) -> None:
        if self._tray is not None:
            try:
                self._tray.sgk_apply_ui(lang=lang, icon_style=icon_style)
            except Exception as exc:
                _logger.error("sgk_apply_ui_error", extra={"error": str(exc)})

    def _sgk_on_settings_saved(self, new_cfg: dict[str, Any]) -> None:
        old = self._cfg
        self._config.sgk_save(new_cfg)
        self._cfg = new_cfg
        _logger.info("sgk_settings_saved")

        beh = new_cfg.get("behavior", {})
        if self._pipeline is not None:
            self._pipeline.clipboard.sgk_configure(
                clipboard_settle_ms=beh.get("clipboard_settle_ms", 80),
                paste_settle_ms=beh.get("paste_settle_ms", 80),
                restore_clipboard=bool(beh.get("restore_clipboard", True)),
            )
            self._pipeline.sgk_set_max_duration(beh.get("max_duration_s", 300.0))
            self._pipeline.sgk_set_lock_hold(beh.get("lock_hold_s", 3.0))

        fb = new_cfg.get("feedback", {})
        if self._cues is not None:
            self._cues.sgk_set(
                enabled=fb.get("sound_enabled", True),
                volume=fb.get("sound_volume", 0.25),
            )

        # Microphone / min-duration can be swapped live.
        new_audio = new_cfg.get("audio", {})
        old_beh = old.get("behavior", {})
        if new_audio != old.get("audio", {}) or beh.get("min_duration_s") != old_beh.get(
            "min_duration_s"
        ):
            self._sgk_swap_recorder(new_audio, beh)

        # Model and hotkey changes need a restart (the dialog says so).
        if new_cfg.get("model", {}) != old.get("model", {}) or new_cfg.get(
            "hotkeys", {}
        ) != old.get("hotkeys", {}):
            _logger.info("sgk_settings_restart_required")

    def _sgk_swap_recorder(self, audio: dict[str, Any], beh: dict[str, Any]) -> None:
        if self._pipeline is None:
            return
        recorder = SgkRecorder(
            sample_rate=audio.get("sample_rate", 16000),
            device=audio.get("device"),
            min_duration_s=beh.get("min_duration_s", 0.3),
        )
        self._pipeline.sgk_set_recorder(recorder)
        _logger.info("sgk_recorder_swapped", extra={"device": str(audio.get("device"))})

    def _sgk_block_until_stopped(self) -> None:
        assert self._loop_thread is not None
        try:
            while self._loop_thread.is_alive():
                self._loop_thread.join(1.0)
        except KeyboardInterrupt:
            pass
        finally:
            self.sgk_stop()
