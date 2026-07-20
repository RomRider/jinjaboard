"""Shared path-resolution and traversal-guard logic for JinjaBoard.

Used both for the primary template path (from a dashboard's `strategy.options.
template`) and, later, for `!include` targets. All template-related paths are
interpreted relative to `hass.config.config_dir` and must resolve to stay
under it.
"""

from __future__ import annotations

from pathlib import Path

from homeassistant.core import HomeAssistant


class JinjaboardPathError(Exception):
    """Raised when a path escapes the Home Assistant config directory."""


def resolve_config_path(hass: HomeAssistant, relative_path: str) -> Path:
    """Resolve `relative_path` against `hass.config.config_dir`, guarded.

    Raises `JinjaboardPathError` if the resolved path would fall outside the
    config directory (e.g. via `..` segments or an absolute path).
    """
    config_dir = Path(hass.config.config_dir).resolve()
    candidate = (config_dir / relative_path).resolve()

    try:
        candidate.relative_to(config_dir)
    except ValueError:
        raise JinjaboardPathError(
            f"Path '{relative_path}' escapes the Home Assistant config directory"
        ) from None

    return candidate
