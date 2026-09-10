#!/usr/bin/env python3
"""
voice_typer daemon entry point.
Hold F9 → speak → release → text appears at cursor.
"""
from __future__ import annotations

import os
import sys

_CUDA_LIBS = (
    "/home/sgk/.venvs/transcribe/lib/python3.12/site-packages/nvidia/cublas/lib"
    ":/home/sgk/.venvs/transcribe/lib/python3.12/site-packages/nvidia/cudnn/lib"
)
if "cublas" not in os.environ.get("LD_LIBRARY_PATH", ""):
    os.environ["LD_LIBRARY_PATH"] = _CUDA_LIBS + ":" + os.environ.get("LD_LIBRARY_PATH", "")
    os.execv(sys.executable, [sys.executable] + sys.argv)

import logging
import queue
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

import numpy as np
import sounddevice as sd
from evdev import ecodes

from voice_typer.config import load_config
from voice_typer.inference import Transcriber
from voice_typer.injector import inject
from voice_typer.listener import PttListener


def _setup_logging(log_file: str, max_bytes: int, backup_count: int) -> None:
    log_path = Path(log_file).expanduser()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_path, maxBytes=max_bytes, backupCount=backup_count)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logging.basicConfig(
        level=logging.INFO,
        handlers=[handler, logging.StreamHandler()],
    )


def main() -> None:
    cfg = load_config()
    _setup_logging(cfg.log_file, cfg.log_max_bytes, cfg.log_backup_count)

    _logger = logging.getLogger(__name__)
    _logger.info("Starting voice_typer daemon")
    _logger.info("Loading model %s on %s...", cfg.model_name, cfg.device)

    transcriber = Transcriber(cfg)
    _logger.info("Model ready. PTT key: %s", cfg.hotkey)

    # State flags shared between threads
    _recording = threading.Event()
    _audio_queue: queue.Queue[np.ndarray] = queue.Queue()
    _shutdown = threading.Event()

    def on_press() -> None:
        if not _recording.is_set():
            _recording.set()
            _logger.debug("PTT pressed — recording started")

    def on_release() -> None:
        if _recording.is_set():
            _recording.clear()
            _logger.debug("PTT released — recording stopped")

    # Recorder thread: captures audio while _recording is set
    def recorder_thread() -> None:
        while not _shutdown.is_set():
            if not _recording.wait(timeout=0.05):
                continue
            # Recording is active — collect audio
            chunks: list[np.ndarray] = []

            def cb(indata: np.ndarray, frames: int, t, status) -> None:
                chunks.append(indata.copy())

            with sd.InputStream(
                samplerate=cfg.sample_rate,
                channels=1,
                dtype="float32",
                device=cfg.audio_device,
                callback=cb,
            ):
                # Wait until PTT released
                while _recording.is_set() and not _shutdown.is_set():
                    time.sleep(0.02)

            if chunks:
                audio = np.concatenate(chunks, axis=0).flatten()
                _audio_queue.put(audio)

    # Inference + inject thread: processes audio queue
    def inference_thread() -> None:
        while not _shutdown.is_set():
            try:
                audio = _audio_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            text = transcriber.transcribe(audio)
            if text:
                inject(
                    text,
                    terminal_apps=cfg.terminal_apps,
                    sleep_after=cfg.sleep_after_paste,
                )

    # Start threads
    key_code = getattr(ecodes, cfg.hotkey, ecodes.KEY_F9)
    listener = PttListener(key_code, on_press, on_release)
    listener.start()

    rec_t = threading.Thread(target=recorder_thread, daemon=True, name="recorder")
    inf_t = threading.Thread(target=inference_thread, daemon=True, name="inference")
    rec_t.start()
    inf_t.start()

    _logger.info("Daemon ready. Hold %s to record.", cfg.hotkey)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        _logger.info("Shutting down...")
        _shutdown.set()
        listener.stop()


if __name__ == "__main__":
    main()
