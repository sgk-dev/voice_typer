from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


CONFIG_PATH = Path.home() / ".config" / "voice_typer" / "config.toml"


@dataclass
class Config:
    model_name: str = "large-v3-turbo"
    device: str = "cuda"
    compute_type: str = "float16"
    language: str = "auto"
    audio_device: str | None = None
    sample_rate: int = 16000
    hotkey: str = "KEY_F9"
    terminal_apps: list[str] = field(default_factory=lambda: [
        "gnome-terminal", "alacritty", "kitty", "tilix", "xterm", "bash", "zsh", "tmux"
    ])
    sleep_after_paste: float = 0.05
    log_file: str = str(Path.home() / ".local" / "share" / "voice_typer" / "voice_typer.log")
    log_max_bytes: int = 5_242_880
    log_backup_count: int = 3
    socket_path: str = "/tmp/voice_typer.sock"


def load_config() -> Config:
    if not CONFIG_PATH.exists():
        return Config()
    with open(CONFIG_PATH, "rb") as f:
        data = tomllib.load(f)
    m = data.get("model", {})
    a = data.get("audio", {})
    h = data.get("hotkey", {})
    i = data.get("inject", {})
    lg = data.get("logging", {})
    s = data.get("socket", {})
    return Config(
        model_name=m.get("name", Config.model_name),
        device=m.get("device", Config.device),
        compute_type=m.get("compute_type", Config.compute_type),
        language=m.get("language", Config.language),
        audio_device=a.get("device", Config.audio_device),
        sample_rate=a.get("sample_rate", Config.sample_rate),
        hotkey=h.get("key", Config.hotkey),
        terminal_apps=i.get("terminal_apps", Config().terminal_apps),
        sleep_after_paste=i.get("sleep_after_paste", Config.sleep_after_paste),
        log_file=lg.get("file", Config.log_file),
        log_max_bytes=lg.get("max_bytes", Config.log_max_bytes),
        log_backup_count=lg.get("backup_count", Config.log_backup_count),
        socket_path=s.get("path", Config.socket_path),
    )
