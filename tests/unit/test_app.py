"""Integration-ish test for SgkApp wiring, with heavy deps faked."""

from __future__ import annotations

import threading
import time

import pytest

from sgk_voice_typer import app as app_mod
from sgk_voice_typer.core.hotkey_manager import SgkHotkeyManager


class _FakeTranscriber:
    def __init__(self, *a, **k) -> None:
        pass

    def transcribe(self, audio):  # pragma: no cover - not exercised here
        return None


class _FakeUinput:
    def __init__(self, *a, **k) -> None:
        self.closed = False

    def sgk_is_available(self) -> bool:
        return True

    def sgk_paste(self, shift: bool = False) -> None:
        pass

    def sgk_close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _fake_heavy(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setattr(app_mod, "sgk_ensure_cuda_libs", lambda device="cuda": None)
    monkeypatch.setattr(app_mod, "SgkUinputInjector", _FakeUinput)
    monkeypatch.setattr(
        "sgk_voice_typer.asr.transcriber.SgkTranscriber", _FakeTranscriber
    )
    # a hotkey manager that never touches evdev
    monkeypatch.setattr(SgkHotkeyManager, "sgk_start", lambda self, loop: True)
    monkeypatch.setattr(SgkHotkeyManager, "sgk_stop", lambda self: None)
    # isolated config file
    from sgk_voice_typer.utils.config import SgkConfig

    monkeypatch.setattr(SgkConfig, "CONFIG_PATH", tmp_path / "config.json")
    yield


def _run_app(app: app_mod.SgkApp) -> threading.Thread:
    t = threading.Thread(target=app.sgk_start, daemon=True)
    t.start()
    time.sleep(0.4)
    return t


def test_headless_start_wires_pipeline_and_stops_clean() -> None:
    app = app_mod.SgkApp(no_gui=True)
    t = _run_app(app)
    try:
        assert app._pipeline is not None
        assert app._hotkeys is not None
        assert app._loop is not None and app._loop.is_running()
        # a press/release round-trip should not raise (transcriber returns None)
        fut = app._loop.create_task  # noqa: F841
        app._loop.call_soon_threadsafe(
            lambda: app._loop.create_task(app._pipeline.sgk_on_press(False))
        )
        time.sleep(0.1)
        app._loop.call_soon_threadsafe(
            lambda: app._loop.create_task(app._pipeline.sgk_on_release(False))
        )
        time.sleep(0.2)
    finally:
        app.sgk_stop()
        t.join(timeout=3)
        time.sleep(0.15)
    assert app._stopped is True
    assert app._uinput.closed is True
    assert not t.is_alive()


def test_enabled_on_start_false_starts_paused(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    from sgk_voice_typer.utils.config import SgkConfig

    cfg_path = SgkConfig.CONFIG_PATH
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps({"behavior": {"enabled_on_start": False}}), encoding="utf-8")

    app = app_mod.SgkApp(no_gui=True)
    t = _run_app(app)
    try:
        assert app._hotkeys is not None
        assert app._hotkeys.sgk_is_paused() is True
    finally:
        app.sgk_stop()
        t.join(timeout=3)
        time.sleep(0.15)
