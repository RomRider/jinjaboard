"""Tests for `globals:` file-path resolution (globals_file.py)."""

from __future__ import annotations

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.core import HomeAssistant

from custom_components.jinjaboard.const import CONF_ALLOWED_TEMPLATES, DOMAIN
from custom_components.jinjaboard.errors import (
    JinjaboardGlobalsError,
    JinjaboardIncludeNotFoundError,
    JinjaboardNotAuthorizedError,
)
from custom_components.jinjaboard.globals_file import resolve_global_vars
from custom_components.jinjaboard.path_guard import JinjaboardPathError
from custom_components.jinjaboard.template_engine import render_template

import pytest


def _authorize_all(hass: HomeAssistant) -> None:
    """Authorize the whole config dir, sync (`add_to_hass` alone is enough
    — see `test_macros.py`'s `_render` helper for why `async_setup` isn't
    needed)."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        options={CONF_ALLOWED_TEMPLATES: [{"path": "", "is_dir": True}]},
    )
    entry.add_to_hass(hass)


def test_non_string_passthrough(hass: HomeAssistant) -> None:
    """A `dict` (today's inline-`globals:` shape) is returned unchanged, no
    allowlist check involved — this must work with no config entry at all."""
    assert resolve_global_vars(hass, {"area_id": "kitchen"}) == {"area_id": "kitchen"}
    assert resolve_global_vars(hass, None) is None


def test_loads_valid_file(hass: HomeAssistant, write_template) -> None:
    _authorize_all(hass)
    write_template("globals.yaml", "area_id: kitchen\ncount: 3\n")
    assert resolve_global_vars(hass, "globals.yaml") == {"area_id": "kitchen", "count": 3}


def test_empty_file_returns_empty_dict(hass: HomeAssistant, write_template) -> None:
    _authorize_all(hass)
    write_template("globals.yaml", "")
    assert resolve_global_vars(hass, "globals.yaml") == {}


def test_missing_file(hass: HomeAssistant) -> None:
    _authorize_all(hass)
    with pytest.raises(JinjaboardIncludeNotFoundError):
        resolve_global_vars(hass, "missing.yaml")


def test_invalid_yaml(hass: HomeAssistant, write_template) -> None:
    _authorize_all(hass)
    write_template("globals.yaml", "area_id: [unterminated\n")
    with pytest.raises(JinjaboardGlobalsError):
        resolve_global_vars(hass, "globals.yaml")


def test_non_mapping_top_level(hass: HomeAssistant, write_template) -> None:
    _authorize_all(hass)
    write_template("globals.yaml", "- a\n- b\n")
    with pytest.raises(JinjaboardGlobalsError):
        resolve_global_vars(hass, "globals.yaml")


def test_path_traversal(hass: HomeAssistant) -> None:
    _authorize_all(hass)
    with pytest.raises(JinjaboardPathError):
        resolve_global_vars(hass, "../../../../../../etc/hostname")


def test_unauthorized_path(hass: HomeAssistant, write_template) -> None:
    """A `globals:` file path is a dashboard-author-controlled top-level
    field, same trust boundary as `template:` — a path under `config_dir`
    but not on the admin's allowlist must be rejected."""
    write_template("globals.yaml", "area_id: kitchen\n")
    with pytest.raises(JinjaboardNotAuthorizedError):
        resolve_global_vars(hass, "globals.yaml")


def test_render_template_loads_globals_from_file(
    hass: HomeAssistant, write_template
) -> None:
    """End-to-end: `render_template`'s `global_vars` may be a file path,
    resolved before `jjb.globals` is built."""
    _authorize_all(hass)
    write_template("globals.yaml", "area_id: kitchen\n")
    root = write_template("root.yaml.j2", "value: \"{{ jjb.globals.area_id }}\"\n")
    result = render_template(hass, root, root.read_text(), global_vars="globals.yaml")
    assert result == {"value": "kitchen"}
