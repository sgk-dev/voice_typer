"""Unit tests for the i18n table."""

from __future__ import annotations

from sgk_voice_typer.gui import i18n


def test_normalize_lang() -> None:
    assert i18n.sgk_normalize_lang("ru") == "ru"
    assert i18n.sgk_normalize_lang("RU") == "ru"
    assert i18n.sgk_normalize_lang("de") == "en"
    assert i18n.sgk_normalize_lang(None) == "en"


def test_known_key_translates() -> None:
    assert i18n.sgk_tr("tray.quit", "ru") == "Выход"
    assert i18n.sgk_tr("tray.quit", "en") == "Quit"


def test_unknown_key_returns_itself() -> None:
    assert i18n.sgk_tr("no.such.key", "ru") == "no.such.key"


def test_every_string_has_english() -> None:
    missing = [k for k, v in i18n._STRINGS.items() if "en" not in v]
    assert missing == []


def test_russian_falls_back_to_english_when_absent() -> None:
    # temporarily use a key that only has en (none exist, so simulate via table)
    i18n._STRINGS["_tmp"] = {"en": "Only English"}
    try:
        assert i18n.sgk_tr("_tmp", "ru") == "Only English"
    finally:
        del i18n._STRINGS["_tmp"]
