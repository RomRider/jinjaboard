"""Shared path-resolution and traversal-guard logic for JinjaBoard.

Used both for the primary template path (from a dashboard's `strategy.
template`) and for `!include`/`!include_dir_*` targets (see `includes.py`).
All template-related paths must resolve to stay under
`hass.config.config_dir`, regardless of what directory they're written
relative to.
"""

from __future__ import annotations

from pathlib import Path

from homeassistant.core import HomeAssistant


class JinjaboardPathError(Exception):
    """Raised when a path escapes the Home Assistant config directory."""


def resolve_config_path(
    hass: HomeAssistant, relative_path: str, base_dir: Path | None = None
) -> Path:
    """Resolve `relative_path` against `base_dir` (default `config_dir`), guarded.

    `base_dir` lets `!include` targets resolve relative to the directory of
    the file that references them (matching real Home Assistant's `!include`)
    rather than always relative to the config root — but the result is always
    re-validated to stay under `config_dir` regardless of `base_dir`, so a
    `base_dir` that is itself outside `config_dir` can't be used to escape it.

    Raises `JinjaboardPathError` if the resolved path would fall outside the
    config directory (e.g. via `..` segments or an absolute path).
    """
    config_dir = Path(hass.config.config_dir).resolve()
    candidate = ((base_dir or config_dir) / relative_path).resolve()

    try:
        candidate.relative_to(config_dir)
    except ValueError:
        raise JinjaboardPathError(
            f"Path '{relative_path}' escapes the Home Assistant config directory"
        ) from None

    return candidate
