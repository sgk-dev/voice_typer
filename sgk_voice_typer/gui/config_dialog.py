"""Settings dialog for VoiceTyper.

Tabbed PyQt6 QDialog: General / Model / Audio / Hotkeys / Behavior. On OK it
hands a full config dict to ``on_save``; language / tray-icon changes also go to
``on_ui_changed`` so the running tray updates immediately.
"""

from __future__ import annotations

import copy
from typing import Any, Callable

from sgk_voice_typer.gui.i18n import (
    SGK_LANGUAGE_NAMES,
    SGK_LANGUAGES,
    sgk_normalize_lang,
    sgk_tr,
)
from sgk_voice_typer.utils.autostart import sgk_is_autostart_enabled, sgk_set_autostart
from sgk_voice_typer.utils.logger import sgk_get_logger

_logger = sgk_get_logger(__name__)

_MODEL_PRESETS = ["large-v3-turbo", "large-v3", "medium", "small", "base"]
_DEVICES = ["cuda", "cpu"]
_COMPUTE_TYPES = ["float16", "int8_float16", "int8", "float32"]
_REC_LANGS = ["auto", "ru", "en", "uk", "de", "fr", "es", "pl", "it"]


def _sgk_input_devices() -> list[tuple[str, object]]:
    """(label, value) pairs; value None means system default."""
    devices: list[tuple[str, object]] = [(sgk_tr("cfg.audio.default"), None)]
    try:
        import sounddevice as sd

        for idx, dev in enumerate(sd.query_devices()):
            if dev.get("max_input_channels", 0) > 0:
                devices.append((f"{dev['name']}", dev["name"]))
    except Exception as exc:  # no PortAudio, no devices - just offer the default
        _logger.debug("sgk_audio_enumerate_failed", extra={"error": str(exc)})
    return devices


