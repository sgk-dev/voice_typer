"""Unit tests for SgkListeningOverlay (Qt offscreen)."""

from __future__ import annotations

import pytest

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from sgk_voice_typer.gui.overlay import _BARS, SgkListeningOverlay  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_set_listening_is_thread_safe_flag_only(qapp) -> None:
    ov = SgkListeningOverlay(level_getter=lambda: 0.0)
    assert ov._want_visible is False
    ov.sgk_set_listening(True)
    assert ov._want_visible is True
    ov.sgk_set_listening(False)
    assert ov._want_visible is False


def test_create_reconcile_render_destroy_do_not_raise(qapp) -> None:
    level = {"v": 0.0}
    ov = SgkListeningOverlay(level_getter=lambda: level["v"])
    ov.sgk_create()
    ov.sgk_set_listening(True)
    ov._reconcile()
    level["v"] = 0.05
    for _ in range(10):
        ov._render_tick()
    assert len(ov._bars) == _BARS
    assert any(b > 0.0 for b in ov._bars)  # bars responded to level
    ov.sgk_set_listening(False)
    ov._reconcile()
    ov.sgk_destroy()


def test_render_tick_survives_getter_exception(qapp) -> None:
    def _boom() -> float:
        raise RuntimeError("recorder gone")

    ov = SgkListeningOverlay(level_getter=_boom)
    ov.sgk_create()
    ov._render_tick()  # must not raise
    ov.sgk_destroy()
