"""Unit tests for SgkConfig."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sgk_voice_typer.utils.config import SgkConfig


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    return tmp_path / "config.json"


@pytest.fixture
def config(config_path: Path) -> SgkConfig:
    return SgkConfig(config_path=config_path)


class TestDefaults:
    def test_default_ptt_hotkeys(self, config: SgkConfig) -> None:
        data = config.sgk_load()
        assert data["hotkeys"]["ptt"] == "f9"
        assert data["hotkeys"]["ptt_terminal"] == "shift+f9"
        assert data["hotkeys"]["toggle"] == "ctrl+pause"

    def test_default_model(self, config: SgkConfig) -> None:
        data = config.sgk_load()
        assert data["model"]["name"] == "large-v3-turbo"
        assert data["model"]["device"] == "cuda"
        assert data["model"]["language"] == "auto"

    def test_default_audio_device_is_none(self, config: SgkConfig) -> None:
        data = config.sgk_load()
        assert data["audio"]["device"] is None
        assert data["audio"]["sample_rate"] == 16000

    def test_default_behavior(self, config: SgkConfig) -> None:
        data = config.sgk_load()
        assert data["behavior"]["enabled_on_start"] is True
        assert data["behavior"]["min_duration_s"] == pytest.approx(0.3)
        assert data["behavior"]["max_duration_s"] == pytest.approx(300.0)
        assert data["behavior"]["lock_hold_s"] == pytest.approx(3.0)

    def test_default_ui_section(self, config: SgkConfig) -> None:
        data = config.sgk_load()
        assert data["ui"]["language"] == "en"
        assert data["ui"]["tray_icon_style"] == "color"

    def test_default_logging_is_json(self, config: SgkConfig) -> None:
        data = config.sgk_load()
        assert data["logging"]["format"] == "json"
        assert data["logging"]["file"].endswith("voice_typer.log")

    def test_default_feedback(self, config: SgkConfig) -> None:
        data = config.sgk_load()
        fb = data["feedback"]
        assert fb["sound_enabled"] is True
        assert 0.0 <= fb["sound_volume"] <= 1.0
        assert fb["overlay_enabled"] is True
        assert fb["overlay_screen"] == "auto"
        assert fb["live_preview"] is True
        assert fb["preview_interval_s"] > 0


class TestLoadSave:
    def test_creates_file_on_first_load(self, config: SgkConfig, config_path: Path) -> None:
        config.sgk_load()
        assert config_path.exists()

    def test_roundtrip(self, config: SgkConfig, config_path: Path) -> None:
        data = config.sgk_load()
        data["hotkeys"]["ptt"] = "f8"
        config.sgk_save(data)

        loaded = SgkConfig(config_path=config_path).sgk_load()
        assert loaded["hotkeys"]["ptt"] == "f8"

    def test_corrupt_json_falls_back_to_defaults(self, config_path: Path) -> None:
        config_path.write_text("{not valid json", encoding="utf-8")
        data = SgkConfig(config_path=config_path).sgk_load()
        assert data["hotkeys"]["ptt"] == "f9"


class TestGetSet:
    def test_nested_get(self, config: SgkConfig) -> None:
        config.sgk_load()
        assert isinstance(config.sgk_get("behavior", "clipboard_settle_ms"), int)

    def test_get_missing_returns_default(self, config: SgkConfig) -> None:
        config.sgk_load()
        assert config.sgk_get("nope", "nope", default="x") == "x"

    def test_set_persists(self, config: SgkConfig, config_path: Path) -> None:
        config.sgk_load()
        config.sgk_set("model", "device", value="cpu")
        assert SgkConfig(config_path=config_path).sgk_load()["model"]["device"] == "cpu"


class TestMergeDefaults:
    def test_missing_keys_filled_from_defaults(self, config_path: Path) -> None:
        partial = {"version": "1.0", "hotkeys": {"ptt": "f7"}}
        config_path.write_text(json.dumps(partial), encoding="utf-8")

        data = SgkConfig(config_path=config_path).sgk_load()
        assert data["hotkeys"]["ptt"] == "f7"          # custom value kept
        assert data["hotkeys"]["ptt_terminal"] == "shift+f9"  # sibling filled
        assert "model" in data and "behavior" in data  # missing sections filled

    def test_unknown_keys_are_kept(self, config_path: Path) -> None:
        config_path.write_text(
            json.dumps({"custom_experiment": {"foo": 1}}), encoding="utf-8"
        )
        data = SgkConfig(config_path=config_path).sgk_load()
        assert data["custom_experiment"] == {"foo": 1}
