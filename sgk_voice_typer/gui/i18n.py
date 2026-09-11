"""UI translation table for the tray and settings dialog.

English (default) and Russian. Active language comes from config ``ui.language``.
Missing keys fall back to English, then to the key itself - a typo shows up but
never crashes the GUI.
"""

from __future__ import annotations

SGK_LANGUAGES: tuple[str, ...] = ("en", "ru")
SGK_LANGUAGE_NAMES: dict[str, str] = {"en": "English", "ru": "Русский"}

_DEFAULT_LANG = "en"

_STRINGS: dict[str, dict[str, str]] = {
    # ---- tray ----
    "tray.enabled": {"en": "Enabled", "ru": "Включено"},
    "tray.paused": {"en": "Paused", "ru": "Выключено"},
    "tray.settings": {"en": "Settings...", "ru": "Настройки..."},
    "tray.about": {"en": "About", "ru": "О программе"},
    "tray.sound": {"en": "Sound", "ru": "Звук"},
    "tray.quit": {"en": "Quit", "ru": "Выход"},
    "tray.tip.idle": {"en": "VoiceTyper - ready", "ru": "VoiceTyper - готов"},
    "tray.tip.recording": {"en": "VoiceTyper - recording...", "ru": "VoiceTyper - запись..."},
    "tray.tip.processing": {"en": "VoiceTyper - transcribing...", "ru": "VoiceTyper - распознавание..."},
    "tray.tip.paused": {"en": "VoiceTyper - paused", "ru": "VoiceTyper - выключено"},
    # ---- about ----
    "about.title": {"en": "About VoiceTyper", "ru": "О программе VoiceTyper"},
    "about.tagline": {
        "en": "Push-to-talk voice input for Linux.",
        "ru": "Голосовой ввод по нажатию клавиши для Linux.",
    },
    "about.version": {"en": "Version", "ru": "Версия"},
    "about.author": {"en": "Author", "ru": "Автор"},
    "about.license": {"en": "License", "ru": "Лицензия"},
    "about.star": {"en": "★ Star on GitHub", "ru": "★ Звезда на GitHub"},
    "about.donate": {"en": "♥ Support the project", "ru": "♥ Поддержать проект"},
    "about.close": {"en": "Close", "ru": "Закрыть"},
    "about.thanks": {
        "en": "If VoiceTyper saves you time, a star or a small donation helps a lot.",
        "ru": "Если VoiceTyper экономит вам время - звезда или небольшой донат очень помогают.",
    },
    # ---- settings ----
    "cfg.title": {"en": "VoiceTyper - Settings", "ru": "VoiceTyper - Настройки"},
    "cfg.ok": {"en": "OK", "ru": "ОК"},
    "cfg.cancel": {"en": "Cancel", "ru": "Отмена"},
    "cfg.tab.general": {"en": "General", "ru": "Основное"},
    "cfg.tab.model": {"en": "Model", "ru": "Модель"},
    "cfg.tab.audio": {"en": "Audio", "ru": "Звук"},
    "cfg.tab.hotkeys": {"en": "Hotkeys", "ru": "Горячие клавиши"},
    "cfg.tab.behavior": {"en": "Behavior", "ru": "Поведение"},
    "cfg.general.language": {"en": "Interface language:", "ru": "Язык интерфейса:"},
    "cfg.general.mono": {"en": "Monochrome tray icon:", "ru": "Чёрно-белая иконка в трее:"},
    "cfg.general.autostart": {"en": "Launch on login:", "ru": "Запускать при входе:"},
    "cfg.model.name": {"en": "Model:", "ru": "Модель:"},
    "cfg.model.device": {"en": "Device:", "ru": "Устройство:"},
    "cfg.model.compute": {"en": "Compute type:", "ru": "Тип вычислений:"},
    "cfg.model.language": {"en": "Recognition language:", "ru": "Язык распознавания:"},
    "cfg.model.lang_auto": {"en": "Auto-detect", "ru": "Автоопределение"},
    "cfg.audio.device": {"en": "Microphone:", "ru": "Микрофон:"},
    "cfg.audio.default": {"en": "System default", "ru": "Системный по умолчанию"},
    "cfg.hotkey.ptt": {"en": "Record and type:", "ru": "Запись и ввод:"},
    "cfg.hotkey.ptt_terminal": {"en": "Record and type (terminal):", "ru": "Запись и ввод (терминал):"},
    "cfg.hotkey.toggle": {"en": "Enable / disable:", "ru": "Включить / выключить:"},
    "cfg.hotkey.note": {
        "en": "Model and hotkey changes take effect after a restart.",
        "ru": "Смена модели и горячих клавиш применяется после перезапуска.",
    },
    "cfg.beh.min_dur": {"en": "Ignore clips shorter than (s):", "ru": "Игнорировать записи короче (с):"},
    "cfg.beh.max_dur": {"en": "Stop recording after (s):", "ru": "Останавливать запись через (с):"},
    "cfg.beh.lock_on": {"en": "Hands-free lock:", "ru": "Режим фиксации (hands-free):"},
    "cfg.beh.lock_after": {"en": "Lock after holding (s):", "ru": "Фиксировать после удержания (с):"},
    "cfg.beh.sound": {"en": "Start / stop sound:", "ru": "Звук начала / конца записи:"},
    "cfg.beh.sound_test": {"en": "▶ Test", "ru": "▶ Прослушать"},
    "cfg.beh.no_speech": {"en": "Silence threshold (0-1):", "ru": "Порог тишины (0-1):"},
    "cfg.beh.restore": {"en": "Restore clipboard after typing:", "ru": "Восстанавливать буфер после ввода:"},
    "cfg.beh.settle": {"en": "Clipboard settle delay (ms):", "ru": "Задержка буфера обмена (мс):"},
}


def sgk_normalize_lang(lang: str | None) -> str:
    if lang and lang.lower() in SGK_LANGUAGES:
        return lang.lower()
    return _DEFAULT_LANG


def sgk_tr(key: str, lang: str | None = None) -> str:
    lang = sgk_normalize_lang(lang)
    entry = _STRINGS.get(key)
    if entry is None:
        return key
    return entry.get(lang) or entry.get(_DEFAULT_LANG) or key
