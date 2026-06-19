"""Configuration system with 3-layer merge: defaults < config.yaml < DB settings."""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

import yaml

_BASE_DIR = Path(__file__).resolve().parent.parent
_config: dict[str, Any] = {}


def deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge *override* into a copy of *base*."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_config(*, reload: bool = False) -> dict[str, Any]:
    """Load and cache the merged configuration.

    Merge order (later wins):
      1. config.defaults.yaml  (shipped defaults)
      2. config.yaml           (user overrides)
    DB settings are applied at runtime by the settings service.
    """
    global _config
    if _config and not reload:
        return _config

    defaults_path = _BASE_DIR / "config.defaults.yaml"
    user_path = _BASE_DIR / "config.yaml"

    defaults = _load_yaml(defaults_path)
    user_overrides = _load_yaml(user_path)

    _config = deep_merge(defaults, user_overrides)

    # Allow env override for secret key
    env_secret = os.environ.get("PHOTOBOX_SECRET_KEY")
    if env_secret:
        _config.setdefault("auth", {})["secret_key"] = env_secret

    return _config


def get_config() -> dict[str, Any]:
    """Return the current config (loads if not yet loaded)."""
    if not _config:
        return load_config()
    return _config


def get_nested(cfg: dict, dotted_key: str, default: Any = None) -> Any:
    """Access a nested config value using a dotted key path.

    Example: get_nested(cfg, "cameras.gphoto2.enabled") -> False
    """
    keys = dotted_key.split(".")
    current = cfg
    for key in keys:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return default
    return current


def set_nested(cfg: dict, dotted_key: str, value: Any) -> None:
    """Set a nested config value using a dotted key path."""
    keys = dotted_key.split(".")
    current = cfg
    for key in keys[:-1]:
        if key not in current or not isinstance(current[key], dict):
            current[key] = {}
        current = current[key]
    current[keys[-1]] = value


def save_user_config(overrides: dict) -> None:
    """Write user overrides to config.yaml."""
    user_path = _BASE_DIR / "config.yaml"
    with open(user_path, "w", encoding="utf-8") as f:
        yaml.dump(overrides, f, default_flow_style=False, allow_unicode=True)


def update_user_config(dotted_key: str, value: Any) -> None:
    """Persist a single nested value to config.yaml (merging, not clobbering)."""
    user_path = _BASE_DIR / "config.yaml"
    existing = _load_yaml(user_path)
    set_nested(existing, dotted_key, value)
    with open(user_path, "w", encoding="utf-8") as f:
        yaml.dump(existing, f, default_flow_style=False, allow_unicode=True)
    # keep the in-memory config in sync
    if _config:
        set_nested(_config, dotted_key, value)
