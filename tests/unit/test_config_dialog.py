"""Unit tests for SgkConfigDialog value collection (Qt offscreen)."""

from __future__ import annotations

import pytest

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtWidgets import QApplication, QDialog  # noqa: E402

from sgk_voice_typer.gui.config_dialog import SgkConfigDialog  # noqa: E402
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
