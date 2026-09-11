"""System tray icon for VoiceTyper (PyQt6 QSystemTrayIcon).

Four visual states: idle, recording, transcribing (processing), paused. The
pipeline reports idle/recording/processing from the asyncio thread and the
enable/disable toggle sets paused from anywhere; both just store a value and a
250 ms QTimer on the Qt thread reconciles the icon and tooltip, so no Qt object
is ever touched off the Qt thread.

Menu: Enabled/Paused toggle (also on left-click), Settings..., About, Quit.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from sgk_voice_typer import SGK_DONATE_URL, SGK_GITHUB_URL, __author__, __version__
from sgk_voice_typer.gui.i18n import sgk_normalize_lang, sgk_tr
from sgk_voice_typer.utils.logger import sgk_get_logger

_logger = sgk_get_logger(__name__)

_ICON = Path(__file__).parent / "icon.png"

# state -> (overlay colour or None, opacity)
_STATE_TINT = {
    "idle": (None, 1.0),
    "recording": ("#e53935", 1.0),
    "processing": ("#fb8c00", 1.0),
    "paused": ("#808080", 0.4),
}


def _sgk_panel_fg():
    from PyQt6.QtGui import QColor, QPalette
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is not None:
        win = app.palette().color(QPalette.ColorRole.Window)
        return QColor("#f5f5f5") if win.lightnessF() < 0.5 else QColor("#2b2b2b")
    return QColor("#f5f5f5")


def _sgk_about_colors():
    """(*background*, *text*, *muted*) for the About dialog.

    Background and text come from the same light/dark decision so they always
    contrast, even when the desktop hands Qt an inconsistent palette (dark
    window colour but dark default text, a known GNOME/Qt6 bug).
    """
    from PyQt6.QtGui import QColor, QPalette
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    win = app.palette().color(QPalette.ColorRole.Window) if app is not None else QColor("#2b2b2b")
    if win.lightnessF() < 0.5:
        return QColor("#2b2b2b"), QColor("#f5f5f5"), QColor("#b3b3b3")
    return QColor("#f7f7f7"), QColor("#1e1e1e"), QColor("#6a6a6a")


def _sgk_make_icon(state: str, style: str = "color"):
    from PyQt6.QtGui import QColor, QIcon, QPainter, QPixmap

    tint, opacity = _STATE_TINT.get(state, (None, 1.0))

    if _ICON.exists():
        base = QPixmap(str(_ICON))
        if not base.isNull():
            out = QPixmap(base.size())
            out.fill(QColor(0, 0, 0, 0))
            p = QPainter(out)
            p.setOpacity(opacity)
            p.drawPixmap(0, 0, base)
            p.setOpacity(1.0)
            fill = None
            if style == "mono":
                fill = _sgk_panel_fg()
            elif tint is not None:
                fill = QColor(tint)
            if fill is not None:
                p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
                p.fillRect(out.rect(), fill)
            p.end()
            return QIcon(out)

    pm = QPixmap(16, 16)
    pm.fill(QColor(tint or "#4A90D9"))
    return QIcon(pm)


def _sgk_theme_icon(name: str):
    from PyQt6.QtGui import QIcon

    for cand in (f"{name}-symbolic", name):
        icon = QIcon.fromTheme(cand)
        if not icon.isNull():
            return icon
    return QIcon()


class SgkTrayIcon:
    def __init__(
        self,
        on_pause_toggle: Callable[[], None],
        on_open_settings: Callable[[], None],
        on_quit: Callable[[], None],
        is_paused_getter: Callable[[], bool] | None = None,
        lang: str = "en",
        icon_style: str = "color",
        on_sound_toggle: Callable[[], None] | None = None,
        is_sound_enabled_getter: Callable[[], bool] | None = None,
    ) -> None:
        self._on_pause_toggle = on_pause_toggle
        self._on_open_settings = on_open_settings
        self._on_quit = on_quit
        self._is_paused_getter = is_paused_getter
        self._lang = sgk_normalize_lang(lang)
        self._icon_style = icon_style if icon_style in ("color", "mono") else "color"
        self._on_sound_toggle = on_sound_toggle
        self._is_sound_enabled_getter = is_sound_enabled_getter

        self._tray: Any = None
        self._menu: Any = None
        self._pause_action: Any = None
        self._sound_action: Any = None
        self._settings_action: Any = None
        self._about_action: Any = None
        self._quit_action: Any = None
        self._timer: Any = None

        self._pipeline_state = "idle"   # set from the asyncio thread
        self._paused = False            # set from anywhere
        self._sound_enabled = True      # mirrored from the getter each reconcile
        self._shown_key: Any = None     # (effective_state, style, lang, sound) last painted

    # ------------------------------------------------------------------
    # public - safe to call from any thread
    # ------------------------------------------------------------------

    def sgk_set_state(self, state: str) -> None:
        if state in ("idle", "recording", "processing"):
            self._pipeline_state = state

    def sgk_set_paused(self, paused: bool) -> None:
        self._paused = bool(paused)

    # ------------------------------------------------------------------
    # Qt thread only
    # ------------------------------------------------------------------

    def sgk_create(self) -> None:
        try:
            from PyQt6.QtCore import QTimer
            from PyQt6.QtWidgets import QMenu, QSystemTrayIcon
        except ImportError:
            _logger.warning("sgk_tray_pyqt6_missing")
            return

        self._tray = QSystemTrayIcon()

        def _activated(reason) -> None:
            if reason == QSystemTrayIcon.ActivationReason.Trigger:
                self._on_pause_toggle()

        self._tray.activated.connect(_activated)

        self._menu = QMenu()
        self._pause_action = self._menu.addAction("")
        self._pause_action.setCheckable(True)
        self._pause_action.triggered.connect(lambda _checked: self._on_pause_toggle())
        self._sound_action = self._menu.addAction("")
        self._sound_action.setCheckable(True)
        self._sound_action.triggered.connect(self._sgk_on_sound_toggled)
        self._menu.addSeparator()
        self._settings_action = self._menu.addAction("")
        self._settings_action.setIcon(_sgk_theme_icon("preferences-system"))
        self._settings_action.triggered.connect(self._on_open_settings)
        self._about_action = self._menu.addAction("")
        self._about_action.setIcon(_sgk_theme_icon("help-about"))
        self._about_action.triggered.connect(self._sgk_show_about)
        self._menu.addSeparator()
        self._quit_action = self._menu.addAction("")
        self._quit_action.setIcon(_sgk_theme_icon("application-exit"))
        self._quit_action.triggered.connect(self._on_quit)
        self._tray.setContextMenu(self._menu)

        self._sgk_reconcile(force=True)
        self._tray.show()

        self._timer = QTimer()
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._sgk_reconcile)
        self._timer.start()
        _logger.info("sgk_tray_created")

    def sgk_apply_ui(self, lang: str | None = None, icon_style: str | None = None) -> None:
        if lang is not None:
            self._lang = sgk_normalize_lang(lang)
        if icon_style in ("color", "mono"):
            self._icon_style = icon_style
        self._sgk_reconcile(force=True)

    def sgk_destroy(self) -> None:
        if self._timer is not None:
            try:
                self._timer.stop()
            except Exception:
                pass
        if self._tray is not None:
            try:
                self._tray.hide()
            except Exception:
                pass

    # ------------------------------------------------------------------

    def _effective_state(self) -> str:
        if self._is_paused_getter is not None:
            try:
                self._paused = bool(self._is_paused_getter())
            except Exception:
                pass
        return "paused" if self._paused else self._pipeline_state

    def _sgk_on_sound_toggled(self, _checked: bool) -> None:
        if self._on_sound_toggle is not None:
            self._on_sound_toggle()

    def _sgk_reconcile(self, force: bool = False) -> None:
        if self._tray is None:
            return
        state = self._effective_state()
        if self._is_sound_enabled_getter is not None:
            try:
                self._sound_enabled = bool(self._is_sound_enabled_getter())
            except Exception:
                pass
        key = (state, self._icon_style, self._lang, self._sound_enabled)
        if key == self._shown_key and not force:
            return
        self._shown_key = key

        self._tray.setIcon(_sgk_make_icon(state, self._icon_style))
        self._tray.setToolTip(sgk_tr(f"tray.tip.{state}", self._lang))
        if self._pause_action is not None:
            self._pause_action.setChecked(state != "paused")
            self._pause_action.setText(
                sgk_tr("tray.paused" if state == "paused" else "tray.enabled", self._lang)
            )
            if self._sound_action is not None:
                self._sound_action.setChecked(self._sound_enabled)
                self._sound_action.setText(sgk_tr("tray.sound", self._lang))
            self._settings_action.setText(sgk_tr("tray.settings", self._lang))
            self._about_action.setText(sgk_tr("tray.about", self._lang))
            self._quit_action.setText(sgk_tr("tray.quit", self._lang))

    def _sgk_show_about(self) -> None:
        try:
            from PyQt6.QtCore import Qt, QUrl
            from PyQt6.QtGui import QDesktopServices, QPixmap
            from PyQt6.QtWidgets import (
                QDialog,
                QHBoxLayout,
                QLabel,
                QPushButton,
                QVBoxLayout,
            )
        except ImportError:
            return

        lang = self._lang
        center = Qt.AlignmentFlag.AlignCenter
        dlg = QDialog()
        dlg.setWindowTitle(sgk_tr("about.title", lang))
        dlg.setMinimumWidth(360)

        bg, fg, muted = _sgk_about_colors()
        dlg.setStyleSheet(
            f"QDialog {{ background-color: {bg.name()}; }}"
            f"QLabel {{ color: {fg.name()}; background: transparent; }}"
            f"QPushButton {{ color: {fg.name()}; background-color: {bg.name()}; "
            f"border: 1px solid {muted.name()}; border-radius: 4px; "
            f"padding: 4px 12px; }}"
            f"QPushButton:hover {{ border-color: {fg.name()}; }}"
        )

        layout = QVBoxLayout(dlg)
        layout.setSpacing(6)
        layout.setContentsMargins(24, 20, 24, 16)

        if _ICON.exists():
            logo = QLabel()
            logo.setPixmap(
                QPixmap(str(_ICON)).scaled(
                    96, 96,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            logo.setAlignment(center)
            layout.addWidget(logo)

        title = QLabel("<b>VoiceTyper</b>")
        title.setStyleSheet(f"font-size: 16px; color: {fg.name()};")
        title.setAlignment(center)
        layout.addWidget(title)

        tagline = QLabel(sgk_tr("about.tagline", lang))
        tagline.setWordWrap(True)
        tagline.setAlignment(center)
        layout.addWidget(tagline)

        meta = QLabel(
            f"{sgk_tr('about.version', lang)} {__version__}  ·  "
            f"{sgk_tr('about.author', lang)}: {__author__}<br>"
            f"{sgk_tr('about.license', lang)}: GPL-3.0-or-later"
        )
        meta.setAlignment(center)
        meta.setStyleSheet(f"color: {muted.name()};")
        layout.addWidget(meta)

        thanks = QLabel(sgk_tr("about.thanks", lang))
        thanks.setWordWrap(True)
        thanks.setAlignment(center)
        thanks.setStyleSheet(f"color: {muted.name()};")
        layout.addWidget(thanks)

        layout.addSpacing(4)
        links = QHBoxLayout()
        links.setAlignment(center)
        star = QPushButton(sgk_tr("about.star", lang))
        star.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(SGK_GITHUB_URL)))
        donate = QPushButton(sgk_tr("about.donate", lang))
        donate.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(SGK_DONATE_URL)))
        links.addWidget(star)
        links.addWidget(donate)
        layout.addLayout(links)

        signature = QLabel("Developed by SGK with ❤️")
        signature.setAlignment(center)
        signature.setStyleSheet(f"color: {muted.name()};")
        layout.addWidget(signature)

        dlg.exec()
