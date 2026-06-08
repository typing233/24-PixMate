"""Configuration management for PixMate."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import json
import os


@dataclass
class PixMateConfig:
    display_mode: str = "auto"
    companion_width: int = 20
    max_fps: float = 6.0
    sprite_theme: str = "default"
    streaming_threshold: float = 50.0
    idle_timeout: float = 5.0
    sleep_timeout: float = 30.0
    error_timeout: float = 5.0
    log_events: bool = False
    log_path: str = ""
    color_mode: str = "auto"
    show_label: bool = True
    ascii_only: bool = False


def load_config(path: str | Path | None = None) -> PixMateConfig:
    config = PixMateConfig()

    search_paths = []
    if path:
        search_paths.append(Path(path))
    search_paths.extend([
        Path.cwd() / "pixmate.toml",
        Path.cwd() / "pixmate.json",
        Path.home() / ".config" / "pixmate" / "config.json",
    ])

    for p in search_paths:
        if p.exists():
            if p.suffix == ".json":
                _load_json_config(config, p)
            elif p.suffix == ".toml":
                _load_toml_config(config, p)
            break

    return config


def _load_json_config(config: PixMateConfig, path: Path) -> None:
    try:
        data = json.loads(path.read_text())
        _apply_dict(config, data)
    except (json.JSONDecodeError, OSError):
        pass


def _load_toml_config(config: PixMateConfig, path: Path) -> None:
    try:
        import tomllib
        data = tomllib.loads(path.read_text())
        general = data.get("general", {})
        detection = data.get("detection", {})
        appearance = data.get("appearance", {})
        merged = {**general, **detection, **appearance}
        _apply_dict(config, merged)
    except (ImportError, OSError):
        pass


def _apply_dict(config: PixMateConfig, data: dict[str, Any]) -> None:
    field_map = {
        "display": "display_mode",
        "display_mode": "display_mode",
        "companion_width": "companion_width",
        "width": "companion_width",
        "max_fps": "max_fps",
        "fps": "max_fps",
        "sprite_theme": "sprite_theme",
        "theme": "sprite_theme",
        "streaming_threshold": "streaming_threshold",
        "idle_timeout": "idle_timeout",
        "sleep_timeout": "sleep_timeout",
        "error_timeout": "error_timeout",
        "log_events": "log_events",
        "log_path": "log_path",
        "color_mode": "color_mode",
        "show_label": "show_label",
        "ascii_only": "ascii_only",
        "ascii": "ascii_only",
    }

    for key, value in data.items():
        attr = field_map.get(key)
        if attr and hasattr(config, attr):
            setattr(config, attr, value)
