"""Unit tests for SgkTrayIcon state logic (Qt offscreen)."""

from __future__ import annotations

import pytest

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from sgk_voice_typer.gui.tray import SgkTrayIcon, _sgk_make_icon  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_make_icon_non_null_for_every_state(qapp) -> None:
    for state in ("idle", "recording", "processing", "paused"):
        assert not _sgk_make_icon(state, "color").isNull()
        assert not _sgk_make_icon(state, "mono").isNull()


def _tray(**kw) -> SgkTrayIcon:
    return SgkTrayIcon(
        on_pause_toggle=lambda: None,
        on_open_settings=lambda: None,
        on_quit=lambda: None,
        **kw,
    )


def test_effective_state_prefers_paused(qapp) -> None:
    t = _tray()
    t.sgk_set_state("recording")
    assert t._effective_state() == "recording"
    t.sgk_set_paused(True)
    assert t._effective_state() == "paused"
    t.sgk_set_paused(False)
    assert t._effective_state() == "recording"


def test_set_state_ignores_unknown(qapp) -> None:
    t = _tray()
    t.sgk_set_state("bogus")
    assert t._pipeline_state == "idle"
    t.sgk_set_state("processing")
    assert t._pipeline_state == "processing"


def test_paused_getter_overrides_stored_flag(qapp) -> None:
    paused = {"v": True}
    t = _tray(is_paused_getter=lambda: paused["v"])
    assert t._effective_state() == "paused"
    paused["v"] = False
    assert t._effective_state() == "idle"


def test_create_and_destroy_do_not_raise(qapp) -> None:
    t = _tray()
    t.sgk_create()
    t.sgk_set_state("recording")
    t._sgk_reconcile()
    t.sgk_apply_ui(lang="ru", icon_style="mono")
    t.sgk_destroy()
