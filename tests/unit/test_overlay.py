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


def _overlay(getter=lambda: 0.0, preview=False) -> SgkListeningOverlay:
    # screen="primary" keeps the tests off xdotool
    return SgkListeningOverlay(level_getter=getter, screen="primary", preview=preview)


def test_set_listening_is_thread_safe_flag_only(qapp) -> None:
    ov = _overlay()
    assert ov._want_visible is False
    ov.sgk_set_listening(True)
    assert ov._want_visible is True
    ov.sgk_set_listening(False)
    assert ov._want_visible is False


def test_create_reconcile_render_destroy_do_not_raise(qapp) -> None:
    level = {"v": 0.0}
    ov = _overlay(lambda: level["v"])
    ov.sgk_create()
    ov.sgk_set_listening(True)
    ov._reconcile()
    level["v"] = 0.05
    for _ in range(10):
        ov._render_tick()
    assert len(ov._bars) == _BARS
    assert any(b > 0.0 for b in ov._bars)
    ov.sgk_set_listening(False)
    ov._reconcile()
    ov.sgk_destroy()


def test_lock_flag_and_paint_do_not_raise(qapp) -> None:
    ov = _overlay(lambda: 0.03)
    ov.sgk_create()
    ov.sgk_set_listening(True)
    ov.sgk_set_locked(True)
    assert ov._locked is True
    for _ in range(3):
        ov._render_tick()
    ov.sgk_set_listening(False)
    assert ov._locked is False
    ov.sgk_destroy()


def test_preview_widget_is_wider_and_taller(qapp) -> None:
    narrow = _overlay(preview=False)
    wide = _overlay(preview=True)
    assert wide._w_px > narrow._w_px
    assert wide._h_px > narrow._h_px


def test_preview_pill_grows_with_text(qapp) -> None:
    ov = _overlay(lambda: 0.02, preview=True)
    ov.sgk_create()
    ov._anchor_x, ov._anchor_bottom = 100, 900
    ov.sgk_set_listening(True)
    short_h = ov._h_px
    ov.sgk_set_preview("one two " * 60)   # many words -> several wrapped lines
    ov._grow_to_fit_preview()
    assert ov._h_px > short_h
    ov.sgk_set_preview("")
    ov._grow_to_fit_preview()
    assert ov._h_px == short_h            # shrinks back
    ov.sgk_destroy()


def test_preview_text_set_and_cleared_on_stop(qapp) -> None:
    ov = _overlay(preview=True)
    ov.sgk_create()
    ov.sgk_set_listening(True)
    ov.sgk_set_preview("привет как дела")
    assert ov._preview_text == "привет как дела"
    for _ in range(3):
        ov._render_tick()          # paints the transcript band, must not raise
    ov.sgk_set_listening(False)
    assert ov._preview_text == ""  # cleared when the recording ends
    ov.sgk_destroy()


def test_render_tick_survives_getter_exception(qapp) -> None:
    def _boom() -> float:
        raise RuntimeError("recorder gone")

    ov = _overlay(_boom)
    ov.sgk_create()
    ov._render_tick()
    ov.sgk_destroy()


def test_screen_mode_normalised() -> None:
    assert SgkListeningOverlay(lambda: 0.0, screen="bogus")._screen_mode == "auto"
    assert SgkListeningOverlay(lambda: 0.0, screen="pointer")._screen_mode == "pointer"


class TestActiveWindowCentre:
    def test_parses_xdotool_shell_output(self, monkeypatch: pytest.MonkeyPatch) -> None:

        from sgk_voice_typer.gui import overlay as mod

        class _R:
            stdout = "WINDOW=123\nX=46\nY=0\nWIDTH=1874\nHEIGHT=1080\nSCREEN=0\n"

        monkeypatch.setattr(mod.shutil, "which", lambda _n: "/usr/bin/xdotool")
        monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: _R())
        assert SgkListeningOverlay._active_window_centre() == (46 + 937, 540)

    def test_none_when_xdotool_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from sgk_voice_typer.gui import overlay as mod

        monkeypatch.setattr(mod.shutil, "which", lambda _n: None)
        assert SgkListeningOverlay._active_window_centre() is None
