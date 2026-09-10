"""Dictation pipeline: press -> record, release -> transcribe -> type.

Runs on the asyncio loop. Opening / closing the mic stream is fast (~10 ms) and
happens inline; only the GPU transcription is pushed to a dedicated
single-worker executor, so two phrases can never race for VRAM.

Two ways to end a recording:

* **push-to-talk** - hold the key, release to stop (the default);
* **hands-free lock** - if the key is held longer than ``lock_hold_s`` the
  recording latches: releasing the key does nothing, a fresh press stops it.
  The overlay shows a padlock while latched.

A re-entrancy guard (``_active`` / ``_processing``) means a second press while a
recording (that is not latched) or a transcription is in flight is ignored. The
hard duration cap is a loop timer that runs the same finish path as a release.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import Executor
from typing import Callable

from sgk_voice_typer.utils.logger import sgk_get_logger

_logger = sgk_get_logger(__name__)

# Pipeline states, surfaced to the tray.
SGK_IDLE = "idle"
SGK_RECORDING = "recording"
SGK_PROCESSING = "processing"


class SgkDictationPipeline:
    def __init__(
        self,
        recorder,
        transcriber,
        clipboard,
        loop: asyncio.AbstractEventLoop,
        transcribe_executor: Executor,
        max_duration_s: float = 300.0,
        lock_hold_s: float = 3.0,
        preview_interval_s: float = 0.0,
    ) -> None:
        self._recorder = recorder
        self._transcriber = transcriber
        self._clipboard = clipboard
        self._loop = loop
        self._executor = transcribe_executor
        self._max_duration_s = max_duration_s
        self._lock_hold_s = lock_hold_s
        self._preview_interval_s = preview_interval_s

        self._active = False
        self._processing = False
        self._terminal = False
        self._locked = False
        self._generation = 0            # bumps each recording; stale preview results are dropped
        self._watchdog: asyncio.TimerHandle | None = None
        self._lock_timer: asyncio.TimerHandle | None = None
        self._preview_task: asyncio.Task | None = None
        self._on_state: Callable[[str], None] | None = None
        self._on_lock: Callable[[bool], None] | None = None
        self._on_partial: Callable[[str], None] | None = None

    def sgk_set_state_listener(self, cb: Callable[[str], None]) -> None:
        self._on_state = cb

    def sgk_set_lock_listener(self, cb: Callable[[bool], None]) -> None:
        self._on_lock = cb

    def sgk_set_partial_listener(self, cb: Callable[[str], None]) -> None:
        """cb(text) is called with the growing transcript while recording."""
        self._on_partial = cb

    def sgk_set_preview_interval(self, seconds: float) -> None:
        self._preview_interval_s = seconds

    def sgk_set_recorder(self, recorder) -> None:
        """Swap the recorder (settings dialog changed the microphone)."""
        if not self._active:
            self._recorder = recorder

    def sgk_set_max_duration(self, seconds: float) -> None:
        self._max_duration_s = seconds

    def sgk_set_lock_hold(self, seconds: float) -> None:
        self._lock_hold_s = seconds

    def sgk_current_level(self) -> float:
        """Latest mic input level (for the on-screen overlay). 0.0 when idle."""
        return float(getattr(self._recorder, "level", 0.0) or 0.0)

    @property
    def clipboard(self):
        return self._clipboard

    def _emit(self, state: str) -> None:
        if self._on_state:
            try:
                self._on_state(state)
            except Exception as exc:  # a broken listener must not break dictation
                _logger.debug("sgk_state_listener_error", extra={"error": str(exc)})

    def _emit_lock(self, locked: bool) -> None:
        if self._on_lock:
            try:
                self._on_lock(locked)
            except Exception as exc:
                _logger.debug("sgk_lock_listener_error", extra={"error": str(exc)})

    def _emit_partial(self, text: str) -> None:
        if self._on_partial:
            try:
                self._on_partial(text)
            except Exception as exc:
                _logger.debug("sgk_partial_listener_error", extra={"error": str(exc)})

    # ------------------------------------------------------------------
    # hotkey entry points (coroutines, scheduled by the hotkey manager)
    # ------------------------------------------------------------------

    async def sgk_on_press(self, terminal: bool) -> None:
        # A press while latched is the stop signal.
        if self._locked:
            await self._sgk_finish(capped=False)
            return
        if self._active or self._processing:
            return
        self._active = True
        self._terminal = terminal
        self._generation += 1
        ok = self._recorder.start()
        if not ok:
            self._active = False
            self._emit(SGK_IDLE)
            return
        self._emit(SGK_RECORDING)
        self._watchdog = self._loop.call_later(self._max_duration_s, self._sgk_auto_stop)
        if self._lock_hold_s > 0:
            self._lock_timer = self._loop.call_later(self._lock_hold_s, self._sgk_engage_lock)
        if self._preview_interval_s > 0 and self._on_partial is not None:
            self._preview_task = self._loop.create_task(self._sgk_preview_loop(self._generation))

    async def sgk_on_release(self, terminal: bool) -> None:
        if self._locked or not self._active:
            return  # latched: keep recording until the next press
        await self._sgk_finish(capped=False)

    def _sgk_engage_lock(self) -> None:
        self._lock_timer = None
        if self._active and not self._locked:
            self._locked = True
            _logger.info("sgk_recording_locked")
            self._emit_lock(True)

    def _sgk_auto_stop(self) -> None:
        if self._active:
            _logger.info("sgk_recording_capped", extra={"cap_s": self._max_duration_s})
            self._loop.create_task(self._sgk_finish(capped=True))

    # ------------------------------------------------------------------
    # live preview: re-transcribe the audio-so-far on an interval
    # ------------------------------------------------------------------

    async def _sgk_preview_loop(self, gen: int) -> None:
        try:
            while self._active and gen == self._generation:
                await asyncio.sleep(self._preview_interval_s)
                if not self._active or gen != self._generation:
                    break
                audio = self._recorder.snapshot()
                if audio is None or audio.size < 12000:   # < ~0.75 s
                    continue
                try:
                    text = await self._loop.run_in_executor(
                        self._executor, self._transcriber.transcribe, audio
                    )
                except Exception as exc:
                    _logger.debug("sgk_preview_error", extra={"error": str(exc)})
                    continue
                if text and self._active and gen == self._generation:
                    self._emit_partial(text)
        except asyncio.CancelledError:
            pass

    def _sgk_cancel_timers(self) -> None:
        for attr in ("_watchdog", "_lock_timer"):
            handle = getattr(self, attr)
            if handle is not None:
                handle.cancel()
                setattr(self, attr, None)
        if self._preview_task is not None:
            self._preview_task.cancel()
            self._preview_task = None

    async def _sgk_finish(self, capped: bool) -> None:
        if not self._active:
            return
        self._active = False
        self._processing = True
        self._sgk_cancel_timers()
        if self._locked:
            self._locked = False
            self._emit_lock(False)
        self._emit(SGK_PROCESSING)
        try:
            audio = self._recorder.stop()
            if audio is None:
                return
            text = await self._loop.run_in_executor(
                self._executor, self._transcriber.transcribe, audio
            )
            if not text:
                return
            await self._clipboard.sgk_save()
            try:
                await self._clipboard.sgk_type(text, terminal=self._terminal)
            finally:
                await self._clipboard.sgk_restore()
        except Exception as exc:
            _logger.error("sgk_pipeline_error", extra={"error": str(exc)})
        finally:
            self._processing = False
            self._emit(SGK_IDLE)
