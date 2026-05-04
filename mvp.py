#!/usr/bin/env python3
"""
Stage 1 manual test: record → transcribe → print.
Run: python mvp.py
Press Enter to start recording, Enter again to stop.
"""
from __future__ import annotations

import logging
import os
import sys

os.environ.setdefault(
    "LD_LIBRARY_PATH",
    "/home/sgk/.venvs/transcribe/lib/python3.12/site-packages/nvidia/cublas/lib"
    ":/home/sgk/.venvs/transcribe/lib/python3.12/site-packages/nvidia/cudnn/lib",
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)

from voice_typer.config import load_config
from voice_typer.inference import Transcriber
from voice_typer.recorder import record_while_held


def main() -> None:
    cfg = load_config()
    print(f"Loading model {cfg.model_name} on {cfg.device}...")
    transcriber = Transcriber(cfg)
    print("Ready.\n")

    try:
        while True:
            print("Press Enter to start recording (Ctrl+C to quit)...")
            input()
            audio = record_while_held(sample_rate=cfg.sample_rate, device=cfg.audio_device)
            print("Transcribing...")
            result = transcriber.transcribe(audio)
            if result:
                print(f"\n>>> {result}\n")
            else:
                print("(nothing recognized — silence or low confidence)\n")
    except KeyboardInterrupt:
        print("\nBye.")
        sys.exit(0)


if __name__ == "__main__":
    main()
