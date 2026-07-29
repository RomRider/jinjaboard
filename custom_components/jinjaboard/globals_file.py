"""Resolve a dashboard's `globals:` into a plain `{name: value}` mapping.

`globals:` (exposed to templates as `jjb.globals.<name>`) can be authored
either inline, as a YAML mapping directly in the dashboard's `strategy:`
block (unchanged, pre-existing behavior), or as a `str` path to a separate
file — useful since the project's primary workflow is pasting the
`strategy:` stub into a dashboard created through the HA UI (storage mode),
where there's no file on disk to factor shared globals out of the way
`!include`/`macros:` already let you factor out cards/macros.

A globals file's own *structure* is deliberately never Jinja-rendered as a
whole — it's parsed as plain, static YAML via `yaml.safe_load`, so it can't
itself use `!include`/`!include_dir_*` or any other Jinja/YAML machinery.
This module's job is resolve-and-parse only: `resolve_global_vars` always
returns the raw, unrendered dict, regardless of whether `globals_param` was
a file path or an already-inline mapping. The *values* inside that dict —
whether file- or inline-sourced — are Jinja-rendered afterward, as a
separate step, by `template_engine._render_global_values`, called from
`render_template` right after this function returns.
"""

from __future__ import annotations

from typing import Any

import yaml
from homeassistant.core import HomeAssistant

from .errors import (
    JinjaboardGlobalsError,
    JinjaboardIncludeNotFoundError,
    JinjaboardNotAuthorizedError,
)
from .path_guard import resolve_config_path
from .template_allowlist import is_path_authorized


def resolve_global_vars(
    hass: HomeAssistant, globals_param: dict[str, Any] | str | None
) -> dict[str, Any] | None:
    """Resolve a request's `globals` field into a plain vars mapping.

    A non-`str` value (a `dict`, already-validated by the WS schema, or
    `None`) is returned unchanged — today's inline-`globals:` behavior. A
    `str` value is treated as a file path, relative to `config_dir` (there's
    no "current file" concept at the dashboard-config level, matching
    `macros.py`'s own reasoning for its `macros:` entries).
    """
    if not isinstance(globals_param, str):
        return globals_param

    target = resolve_config_path(hass, globals_param)
    if not is_path_authorized(hass, target):
        raise JinjaboardNotAuthorizedError(
            f"Globals file '{globals_param}' is not on JinjaBoard's "
            "authorized files list. Add it in Settings → Devices & "
            "Services → JinjaBoard → Configure."
        )

    try:
        source = target.read_text()
    except OSError as err:
        raise JinjaboardIncludeNotFoundError(
            f"Globals file {globals_param!r} not found"
        ) from err

    try:
        parsed = yaml.safe_load(source)
    except yaml.YAMLError as err:
        raise JinjaboardGlobalsError(
            f"Globals file {globals_param!r} is not valid YAML: {err}"
        ) from err

    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise JinjaboardGlobalsError(
            f"Globals file {globals_param!r} must contain a YAML mapping at "
            f"the top level, got {type(parsed).__name__}"
        )
    return parsed
