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


def apply_db_settings(session) -> int:
    """Merge persisted DB Setting overrides into the in-memory config.

    This is the third (highest-priority) config layer the docstring of
    load_config() promises: defaults < config.yaml < DB settings. It must run
    once at startup so settings saved via the admin UI survive a restart.
    Returns the number of overrides applied.
    """
    import json

    from sqlmodel import select

    from app.models import Setting

    cfg = get_config()
    count = 0
    for setting in session.exec(select(Setting)).all():
        try:
            value = json.loads(setting.value_json)
        except (ValueError, TypeError):
            continue
        set_nested(cfg, setting.key, value)
        count += 1
    return count


def export_settings_bundle(session, include_secret: bool = False) -> dict[str, Any]:
    """Build a portable settings bundle: config.yaml overrides + DB setting rows.

    The JWT secret_key is excluded by default (it's a secret and box-specific).
    """
    import json

    from sqlmodel import select

    from app.models import Setting

    user_cfg = _load_yaml(_BASE_DIR / "config.yaml")
    if not include_secret and isinstance(user_cfg.get("auth"), dict):
        user_cfg["auth"].pop("secret_key", None)

    db_settings: dict[str, Any] = {}
    for setting in session.exec(select(Setting)).all():
        try:
            db_settings[setting.key] = json.loads(setting.value_json)
        except (ValueError, TypeError):
            continue

    return {
        "mkphotobox_settings": 1,
        "config_yaml": user_cfg,
        "db_settings": db_settings,
    }


def import_settings_bundle(session, bundle: dict[str, Any]) -> dict[str, Any]:
    """Apply a settings bundle (from export_settings_bundle): merge config.yaml,
    upsert DB settings, then reload so it takes effect immediately."""
    import json
    from datetime import datetime

    from sqlmodel import select

    from app.models import Setting

    if not isinstance(bundle, dict) or "mkphotobox_settings" not in bundle:
        raise ValueError("Keine gültige Einstellungs-Datei.")

    # 1) Merge config.yaml (imported values win) — never drop an existing secret_key
    cfg_in = bundle.get("config_yaml") or {}
    if isinstance(cfg_in, dict) and cfg_in:
        existing = _load_yaml(_BASE_DIR / "config.yaml")
        merged = deep_merge(existing, cfg_in)
        existing_secret = (existing.get("auth") or {}).get("secret_key")
        if existing_secret and not (cfg_in.get("auth") or {}).get("secret_key"):
            merged.setdefault("auth", {})["secret_key"] = existing_secret
        with open(_BASE_DIR / "config.yaml", "w", encoding="utf-8") as f:
            yaml.dump(merged, f, default_flow_style=False, allow_unicode=True)

    # 2) Upsert DB settings
    count = 0
    for key, value in (bundle.get("db_settings") or {}).items():
        row = session.exec(select(Setting).where(Setting.key == key)).first()
        value_json = json.dumps(value)
        if row:
            row.value_json = value_json
            row.updated_at = datetime.utcnow()
        else:
            row = Setting(key=key, value_json=value_json)
        session.add(row)
        count += 1
    session.commit()

    # 3) Reload merged config + re-apply DB layer so changes are live now
    load_config(reload=True)
    apply_db_settings(session)
    return {"config_imported": bool(cfg_in), "db_settings": count}


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
