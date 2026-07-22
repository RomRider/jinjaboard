"""Admin-managed allowlist of files usable as a top-level `template`.

Only the top-level `template` path passed to `jinjaboard/render`
(`websocket.py`) is checked against this list. Once a template is
authorized, everything it reaches via `!include`/`!include_dir_*`/
`macros:` is unrestricted, same as before this module existed — those are
already confined to `config_dir` by `path_guard.resolve_config_path` on
every resolution, which is a traversal guard, not an authorization list.
Re-checking every included file against the allowlist too would make a
single authorized template unable to pull in its own helper files, which
defeats the point of `!include` existing at all.
"""

from __future__ import annotations

from pathlib import Path
from typing import TypedDict

from homeassistant.core import HomeAssistant

from .const import CONF_ALLOWED_TEMPLATES, DOMAIN
from .path_guard import JinjaboardPathError, resolve_config_path


class AllowlistEntry(TypedDict):
    """One admin-added allowlist entry."""

    path: str
    is_dir: bool


def get_allowed_entries(hass: HomeAssistant) -> list[AllowlistEntry]:
    """Return the current allowlist from the (single) config entry's options.

    Read fresh on every call rather than cached — `single_config_entry:
    true` (manifest.json) guarantees exactly one entry exists once the
    integration is set up, and re-reading `entry.options` is cheap enough
    that caching would only add a staleness risk for no real benefit.
    """
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        return []
    return entries[0].options.get(CONF_ALLOWED_TEMPLATES, [])


def is_template_authorized(hass: HomeAssistant, resolved_path: Path) -> bool:
    """Check `resolved_path` (already `resolve_config_path`-guarded) against the allowlist."""
    for entry in get_allowed_entries(hass):
        try:
            allowed_path = resolve_config_path(hass, entry["path"])
        except JinjaboardPathError:
            # An entry that no longer confines to config_dir (e.g. config_dir
            # itself changed) just never matches, rather than breaking every
            # render because of one stale entry.
            continue

        if entry["is_dir"]:
            if resolved_path == allowed_path or resolved_path.is_relative_to(allowed_path):
                return True
        elif resolved_path == allowed_path:
            return True

    return False
