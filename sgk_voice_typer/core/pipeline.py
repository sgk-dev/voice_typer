"""Dictation pipeline: press -> record, release -> transcribe -> type.

Runs on the asyncio loop. Opening / closing the mic stream is fast (~10 ms) and
happens inline; only the GPU transcription is pushed to a dedicated
single-worker executor, so two phrases can never race for VRAM.

A re-entrancy guard (``_active`` / ``_processing``) means a second press while
a recording or a transcription is in flight is ignored. The hard duration cap
is a loop timer that runs the same finish path as a real release.
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
        max_duration_s: float = 60.0,
    ) -> None:
        self._recorder = recorder
        self._transcriber = transcriber
        self._clipboard = clipboard
        self._loop = loop
        self._executor = transcribe_executor
        self._max_duration_s = max_duration_s

        self._active = False
        self._processing = False
        self._terminal = False
        self._watchdog: asyncio.TimerHandle | None = None
        self._on_state: Callable[[str], None] | None = None

    def sgk_set_state_listener(self, cb: Callable[[str], None]) -> None:
        self._on_state = cb

    def sgk_set_recorder(self, recorder) -> None:
        """Swap the recorder (settings dialog changed the microphone)."""
        if not self._active:
            self._recorder = recorder

    def sgk_set_max_duration(self, seconds: float) -> None:
        self._max_duration_s = seconds

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

    # ------------------------------------------------------------------
    # hotkey entry points (coroutines, scheduled by the hotkey manager)
    # ------------------------------------------------------------------

    async def sgk_on_press(self, terminal: bool) -> None:
        if self._active or self._processing:
            return
        self._active = True
        self._terminal = terminal
        ok = self._recorder.start()
        if not ok:
            self._active = False
            self._emit(SGK_IDLE)
            return
        self._emit(SGK_RECORDING)
        self._watchdog = self._loop.call_later(self._max_duration_s, self._sgk_auto_stop)

    async def sgk_on_release(self, terminal: bool) -> None:
        if not self._active:
            return
        await self._sgk_finish(capped=False)

    def _sgk_auto_stop(self) -> None:
        if self._active:
            _logger.info("sgk_recording_capped", extra={"cap_s": self._max_duration_s})
            self._loop.create_task(self._sgk_finish(capped=True))

    # ------------------------------------------------------------------

    async def _sgk_finish(self, capped: bool) -> None:
        if not self._active:
            return
        self._active = False
        self._processing = True
        if self._watchdog is not None:
            self._watchdog.cancel()
            self._watchdog = None
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
