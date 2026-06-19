"""Internationalization: load YAML translation files, provide t() function."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_BASE_DIR = Path(__file__).resolve().parent.parent
_translations: dict[str, dict[str, str]] = {}


def load_translations() -> None:
    """Load all locale/*.yaml files into memory."""
    locale_dir = _BASE_DIR / "locale"
    if not locale_dir.exists():
        logger.warning("Locale directory not found: %s", locale_dir)
        return

    for path in locale_dir.glob("*.yaml"):
        lang = path.stem
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        _translations[lang] = _flatten(data)
        logger.info("Loaded locale: %s (%d keys)", lang, len(_translations[lang]))


def _flatten(data: dict, prefix: str = "") -> dict[str, str]:
    """Flatten nested YAML into dotted keys."""
    result = {}
    for key, value in data.items():
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            result.update(_flatten(value, full_key))
        else:
            result[full_key] = str(value)
    return result


def t(key: str, lang: str = "de", **kwargs: Any) -> str:
    """Translate a key. Supports {placeholder} interpolation."""
    template = _translations.get(lang, {}).get(key)
    if template is None:
        # Fallback to default language
        template = _translations.get("de", {}).get(key, key)
    if kwargs:
        try:
            return template.format(**kwargs)
        except (KeyError, IndexError):
            return template
    return template


def get_all_translations(lang: str) -> dict[str, str]:
    """Return all translations for a language (for the frontend)."""
    return dict(_translations.get(lang, {}))


def get_available_locales() -> list[str]:
    """Return list of available locale codes."""
    return sorted(_translations.keys())
