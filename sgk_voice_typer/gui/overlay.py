"""On-screen "listening" indicator: a rounded pill of equaliser bars, optionally
with a live-transcript band above them.

Frameless, always-on-top, click-through, translucent. Shown only while a
recording is in progress, at the bottom-centre of a screen chosen by
``screen`` mode: ``auto`` follows the focused window (via ``xdotool`` under
XWayland, falling back to the primary screen), ``primary`` pins it, ``pointer``
uses the screen under the mouse.

The bar heights follow the microphone RMS level, read from a getter on a 33 ms
render timer. With ``preview=True`` the widget is wider and taller, and the top
band shows the growing transcript (``sgk_set_preview``) as the pipeline
re-transcribes the audio so far - nothing is typed into the focused app until
the recording stops. No Qt object is touched off the Qt thread: the setters
just store values, a 120 ms timer reconciles visibility, the 33 ms timer paints.
"""

from __future__ import annotations

import math
import random
import shutil
import subprocess
from typing import Any, Callable

from sgk_voice_typer.utils.logger import sgk_get_logger

_logger = sgk_get_logger(__name__)

_BARS = 15
_BARS_H = 56               # height of the equaliser band
_NARROW_W = 240
_WIDE_W = 460
_PREVIEW_PAD_X = 20        # inset of the transcript text from the pill edge
_PREVIEW_PAD_Y = 12        # top + bottom inset of the transcript band
_PREVIEW_LINE_H = 20
_PREVIEW_MIN_LINES = 1
_PREVIEW_MAX_LINES = 6
_BOTTOM_MARGIN = 96
_LEVEL_GAIN = 9.0          # RMS (~0.03 speech) -> 0..1 bar fill
_RENDER_MS = 33
_RECONCILE_MS = 120


def _preview_band_h(lines: int) -> int:
    lines = max(_PREVIEW_MIN_LINES, min(_PREVIEW_MAX_LINES, lines))
    return 2 * _PREVIEW_PAD_Y + lines * _PREVIEW_LINE_H


