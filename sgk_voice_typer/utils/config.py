"""Configuration management for sgk-voice-typer.

Config file: ~/.config/sgk-voice-typer/config.json

Loaded once at startup and written back by the settings dialog. Unknown keys in
the user's file are kept; missing keys are filled from the defaults below via a
deep merge, so a config written by an older version keeps working.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from sgk_voice_typer.utils.logger import sgk_get_logger

_logger = sgk_get_logger(__name__)

_SGK_DEFAULT_CONFIG: dict[str, Any] = {
    "version": "1.0",
    "ui": {
        "language": "en",              # "en" | "ru"
        "tray_icon_style": "color",    # "color" | "mono"
    },
    "hotkeys": {
        "ptt": "f9",                   # hold to record, release to type
        "ptt_terminal": "shift+f9",    # same, pastes with Ctrl+Shift+V
        "toggle": "ctrl+pause",        # enable / disable the daemon
    },
    "model": {
        "name": "large-v3-turbo",
        "device": "cuda",             # "cuda" | "cpu"
        "compute_type": "float16",
        "language": "auto",           # "auto" or an ISO code like "ru" / "en"
        "beam_size": 5,
    },
    "audio": {
        "device": None,               # sounddevice name or index; None = system default
        "sample_rate": 16000,
    },
    "behavior": {
        "enabled_on_start": True,
        "min_duration_s": 0.3,        # shorter clips are dropped (stray key taps)
        "max_duration_s": 60.0,       # hard cap against a stuck key
        "no_speech_threshold": 0.5,   # skip typing if Whisper is this unsure speech occurred
        "clipboard_settle_ms": 150,
        "paste_settle_ms": 400,
        "restore_clipboard": True,
    },
    "feedback": {
        "sound_enabled": True,
        "sound_volume": 0.25,         # 0.0 - 1.0
        "overlay_enabled": True,
        "overlay_position": "bottom-center",   # currently the only value
    },
    "logging": {
        "level": "INFO",
        "file": "~/.local/share/sgk-voice-typer/voice_typer.log",
        "format": "json",
        "max_bytes": 5_242_880,       # 5 MB
        "backup_count": 3,
    },
}


class SgkConfig:
    CONFIG_PATH = Path.home() / ".config" / "sgk-voice-typer" / "config.json"

    def __init__(self, config_path: Path | None = None) -> None:
        self._path = config_path or self.CONFIG_PATH
        self._data: dict[str, Any] = {}

    def sgk_load(self) -> dict[str, Any]:
        """Load config from disk. Falls back to defaults on any error."""
        if not self._path.exists():
            _logger.info("sgk_config_not_found", extra={"path": str(self._path)})
            self._data = self.sgk_get_default()
            self.sgk_save(self._data)
            return self._data

        try:
            with self._path.open("r", encoding="utf-8") as f:
                loaded = json.load(f)
            self._data = self._sgk_merge_defaults(loaded)
            _logger.info("sgk_config_loaded", extra={"path": str(self._path)})
        except (json.JSONDecodeError, OSError) as exc:
            _logger.warning(
                "sgk_config_load_failed",
                extra={"path": str(self._path), "error": str(exc)},
            )
            self._data = self.sgk_get_default()

        return self._data

    def sgk_save(self, data: dict[str, Any] | None = None) -> None:
        """Save config to disk."""
        if data is not None:
            self._data = data
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
            _logger.debug("sgk_config_saved", extra={"path": str(self._path)})
        except OSError as exc:
            _logger.error(
                "sgk_config_save_failed",
                extra={"path": str(self._path), "error": str(exc)},
            )

    def sgk_get(self, *keys: str, default: Any = None) -> Any:
        """Nested key access: sgk_get('behavior', 'min_duration_s')."""
        node: Any = self._data
        for key in keys:
            if not isinstance(node, dict):
                return default
            node = node.get(key, default)
        return node

    def sgk_set(self, *keys: str, value: Any) -> None:
        """Set a nested key and persist."""
        node = self._data
        for key in keys[:-1]:
            node = node.setdefault(key, {})
        node[keys[-1]] = value
        self.sgk_save()

    @staticmethod
    def sgk_get_default() -> dict[str, Any]:
        return copy.deepcopy(_SGK_DEFAULT_CONFIG)

    def _sgk_merge_defaults(self, loaded: dict[str, Any]) -> dict[str, Any]:
        """Deep-merge loaded config onto the defaults (defaults fill gaps)."""
        result = copy.deepcopy(_SGK_DEFAULT_CONFIG)
        _sgk_deep_merge(result, loaded)
        return result

    @property
    def data(self) -> dict[str, Any]:
        return self._data


def _sgk_deep_merge(base: dict[str, Any], override: dict[str, Any]) -> None:
    """Merge ``override`` into ``base`` in place (recursive)."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _sgk_deep_merge(base[key], value)
        else:
            base[key] = value
