"""Unit tests for SgkConfigDialog value collection (Qt offscreen)."""

from __future__ import annotations

import pytest

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtWidgets import QApplication, QDialog  # noqa: E402

from sgk_voice_typer.gui.config_dialog import SgkConfigDialog, _sgk_input_devices  # noqa: E402
from sgk_voice_typer.utils.config import SgkConfig  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _no_autostart_writes(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "sgk_voice_typer.gui.config_dialog.sgk_set_autostart", lambda enabled: enabled
    )
    monkeypatch.setattr(
        "sgk_voice_typer.gui.config_dialog.sgk_is_autostart_enabled", lambda: False
    )


def test_collect_roundtrips_defaults(qapp) -> None:
    cfg = SgkConfig.sgk_get_default()
    saved: list = []
    d = SgkConfigDialog(cfg, on_save=saved.append)
    dlg = QDialog()
    d._sgk_build(dlg)
    out = d._sgk_collect()

    assert out["hotkeys"]["ptt"] == "f9"
    assert out["model"]["name"] == "large-v3-turbo"
    assert out["audio"]["device"] is None
    assert out["behavior"]["clipboard_settle_ms"] == out["behavior"]["paste_settle_ms"]
    assert out["behavior"]["lock_hold_s"] == pytest.approx(3.0)


def test_lock_toggle_and_delay(qapp) -> None:
    d = SgkConfigDialog(SgkConfig.sgk_get_default(), on_save=lambda _c: None)
    dlg = QDialog()
    d._sgk_build(dlg)

    d._w["lock_on"].setChecked(True)
    d._w["lock_s"].setValue(5.5)
    assert d._sgk_collect()["behavior"]["lock_hold_s"] == pytest.approx(5.5)

    d._w["lock_on"].setChecked(False)
    assert d._w["lock_s"].isEnabled() is False           # greyed out when off
    assert d._sgk_collect()["behavior"]["lock_hold_s"] == 0.0

    # a config that had the lock disabled loads with the box unchecked
    cfg = SgkConfig.sgk_get_default()
    cfg["behavior"]["lock_hold_s"] = 0.0
    d2 = SgkConfigDialog(cfg, on_save=lambda _c: None)
    dlg2 = QDialog()
    d2._sgk_build(dlg2)
    assert d2._w["lock_on"].isChecked() is False


def test_edited_values_are_collected(qapp) -> None:
    cfg = SgkConfig.sgk_get_default()
    d = SgkConfigDialog(cfg, on_save=lambda _c: None)
    dlg = QDialog()
    d._sgk_build(dlg)

    d._w["ptt"].setText("f8")
    d._w["device"].setCurrentText("cpu")
    d._w["nsp"].setValue(0.7)
    d._w["restore"].setChecked(False)
    d._w["settle"].setValue(120)

    out = d._sgk_collect()
    assert out["hotkeys"]["ptt"] == "f8"
    assert out["model"]["device"] == "cpu"
    assert out["behavior"]["no_speech_threshold"] == pytest.approx(0.7)
    assert out["behavior"]["restore_clipboard"] is False
    assert out["behavior"]["clipboard_settle_ms"] == 120
    assert out["behavior"]["paste_settle_ms"] == 120


def test_ui_changed_fires_only_on_ui_diff(qapp) -> None:
    cfg = SgkConfig.sgk_get_default()
    ui_calls: list = []
    d = SgkConfigDialog(cfg, on_save=lambda _c: None, on_ui_changed=lambda lang, style: ui_calls.append((lang, style)))
    dlg = QDialog()
    d._sgk_build(dlg)
    d._sgk_apply()
    assert ui_calls == []  # nothing changed

    d._w["mono"].setChecked(True)
    d._sgk_apply()
    assert ui_calls == [("en", "mono")]


def test_sound_preview_plays_regardless_of_checkbox(qapp, monkeypatch: pytest.MonkeyPatch) -> None:
    from sgk_voice_typer.feedback.cues import SgkSoundCues

    calls: list = []
    monkeypatch.setattr(SgkSoundCues, "play_start", lambda self: calls.append("start"))
    monkeypatch.setattr(SgkSoundCues, "play_stop", lambda self: calls.append("stop"))

    d = SgkConfigDialog(SgkConfig.sgk_get_default(), on_save=lambda _c: None)
    dlg = QDialog()
    d._sgk_build(dlg)

    d._w["sound_on"].setChecked(False)  # preview must not depend on this
    d._sgk_play_preview(0.1, "bright")
    assert "start" in calls


def test_sound_style_roundtrips_and_lists_all_presets(qapp) -> None:
    from sgk_voice_typer.feedback.cues import SGK_SOUND_STYLES

    cfg = SgkConfig.sgk_get_default()
    cfg["feedback"]["sound_style"] = "deep"
    d = SgkConfigDialog(cfg, on_save=lambda _c: None)
    dlg = QDialog()
    d._sgk_build(dlg)

    assert d._w["sound_style"].count() == len(SGK_SOUND_STYLES)
    assert d._w["sound_style"].currentData() == "deep"

    d._w["sound_style"].setCurrentIndex(0)
    assert d._sgk_collect()["feedback"]["sound_style"] == list(SGK_SOUND_STYLES)[0]


def test_input_devices_skip_generic_alsa_plumbing(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeSd:
        @staticmethod
        def query_devices():
            return [
                {"name": "sysdefault", "max_input_channels": 128},
                {"name": "pulse", "max_input_channels": 32},
                {"name": "2.4G Wireless headset: USB Audio (hw:3,0)", "max_input_channels": 1},
            ]

    import sys

    monkeypatch.setitem(sys.modules, "sounddevice", _FakeSd())
    devices = _sgk_input_devices()
    names = [v for _label, v in devices]
    assert "sysdefault" not in names
    assert "pulse" not in names
    assert "2.4G Wireless headset: USB Audio (hw:3,0)" in names
