"""Tests for `globals:` file-path resolution (globals_file.py)."""

from __future__ import annotations

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.core import HomeAssistant

from custom_components.jinjaboard.const import CONF_ALLOWED_TEMPLATES, DOMAIN
from custom_components.jinjaboard.errors import (
    JinjaboardGlobalsError,
    JinjaboardIncludeNotFoundError,
    JinjaboardNotAuthorizedError,
    JinjaboardTemplateError,
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


def test_inline_global_value_renders_jjb_user(
    hass: HomeAssistant, write_template
) -> None:
    """A global's *value* can itself be Jinja, referencing `jjb.user` — the
    file's own structure stays plain YAML, but this string is rendered."""
    _authorize_all(hass)
    root = write_template("root.yaml.j2", "value: \"{{ jjb.globals.greeting }}\"\n")
    result = render_template(
        hass,
        root,
        root.read_text(),
        global_vars={"greeting": "{{ jjb.user.name }}"},
        user_vars={"name": "Jerome"},
    )
    assert result == {"value": "Jerome"}


def test_file_global_value_renders_jjb_user(
    hass: HomeAssistant, write_template
) -> None:
    """Same as above, but the globals mapping is loaded from a file — inline
    and file-sourced globals must render values identically."""
    _authorize_all(hass)
    write_template("globals.yaml", 'greeting: "{{ jjb.user.name }}"\n')
    root = write_template("root.yaml.j2", "value: \"{{ jjb.globals.greeting }}\"\n")
    result = render_template(
        hass,
        root,
        root.read_text(),
        global_vars="globals.yaml",
        user_vars={"name": "Jerome"},
    )
    assert result == {"value": "Jerome"}


def test_global_value_renders_jjb_client(
    hass: HomeAssistant, write_template
) -> None:
    _authorize_all(hass)
    root = write_template("root.yaml.j2", "value: \"{{ jjb.globals.lang }}\"\n")
    result = render_template(
        hass,
        root,
        root.read_text(),
        global_vars={"lang": "{{ jjb.client.language }}"},
        client_vars={"language": "en"},
    )
    assert result == {"value": "en"}


def test_nested_dict_and_list_global_values_rendered(
    hass: HomeAssistant, write_template
) -> None:
    """Jinja rendering recurses through nested dict values and list
    elements, leaving a plain literal string untouched."""
    _authorize_all(hass)
    root = write_template(
        "root.yaml.j2",
        "a: \"{{ jjb.globals.nested.a }}\"\n"
        "b: \"{{ jjb.globals.nested.list[0] }}\"\n"
        "c: \"{{ jjb.globals.nested.list[1] }}\"\n",
    )
    result = render_template(
        hass,
        root,
        root.read_text(),
        global_vars={
            "nested": {
                "a": "{{ jjb.user.name }}",
                "list": ["{{ jjb.user.name }}", "static"],
            }
        },
        user_vars={"name": "Jerome"},
    )
    assert result == {"a": "Jerome", "b": "Jerome", "c": "static"}


def test_non_string_global_values_pass_through_unchanged(
    hass: HomeAssistant, write_template
) -> None:
    """`int`/`bool`/`None` global values aren't stringified by the Jinja
    render pass — only `str` leaves are rendered at all."""
    _authorize_all(hass)
    root = write_template(
        "root.yaml.j2",
        "count: {{ jjb.globals.count }}\n"
        "enabled: {{ jjb.globals.enabled }}\n"
        "empty: {{ jjb.globals.empty is none }}\n",
    )
    result = render_template(
        hass,
        root,
        root.read_text(),
        global_vars={"count": 3, "enabled": True, "empty": None},
    )
    assert result == {"count": 3, "enabled": True, "empty": True}


def test_global_value_referencing_jjb_globals_raises(
    hass: HomeAssistant, write_template
) -> None:
    """A global's value can't reference `jjb.globals` — that would be a
    self-reference into the very dict being built, so it's left empty and
    raises rather than silently resolving wrong."""
    _authorize_all(hass)
    root = write_template("root.yaml.j2", "value: \"{{ jjb.globals.a }}\"\n")
    with pytest.raises(JinjaboardTemplateError):
        render_template(
            hass,
            root,
            root.read_text(),
            global_vars={"a": "{{ jjb.globals.other }}"},
        )


def test_global_value_referencing_jjb_inc_raises(
    hass: HomeAssistant, write_template
) -> None:
    """`jjb.inc` doesn't exist yet at the point globals are rendered."""
    _authorize_all(hass)
    root = write_template("root.yaml.j2", "value: \"{{ jjb.globals.a }}\"\n")
    with pytest.raises(JinjaboardTemplateError):
        render_template(
            hass,
            root,
            root.read_text(),
            global_vars={"a": "{{ jjb.inc.foo }}"},
        )


def test_global_value_referencing_jjb_macros_raises(
    hass: HomeAssistant, write_template
) -> None:
    """`jjb.macros` doesn't exist yet at the point globals are rendered."""
    _authorize_all(hass)
    root = write_template("root.yaml.j2", "value: \"{{ jjb.globals.a }}\"\n")
    with pytest.raises(JinjaboardTemplateError):
        render_template(
            hass,
            root,
            root.read_text(),
            global_vars={"a": "{{ jjb.macros.foo }}"},
        )
