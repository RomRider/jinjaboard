"""Shared path-resolution and traversal-guard logic for JinjaBoard.

Used both for the primary template path (from a dashboard's `strategy.
template`) and for `!include`/`!include_dir_*` targets (see `includes.py`).
All template-related paths must resolve to stay under
`hass.config.config_dir`, regardless of what directory they're written
relative to.
"""

from __future__ import annotations

import os
from pathlib import Path

from homeassistant.core import HomeAssistant


class JinjaboardPathError(Exception):
    """Raised when a path escapes the Home Assistant config directory."""


def normalize_path(path: Path) -> Path:
    """Lexically normalize `path` — collapse `.`/`..` segments via
    `os.path.normpath`, a pure string operation that never touches the
    filesystem or dereferences symlinks.

    Deliberately *not* `Path.resolve()`: `config_dir` (and, since dashboard
    files can live under a directory symlinked in from elsewhere — e.g. this
    project's own devcontainer setup — any path under it) may contain
    symlink components whose real target lies outside `config_dir`. Using
    `Path.resolve()` for the confinement check would follow those and reject
    a perfectly legitimate, syntactically-confined path. The guard's actual
    job is to reject a path/include argument that types its way out via `..`
    or an absolute path — that's a purely lexical property and doesn't
    require (or benefit from) resolving symlinks. Reading the file
    afterwards still transparently follows any symlink regardless, since
    that's ordinary OS/`open()` behavior independent of how the `Path` used
    for validation was normalized.
    """
    return Path(os.path.normpath(path))


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
    config_dir = normalize_path(Path(hass.config.config_dir))
    candidate = normalize_path((base_dir or config_dir) / relative_path)

    try:
        candidate.relative_to(config_dir)
    except ValueError:
        raise JinjaboardPathError(
            f"Path '{relative_path}' escapes the Home Assistant config directory"
        ) from None

    return candidate


def config_relative_display_path(hass: HomeAssistant, path: Path) -> str:
    """Render `path` relative to `config_dir` for display in error/debug
    output, falling back to the absolute path if that fails (it shouldn't,
    since every path reaching here was already confined by
    `resolve_config_path`)."""
    try:
        return str(path.relative_to(normalize_path(Path(hass.config.config_dir))))
    except ValueError:
        return str(path)