class SgkListeningOverlay:
    def __init__(
        self,
        level_getter: Callable[[], float],
        position: str = "bottom-center",
        screen: str = "auto",
        preview: bool = False,
    ) -> None:
        self._level_getter = level_getter
        self._position = position
        self._screen_mode = screen if screen in ("auto", "primary", "pointer") else "auto"
        self._preview_enabled = preview
        self._w_px = _WIDE_W if preview else _NARROW_W
        self._h_px = (_BARS_H + _preview_band_h(_PREVIEW_MIN_LINES)) if preview else _BARS_H
        self._anchor_x = 0
        self._anchor_bottom = 0    # y of the pill's bottom edge; the pill grows upward
        self._widget: Any = None
        self._render_timer: Any = None
        self._reconcile_timer: Any = None
        self._anim: Any = None
        self._want_visible = False
        self._locked = False
        self._warned = False
        self._preview_text = ""
        self._bars = [0.0] * _BARS
        self._phase = [random.uniform(0, math.tau) for _ in range(_BARS)]

    # ------------------------------------------------------------------
    # any thread
    # ------------------------------------------------------------------

    def sgk_set_listening(self, listening: bool) -> None:
        self._want_visible = bool(listening)
        if not listening:
            self._locked = False
            self._preview_text = ""

    def sgk_set_locked(self, locked: bool) -> None:
        self._locked = bool(locked)

    def sgk_set_preview(self, text: str) -> None:
        self._preview_text = text or ""

    # ------------------------------------------------------------------
    # Qt thread
    # ------------------------------------------------------------------

    def sgk_create(self) -> None:
        try:
            from PyQt6.QtCore import Qt, QTimer
            from PyQt6.QtWidgets import QWidget
        except ImportError:
            _logger.warning("sgk_overlay_pyqt6_missing")
            return

        w = QWidget(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.X11BypassWindowManagerHint
            | Qt.WindowType.WindowTransparentForInput,
        )
        w.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        w.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        w.resize(self._w_px, self._h_px)
        w.setWindowOpacity(0.0)
        w.paintEvent = self._paint_event  # type: ignore[assignment,method-assign]
        self._widget = w

        self._render_timer = QTimer()
        self._render_timer.setInterval(_RENDER_MS)
        self._render_timer.timeout.connect(self._render_tick)

        self._reconcile_timer = QTimer()
        self._reconcile_timer.setInterval(_RECONCILE_MS)
        self._reconcile_timer.timeout.connect(self._reconcile)
        self._reconcile_timer.start()
        _logger.info("sgk_overlay_created")

    def sgk_destroy(self) -> None:
        for t in (self._render_timer, self._reconcile_timer):
            try:
                if t is not None:
                    t.stop()
            except Exception:
                pass
        if self._widget is not None:
            try:
                self._widget.hide()
            except Exception:
                pass

    # ------------------------------------------------------------------

    def _reconcile(self) -> None:
        w = self._widget
        if w is None:
            return
        visible = w.isVisible() and w.windowOpacity() > 0.01
        if self._want_visible and not visible:
            self._place(w)
            w.show()
            self._render_timer.start()
            self._fade_to(1.0)
        elif not self._want_visible and visible:
            self._fade_to(0.0, hide_after=True)

    def _place(self, w) -> None:
        try:
            from PyQt6.QtGui import QGuiApplication

            screen = self._pick_screen()
            if screen is None:
                return
            geo = screen.availableGeometry()
            if self._preview_enabled:
                self._h_px = _BARS_H + _preview_band_h(_PREVIEW_MIN_LINES)
            self._anchor_x = geo.x() + (geo.width() - self._w_px) // 2
            self._anchor_bottom = geo.y() + geo.height() - _BOTTOM_MARGIN
            y = self._anchor_bottom - self._h_px
            w.setGeometry(self._anchor_x, y, self._w_px, self._h_px)
            w.move(self._anchor_x, y)
            if QGuiApplication.platformName() == "wayland" and not self._warned:
                self._warned = True
                _logger.warning(
                    "sgk_overlay_wayland_position",
                    extra={"hint": "install libxcb-cursor0 so the overlay can sit "
                                   "bottom-centre of the right screen (GNOME "
                                   "Wayland ignores client window positions)"},
                )
        except Exception as exc:
            _logger.debug("sgk_overlay_place_failed", extra={"error": str(exc)})

    def _pick_screen(self):
        from PyQt6.QtCore import QPoint
        from PyQt6.QtGui import QCursor, QGuiApplication

        primary = QGuiApplication.primaryScreen()
        if self._screen_mode == "primary":
            return primary
        if self._screen_mode == "pointer":
            return QGuiApplication.screenAt(QCursor.pos()) or primary

        # "auto": the screen holding the focused window (XWayland only).
        centre = self._active_window_centre()
        if centre is not None:
            return QGuiApplication.screenAt(QPoint(*centre)) or primary
        return primary

    @staticmethod
    def _active_window_centre() -> tuple[int, int] | None:
        if not shutil.which("xdotool"):
            return None
        try:
            out = subprocess.run(
                ["xdotool", "getactivewindow", "getwindowgeometry", "--shell"],
                capture_output=True, text=True, timeout=0.5,
            ).stdout
        except (OSError, subprocess.SubprocessError):
            return None
        vals: dict[str, int] = {}
        for row in out.splitlines():
            k, _, v = row.partition("=")
            if v.strip().lstrip("-").isdigit():
                vals[k.strip()] = int(v)
        if {"X", "Y", "WIDTH", "HEIGHT"} <= vals.keys():
            return vals["X"] + vals["WIDTH"] // 2, vals["Y"] + vals["HEIGHT"] // 2
        return None

    def _fade_to(self, target: float, hide_after: bool = False) -> None:
        from PyQt6.QtCore import QEasingCurve, QPropertyAnimation

        w = self._widget
        anim = QPropertyAnimation(w, b"windowOpacity")
        anim.setDuration(160)
        anim.setStartValue(w.windowOpacity())
        anim.setEndValue(target)
        anim.setEasingCurve(QEasingCurve.Type.InOutQuad)

        def _done() -> None:
            if hide_after:
                w.hide()
                self._render_timer.stop()

        anim.finished.connect(_done)
        anim.start()
        self._anim = anim  # keep a ref so it isn't GC'd mid-animation

    def _render_tick(self) -> None:
        try:
            level = max(0.0, float(self._level_getter()))
        except Exception:
            level = 0.0
        fill = min(1.0, level * _LEVEL_GAIN)
        for i in range(_BARS):
            # symmetric hump so the middle bars are tallest
            centre = 1.0 - abs(i - (_BARS - 1) / 2) / ((_BARS - 1) / 2)
            self._phase[i] += 0.35
            wobble = 0.12 + 0.10 * math.sin(self._phase[i])
            target = 0.06 + fill * (0.35 + 0.65 * centre) + fill * wobble
            self._bars[i] += (min(1.0, target) - self._bars[i]) * 0.4
        if self._preview_enabled:
            self._grow_to_fit_preview()
        if self._widget is not None:
            self._widget.update()

    def _grow_to_fit_preview(self) -> None:
        """Resize the pill so it holds the wrapped transcript, growing upward."""
        w = self._widget
        if w is None:
            return
        from PyQt6.QtCore import QRect
        from PyQt6.QtGui import QFont, QFontMetrics

        text = self._preview_text.strip()
        lines = _PREVIEW_MIN_LINES
        if text:
            font = QFont()
            font.setPointSize(10)
            avail = self._w_px - 2 * _PREVIEW_PAD_X
            rect = QFontMetrics(font).boundingRect(
                QRect(0, 0, avail, 10_000),
                int(0x1000 | 0x0004),  # TextWordWrap | AlignLeft
                text,
            )
            lines = max(1, -(-rect.height() // _PREVIEW_LINE_H))  # ceil
        want_h = _BARS_H + _preview_band_h(lines)
        if want_h != self._h_px and self._anchor_bottom:
            self._h_px = want_h
            y = self._anchor_bottom - want_h
            w.setGeometry(self._anchor_x, y, self._w_px, want_h)

    def _paint_event(self, _event) -> None:
        from PyQt6.QtCore import QRectF, Qt
        from PyQt6.QtGui import QColor, QFont, QPainter

        w = self._widget
        wpx, hpx = self._w_px, self._h_px
        bars_top = hpx - _BARS_H

        p = QPainter(w)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(20, 20, 24, 210))
        radius = min(_BARS_H, hpx) / 2
        p.drawRoundedRect(QRectF(0, 0, wpx, hpx), radius, radius)

        # --- live transcript band (fills everything above the equaliser) ---
        if self._preview_enabled and bars_top > 0:
            band = QRectF(
                _PREVIEW_PAD_X, _PREVIEW_PAD_Y,
                wpx - 2 * _PREVIEW_PAD_X, bars_top - _PREVIEW_PAD_Y,
            )
            font = QFont()
            font.setPointSize(10)
            p.setFont(font)
            text = self._preview_text.strip()
            flags = int(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom
                | Qt.TextFlag.TextWordWrap
            )
            if text:
                p.setPen(QColor(232, 236, 245, 245))
                p.drawText(band, flags, text)
            else:
                p.setPen(QColor(150, 155, 165, 180))
                p.drawText(band, flags, "…")
            p.setPen(Qt.PenStyle.NoPen)

        # --- equaliser ---
        pad_x, pad_y = 22, 12
        lock_w = 24 if self._locked else 0
        area_w = wpx - 2 * pad_x - lock_w
        area_h = _BARS_H - 2 * pad_y
        bar_w = area_w / (_BARS * 2 - 1)
        p.setBrush(QColor(90, 170, 255, 235))
        for i, v in enumerate(self._bars):
            bh = max(3.0, v * area_h)
            x = pad_x + i * 2 * bar_w
            y = bars_top + pad_y + (area_h - bh) / 2
            p.drawRoundedRect(QRectF(x, y, bar_w, bh), bar_w / 2, bar_w / 2)

        if self._locked:
            self._draw_lock(p, QColor(255, 210, 120, 245), wpx, bars_top + _BARS_H / 2)
        p.end()

    def _draw_lock(self, p, color, cx: float, cy: float) -> None:
        from PyQt6.QtCore import QRectF, Qt
        from PyQt6.QtGui import QPen

        cx = cx - 22
        body = QRectF(cx - 7, cy - 1, 14, 11)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawRoundedRect(body, 2, 2)
        pen = QPen(color)
        pen.setWidth(2)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(QRectF(cx - 5, cy - 9, 10, 12), 0, 180 * 16)
