"""Unit tests for the structured JSON logger."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from sgk_voice_typer.utils.logger import sgk_configure_logging, sgk_get_logger


def test_get_logger_is_under_package_hierarchy() -> None:
    log = sgk_get_logger("sgk_voice_typer.something")
    assert log.name == "sgk_voice_typer.something"


def test_no_source_uses_reserved_logrecord_keys_in_extra() -> None:
    """extra={"name": ...} & friends raise KeyError and kill the calling thread."""
    import pathlib
    import re

    import sgk_voice_typer

    reserved = (
        "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
        "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
        "created", "msecs", "relativeCreated", "thread", "threadName",
        "processName", "process", "message", "taskName",
    )
    pkg_dir = pathlib.Path(sgk_voice_typer.__file__).parent
    offenders: list[str] = []
    for py in pkg_dir.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        for m in re.finditer(r"extra=\{([^}]*)\}", text, re.DOTALL):
            keys = set(re.findall(r"""["']([A-Za-z_]+)["']\s*:""", m.group(1)))
            bad = keys & set(reserved)
            if bad:
                offenders.append(f"{py.name}: {sorted(bad)}")
    assert not offenders, offenders


def test_file_output_is_single_line_json(tmp_path: Path) -> None:
    log_file = tmp_path / "vt.log"
    sgk_configure_logging(level="INFO", log_file=str(log_file))

    sgk_get_logger("sgk_voice_typer.test").info(
        "sgk_event", extra={"chars": 12, "lang": "ru"}
    )

    for h in logging.getLogger("sgk_voice_typer").handlers:
        h.flush()

    lines = log_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["event"] == "sgk_event"
    assert payload["level"] == "INFO"
    assert payload["chars"] == 12
    assert payload["lang"] == "ru"


def test_level_filtering(tmp_path: Path) -> None:
    log_file = tmp_path / "vt.log"
    sgk_configure_logging(level="WARNING", log_file=str(log_file))

    log = sgk_get_logger("sgk_voice_typer.test")
    log.info("sgk_quiet")
    log.warning("sgk_loud")

    for h in logging.getLogger("sgk_voice_typer").handlers:
        h.flush()

    text = log_file.read_text(encoding="utf-8")
    assert "sgk_loud" in text
    assert "sgk_quiet" not in text
