"""On-screen "listening" indicator: a rounded pill of equaliser bars.

Frameless, always-on-top, click-through, translucent. Shown only while a
recording is in progress, at the bottom-centre of whichever screen the mouse
pointer is on. The bar heights follow the microphone RMS level, which is read
from a getter on a 33 ms render timer - no Qt object is touched off the Qt
thread (``sgk_set_listening`` just flips a flag, a 120 ms timer reconciles).
"""

from __future__ import annotations

import math
import random
from typing import Any, Callable

from sgk_voice_typer.utils.logger import sgk_get_logger

_logger = sgk_get_logger(__name__)

_BARS = 15
_W, _H = 240, 56
_BOTTOM_MARGIN = 96
_LEVEL_GAIN = 9.0          # RMS (~0.03 speech) -> 0..1 bar fill
_RENDER_MS = 33
_RECONCILE_MS = 120


class SgkListeningOverlay:
    def __init__(self, level_getter: Callable[[], float], position: str = "bottom-center") -> None:
        self._level_getter = level_getter
        self._position = position
        self._widget: Any = None
        self._render_timer: Any = None
        self._reconcile_timer: Any = None
        self._anim: Any = None
        self._want_visible = False
        self._bars = [0.0] * _BARS
        self._phase = [random.uniform(0, math.tau) for _ in range(_BARS)]

    # ------------------------------------------------------------------
    # any thread
    # ------------------------------------------------------------------

    def sgk_set_listening(self, listening: bool) -> None:
        self._want_visible = bool(listening)

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
            | Qt.WindowType.WindowTransparentForInput,
        )
        w.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        w.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        w.resize(_W, _H)
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
            from PyQt6.QtGui import QCursor, QGuiApplication

            screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
            if screen is None:
                return
            geo = screen.availableGeometry()
            x = geo.x() + (geo.width() - _W) // 2
            y = geo.y() + geo.height() - _H - _BOTTOM_MARGIN
            w.move(x, y)
        except Exception as exc:
            _logger.debug("sgk_overlay_place_failed", extra={"error": str(exc)})

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
        if self._widget is not None:
            self._widget.update()

    def _paint_event(self, _event) -> None:
        from PyQt6.QtCore import QRectF, Qt
        from PyQt6.QtGui import QColor, QPainter

        w = self._widget
        p = QPainter(w)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        p.setBrush(QColor(20, 20, 24, 205))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(0, 0, _W, _H), _H / 2, _H / 2)

        pad_x, pad_y = 22, 12
        area_w = _W - 2 * pad_x
        area_h = _H - 2 * pad_y
        bar_w = area_w / (_BARS * 2 - 1)
        p.setBrush(QColor(90, 170, 255, 235))
        for i, v in enumerate(self._bars):
            bh = max(3.0, v * area_h)
            x = pad_x + i * 2 * bar_w
            y = pad_y + (area_h - bh) / 2
            p.drawRoundedRect(QRectF(x, y, bar_w, bh), bar_w / 2, bar_w / 2)
        p.end()