class SgkConfigDialog:
    def __init__(
        self,
        config_data: dict[str, Any],
        on_save: Callable[[dict[str, Any]], None],
        on_ui_changed: Callable[[str, str], None] | None = None,
    ) -> None:
        self._config = config_data
        self._on_save = on_save
        self._on_ui_changed = on_ui_changed
        self._lang = sgk_normalize_lang(config_data.get("ui", {}).get("language", "en"))
        self._w: dict[str, Any] = {}

    def _tr(self, key: str) -> str:
        return sgk_tr(key, self._lang)

    def sgk_show(self) -> None:
        try:
            self._sgk_build_and_exec()
        except ImportError:
            _logger.warning("sgk_dialog_pyqt6_missing")
        except Exception as exc:
            _logger.error("sgk_dialog_error", extra={"error": str(exc)})

    # ------------------------------------------------------------------

    def _sgk_build_and_exec(self) -> None:
        from PyQt6.QtWidgets import QDialog

        dlg = QDialog()
        self._sgk_build(dlg)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._sgk_apply()

    def _sgk_build(self, dlg) -> None:
        """Populate ``dlg`` with the tabs and fill ``self._w``. No exec()."""
        from PyQt6.QtWidgets import (
            QCheckBox,
            QComboBox,
            QDialogButtonBox,
            QDoubleSpinBox,
            QFormLayout,
            QLabel,
            QLineEdit,
            QSpinBox,
            QTabWidget,
            QVBoxLayout,
            QWidget,
        )

        cfg = self._config
        ui = cfg.get("ui", {})
        model = cfg.get("model", {})
        audio = cfg.get("audio", {})
        hotkeys = cfg.get("hotkeys", {})
        beh = cfg.get("behavior", {})
        fb = cfg.get("feedback", {})

        dlg.setWindowTitle(self._tr("cfg.title"))
        dlg.setMinimumWidth(420)
        root = QVBoxLayout(dlg)
        tabs = QTabWidget()
        root.addWidget(tabs)

        def _combo(items: list[str], current: str, editable: bool = False) -> QComboBox:
            c = QComboBox()
            c.addItems(items)
            c.setEditable(editable)
            if current in items:
                c.setCurrentText(current)
            elif editable:
                c.setCurrentText(current)
            return c

        # ---- General ----
        g = QWidget()
        gf = QFormLayout(g)
        lang_combo = QComboBox()
        for code in SGK_LANGUAGES:
            lang_combo.addItem(SGK_LANGUAGE_NAMES[code], code)
        lang_combo.setCurrentIndex(max(0, list(SGK_LANGUAGES).index(self._lang)))
        mono = QCheckBox()
        mono.setChecked(ui.get("tray_icon_style", "color") == "mono")
        autostart = QCheckBox()
        autostart.setChecked(sgk_is_autostart_enabled())
        gf.addRow(self._tr("cfg.general.language"), lang_combo)
        gf.addRow(self._tr("cfg.general.mono"), mono)
        gf.addRow(self._tr("cfg.general.autostart"), autostart)
        tabs.addTab(g, self._tr("cfg.tab.general"))
        self._w.update(lang=lang_combo, mono=mono, autostart=autostart)

        # ---- Model ----
        m = QWidget()
        mf = QFormLayout(m)
        name_c = _combo(_MODEL_PRESETS, model.get("name", "large-v3-turbo"), editable=True)
        dev_c = _combo(_DEVICES, model.get("device", "cuda"))
        comp_c = _combo(_COMPUTE_TYPES, model.get("compute_type", "float16"))
        reclang_c = _combo(_REC_LANGS, model.get("language", "auto"), editable=True)
        mf.addRow(self._tr("cfg.model.name"), name_c)
        mf.addRow(self._tr("cfg.model.device"), dev_c)
        mf.addRow(self._tr("cfg.model.compute"), comp_c)
        mf.addRow(self._tr("cfg.model.language"), reclang_c)
        tabs.addTab(m, self._tr("cfg.tab.model"))
        self._w.update(name=name_c, device=dev_c, compute=comp_c, reclang=reclang_c)

        # ---- Audio ----
        a = QWidget()
        af = QFormLayout(a)
        mic_c = QComboBox()
        self._mic_values: list[object] = []
        for label, value in _sgk_input_devices():
            mic_c.addItem(label)
            self._mic_values.append(value)
        cur_dev = audio.get("device")
        if cur_dev in self._mic_values:
            mic_c.setCurrentIndex(self._mic_values.index(cur_dev))
        af.addRow(self._tr("cfg.audio.device"), mic_c)
        tabs.addTab(a, self._tr("cfg.tab.audio"))
        self._w.update(mic=mic_c)

        # ---- Hotkeys ----
        h = QWidget()
        hf = QFormLayout(h)
        ptt_e = QLineEdit(hotkeys.get("ptt", "f9"))
        pttt_e = QLineEdit(hotkeys.get("ptt_terminal", "shift+f9"))
        tog_e = QLineEdit(hotkeys.get("toggle", "ctrl+pause"))
        hf.addRow(self._tr("cfg.hotkey.ptt"), ptt_e)
        hf.addRow(self._tr("cfg.hotkey.ptt_terminal"), pttt_e)
        hf.addRow(self._tr("cfg.hotkey.toggle"), tog_e)
        note = QLabel(self._tr("cfg.hotkey.note"))
        note.setStyleSheet("color: palette(mid);")
        note.setWordWrap(True)
        hf.addRow(note)
        tabs.addTab(h, self._tr("cfg.tab.hotkeys"))
        self._w.update(ptt=ptt_e, ptt_terminal=pttt_e, toggle=tog_e)

        # ---- Behavior ----
        b = QWidget()
        bf = QFormLayout(b)

        def _dspin(lo: float, hi: float, step: float, val: float, dec: int = 2) -> QDoubleSpinBox:
            s = QDoubleSpinBox()
            s.setRange(lo, hi)
            s.setSingleStep(step)
            s.setDecimals(dec)
            s.setValue(float(val))
            return s

        min_s = _dspin(0.0, 5.0, 0.1, beh.get("min_duration_s", 0.3))
        max_s = _dspin(1.0, 600.0, 1.0, beh.get("max_duration_s", 300.0), dec=0)

        lock_hold = float(beh.get("lock_hold_s", 3.0))
        lock_on = QCheckBox()
        lock_on.setChecked(lock_hold > 0)
        lock_s = _dspin(0.5, 15.0, 0.5, lock_hold if lock_hold > 0 else 3.0, dec=1)
        lock_s.setEnabled(lock_on.isChecked())
        lock_on.toggled.connect(lock_s.setEnabled)

        nsp = _dspin(0.0, 1.0, 0.05, beh.get("no_speech_threshold", 0.5))
        restore = QCheckBox()
        restore.setChecked(bool(beh.get("restore_clipboard", True)))
        settle = QSpinBox()
        settle.setRange(0, 1000)
        settle.setValue(int(beh.get("clipboard_settle_ms", 80)))
        sound_on = QCheckBox()
        sound_on.setChecked(bool(fb.get("sound_enabled", True)))
        bf.addRow(self._tr("cfg.beh.min_dur"), min_s)
        bf.addRow(self._tr("cfg.beh.max_dur"), max_s)
        bf.addRow(self._tr("cfg.beh.lock_on"), lock_on)
        bf.addRow(self._tr("cfg.beh.lock_after"), lock_s)
        bf.addRow(self._tr("cfg.beh.no_speech"), nsp)
        bf.addRow(self._tr("cfg.beh.restore"), restore)
        bf.addRow(self._tr("cfg.beh.settle"), settle)
        bf.addRow(self._tr("cfg.beh.sound"), sound_on)
        tabs.addTab(b, self._tr("cfg.tab.behavior"))
        self._w.update(
            min_s=min_s, max_s=max_s, lock_on=lock_on, lock_s=lock_s,
            nsp=nsp, restore=restore, settle=settle, sound_on=sound_on,
        )

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        cancel_btn = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if ok_btn is not None:
            ok_btn.setText(self._tr("cfg.ok"))
        if cancel_btn is not None:
            cancel_btn.setText(self._tr("cfg.cancel"))
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        root.addWidget(buttons)

    # ------------------------------------------------------------------

    def _sgk_collect(self) -> dict[str, Any]:
        w = self._w
        new = copy.deepcopy(self._config)
        lang = w["lang"].currentData()
        style = "mono" if w["mono"].isChecked() else "color"
        new.setdefault("ui", {})["language"] = lang
        new["ui"]["tray_icon_style"] = style
        new.setdefault("model", {}).update(
            name=w["name"].currentText().strip(),
            device=w["device"].currentText(),
            compute_type=w["compute"].currentText(),
            language=w["reclang"].currentText().strip() or "auto",
        )
        new.setdefault("audio", {})["device"] = self._mic_values[w["mic"].currentIndex()]
        new.setdefault("hotkeys", {}).update(
            ptt=w["ptt"].text().strip() or "f9",
            ptt_terminal=w["ptt_terminal"].text().strip() or "shift+f9",
            toggle=w["toggle"].text().strip() or "ctrl+pause",
        )
        settle = int(w["settle"].value())
        new.setdefault("behavior", {}).update(
            min_duration_s=round(w["min_s"].value(), 2),
            max_duration_s=round(w["max_s"].value(), 1),
            lock_hold_s=round(w["lock_s"].value(), 1) if w["lock_on"].isChecked() else 0.0,
            no_speech_threshold=round(w["nsp"].value(), 2),
            restore_clipboard=w["restore"].isChecked(),
            clipboard_settle_ms=settle,
            paste_settle_ms=settle,
        )
        new.setdefault("feedback", {})["sound_enabled"] = w["sound_on"].isChecked()
        return new

    def _sgk_apply(self) -> None:
        new = self._sgk_collect()
        sgk_set_autostart(self._w["autostart"].isChecked())
        old_ui = self._config.get("ui", {})
        self._on_save(new)
        if self._on_ui_changed is not None and (
            new["ui"]["language"] != old_ui.get("language")
            or new["ui"]["tray_icon_style"] != old_ui.get("tray_icon_style")
        ):
            self._on_ui_changed(new["ui"]["language"], new["ui"]["tray_icon_style"])
