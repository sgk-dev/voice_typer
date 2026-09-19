"""Application lifecycle: SgkApp.

Wires everything together:

* config + logging
* CUDA library resolution (may re-exec the process once)
* the faster-whisper model, the mic recorder, the clipboard injector
* the dictation pipeline (asyncio loop in its own thread)
* the evdev push-to-talk listener
* the Qt tray, when a display and PyQt6 are available

Qt owns the main thread; the asyncio loop runs in a daemon thread. The Whisper
model loads on the transcription executor *after* the tray is up, so the user
sees a "loading" icon within a second instead of nothing for 10-15 s; the
push-to-talk listener starts once the model is ready. Shutdown is driven from
SIGTERM/SIGINT in __main__; with the GUI running, the signal is delivered to
Python through ``signal.set_wakeup_fd`` + a ``QSocketNotifier`` so it never
waits for an unrelated Qt callback.
"""

from __future__ import annotations

import asyncio
import os
import signal
import socket
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
        self._sig_socks: tuple[socket.socket, socket.socket] | None = None
        self._sig_notifier: Any = None
        self._stopped = False

    # ------------------------------------------------------------------
    # start
    # ------------------------------------------------------------------

    def sgk_start(self) -> None:
        self._cfg = self._config.sgk_load()
        self._sgk_configure_logging()

        model_cfg = self._cfg["model"]
        # May replace the process (re-exec with LD_LIBRARY_PATH). Guarded so it
        # happens at most once; everything above is cheap to redo.
        sgk_ensure_cuda_libs(model_cfg["device"])

        _logger.info("sgk_app_starting", extra={"version": __version__})

        behavior = self._cfg["behavior"]
        audio = self._cfg["audio"]
        feedback = self._cfg["feedback"]

        self._cues = SgkSoundCues(
            enabled=feedback["sound_enabled"],
            volume=feedback["sound_volume"],
            style=feedback["sound_style"],
        )

        self._hotkeys = SgkHotkeyManager(self._cfg["hotkeys"])
        self._uinput = SgkUinputInjector()
        clipboard = SgkClipboard(
            self._uinput,
            clipboard_settle_ms=behavior["clipboard_settle_ms"],
            paste_settle_ms=behavior["paste_settle_ms"],
            restore_clipboard=behavior["restore_clipboard"],
            keys_held=self._hotkeys.sgk_keys_held,
        )
        recorder = self._sgk_make_recorder(audio, behavior)

        self._loop = asyncio.new_event_loop()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sgk-asr")
        self._pipeline = SgkDictationPipeline(
            recorder,
            None,
            clipboard,
            self._loop,
            self._executor,
            max_duration_s=behavior["max_duration_s"],
            lock_hold_s=behavior["lock_hold_s"],
            preview_interval_s=self._sgk_preview_interval(feedback),
        )
        self._pipeline.sgk_set_state_listener(self._sgk_on_state)
        self._pipeline.sgk_set_lock_listener(self._sgk_on_lock)
        self._pipeline.sgk_set_partial_listener(self._sgk_on_partial)

        self._loop_thread = threading.Thread(
            target=self._loop.run_forever, name="sgk-asyncio", daemon=True
        )
        self._loop_thread.start()

        self._hotkeys.sgk_set_handlers(
            on_press=self._pipeline.sgk_on_press,
            on_release=self._pipeline.sgk_on_release,
            on_toggle=self._sgk_toggle_enabled,
        )
        if not behavior["enabled_on_start"]:
            self._hotkeys.sgk_set_paused(True)

        gui = not self._no_gui and self._sgk_start_gui()
        self._loop.call_soon_threadsafe(self._sgk_schedule_model_load, model_cfg, behavior)

        if gui:
            assert self._qt_app is not None
            try:
                sys.exit(self._qt_app.exec())
            except SystemExit:
                pass
            finally:
                self.sgk_stop()
            return

        self._sgk_block_until_stopped()

    def _sgk_schedule_model_load(self, model_cfg: dict[str, Any], behavior: dict[str, Any]) -> None:
        assert self._loop is not None and self._executor is not None

        def _load():
            from sgk_voice_typer.asr.transcriber import SgkTranscriber

            return SgkTranscriber(
                name=model_cfg["name"],
                device=model_cfg["device"],
                compute_type=model_cfg["compute_type"],
                language=model_cfg["language"],
                beam_size=model_cfg["beam_size"],
                no_speech_threshold=behavior["no_speech_threshold"],
            )

        self._loop.run_in_executor(self._executor, _load).add_done_callback(self._sgk_on_model_loaded)

    def _sgk_on_model_loaded(self, fut: asyncio.Future) -> None:
        if self._stopped:
            return
        try:
            transcriber = fut.result()
        except Exception as exc:
            _logger.error("sgk_model_load_failed", extra={"error": str(exc)})
            self.sgk_stop()
            return
        assert self._pipeline is not None and self._hotkeys is not None and self._loop is not None
        self._pipeline.sgk_set_transcriber(transcriber)
        if not self._hotkeys.sgk_start(self._loop):
            _logger.error("sgk_hotkeys_unavailable_continuing_without_ptt")
        if self._tray is not None:
            self._tray.sgk_set_state("idle")
        _logger.info(
            "sgk_app_ready",
            extra={"hotkeys": self._cfg["hotkeys"], "no_gui": self._no_gui},
        )

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
        if (
            self._loop_thread is not None
            and self._loop_thread.is_alive()
            and threading.current_thread() is not self._loop_thread
        ):
            self._loop_thread.join(timeout=2.0)
        if self._loop is not None and not self._loop.is_running():
            self._loop.close()
        if self._executor is not None:
            # wait=True joins the worker thread - a dangling executor thread
            # racing native-extension teardown segfaults the interpreter at exit.
            self._executor.shutdown(wait=True, cancel_futures=True)
        if self._uinput is not None:
            self._uinput.sgk_close()
        self._sgk_teardown_signal_pump()
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
        log_cfg = self._cfg["logging"]
        sgk_configure_logging(
            level=self._log_level_override or log_cfg["level"],
            log_file=log_cfg["file"],
            max_bytes=log_cfg["max_bytes"],
            backup_count=log_cfg["backup_count"],
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

    def _sgk_toggle_sound(self) -> None:
        if self._cues is None:
            return
        enabled = not self._cues.sgk_enabled
        fb = self._cfg.setdefault("feedback", {})
        fb["sound_enabled"] = enabled
        self._cues.sgk_set(enabled=enabled, volume=fb["sound_volume"])
        self._config.sgk_save(self._cfg)
        if self._tray is not None:
            self._tray.sgk_set_sound_enabled(enabled)
        _logger.info("sgk_sound_toggle", extra={"enabled": enabled})

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
        self._sgk_setup_signal_pump()

        ui_cfg = self._cfg["ui"]
        self._tray = SgkTrayIcon(
            on_pause_toggle=self._sgk_toggle_enabled,
            on_open_settings=self._sgk_open_settings,
            on_quit=self.sgk_stop,
            lang=ui_cfg["language"],
            icon_style=ui_cfg["tray_icon_style"],
            on_sound_toggle=self._sgk_toggle_sound,
        )
        self._tray.sgk_create()
        self._tray.sgk_set_paused(bool(self._hotkeys and self._hotkeys.sgk_is_paused()))
        self._tray.sgk_set_sound_enabled(bool(self._cues and self._cues.sgk_enabled))

        fb_cfg = self._cfg["feedback"]
        if fb_cfg["overlay_enabled"] and self._pipeline is not None:
            self._overlay = SgkListeningOverlay(
                level_getter=self._pipeline.sgk_current_level,
                screen=fb_cfg["overlay_screen"],
                preview=fb_cfg["live_preview"],
            )
            self._overlay.sgk_create()

        _logger.info("sgk_gui_started")
        return True

    def _sgk_setup_signal_pump(self) -> None:
        """Python only runs signal handlers between bytecodes; while the main
        thread sits in Qt's exec() that never happens on its own. The wakeup fd
        makes the C-level handler write a byte, the notifier wakes Qt, and the
        Python handler (__main__) runs in that callback."""
        try:
            from PyQt6.QtCore import QSocketNotifier

            r, w = socket.socketpair()
            w.setblocking(False)
            signal.set_wakeup_fd(w.fileno())
            notifier = QSocketNotifier(r.fileno(), QSocketNotifier.Type.Read)  # type: ignore[call-overload]
            notifier.activated.connect(lambda *_: r.recv(4096))
            self._sig_socks, self._sig_notifier = (r, w), notifier
        except (ImportError, ValueError, OSError) as exc:
            _logger.debug("sgk_signal_pump_unavailable", extra={"error": str(exc)})

    def _sgk_teardown_signal_pump(self) -> None:
        if self._sig_socks is None:
            return
        try:
            signal.set_wakeup_fd(-1)
        except ValueError:
            pass
        for sock in self._sig_socks:
            try:
                sock.close()
            except OSError:
                pass
        self._sig_socks, self._sig_notifier = None, None

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

    def _sgk_on_partial(self, text: str) -> None:
        if self._overlay is not None:
            self._overlay.sgk_set_preview(text)

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
        new_cfg = SgkConfig.sgk_with_defaults(new_cfg)
        self._config.sgk_save(new_cfg)
        self._cfg = new_cfg
        _logger.info("sgk_settings_saved")

        beh = new_cfg["behavior"]
        fb = new_cfg["feedback"]
        if self._pipeline is not None:
            self._pipeline.clipboard.sgk_configure(
                clipboard_settle_ms=beh["clipboard_settle_ms"],
                paste_settle_ms=beh["paste_settle_ms"],
                restore_clipboard=bool(beh["restore_clipboard"]),
            )
            self._pipeline.sgk_set_max_duration(beh["max_duration_s"])
            self._pipeline.sgk_set_lock_hold(beh["lock_hold_s"])
            self._pipeline.sgk_set_preview_interval(self._sgk_preview_interval(fb))
        if self._cues is not None:
            self._cues.sgk_set(
                enabled=fb["sound_enabled"], volume=fb["sound_volume"], style=fb["sound_style"]
            )
            if self._tray is not None:
                self._tray.sgk_set_sound_enabled(fb["sound_enabled"])

        if new_cfg["audio"] != old["audio"] or beh["min_duration_s"] != old["behavior"]["min_duration_s"]:
            if self._pipeline is not None:
                self._pipeline.sgk_set_recorder(self._sgk_make_recorder(new_cfg["audio"], beh))
                _logger.info("sgk_recorder_swapped", extra={"device": str(new_cfg["audio"]["device"])})

        if new_cfg["model"] != old["model"] or new_cfg["hotkeys"] != old["hotkeys"]:
            _logger.info("sgk_settings_restart_required")

    @staticmethod
    def _sgk_make_recorder(audio: dict[str, Any], beh: dict[str, Any]) -> SgkRecorder:
        return SgkRecorder(
            sample_rate=audio["sample_rate"],
            device=audio["device"],
            min_duration_s=beh["min_duration_s"],
        )

    def _sgk_preview_interval(self, fb: dict[str, Any]) -> float:
        if fb["live_preview"] and not self._no_gui:
            return float(fb["preview_interval_s"])
        return 0.0

    def _sgk_block_until_stopped(self) -> None:
        assert self._loop_thread is not None
        try:
            while self._loop_thread.is_alive():
                self._loop_thread.join(1.0)
        except KeyboardInterrupt:
            pass
        finally:
            self.sgk_stop()
