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
    assert t._pipeline_state == "loading"
    t.sgk_set_state("paused")
    assert t._pipeline_state == "loading"
    t.sgk_set_state("processing")
    assert t._pipeline_state == "processing"


def test_starts_in_loading_state_until_told_otherwise(qapp) -> None:
    t = _tray()
    assert t._effective_state() == "loading"
    t.sgk_set_state("idle")
    assert t._effective_state() == "idle"


def test_setters_emit_through_the_bridge_after_create(qapp) -> None:
    t = _tray()
    t.sgk_create()
    hits: list[int] = []
    t._bridge.changed.connect(lambda: hits.append(1))
    t.sgk_set_state("recording")
    t.sgk_set_sound_enabled(False)
    t.sgk_set_paused(True)
    qapp.processEvents()
    assert len(hits) == 3
    assert t._shown_key[0] == "paused" and t._shown_key[3] is False
    t.sgk_destroy()
    assert t._bridge is None


def test_create_and_destroy_do_not_raise(qapp) -> None:
    t = _tray()
    t.sgk_create()
    t.sgk_set_state("recording")
    t._sgk_reconcile()
    t.sgk_apply_ui(lang="ru", icon_style="mono")
    t.sgk_destroy()
