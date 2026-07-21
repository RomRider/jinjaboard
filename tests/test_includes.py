"""Tests for !include/!include_dir_* resolution (includes.py)."""

from __future__ import annotations

import pytest

from homeassistant.core import HomeAssistant

from custom_components.jinjaboard.errors import (
    JinjaboardIncludeNotFoundError,
    JinjaboardTemplateError,
    JinjaboardYamlError,
)
from custom_components.jinjaboard.includes import MAX_INCLUDE_DEPTH
from custom_components.jinjaboard.path_guard import JinjaboardPathError
from custom_components.jinjaboard.template_engine import render_template


def _render(hass: HomeAssistant, path):
    return render_template(hass, path, path.read_text())


def test_include_scalar_form(hass: HomeAssistant, write_template) -> None:
    write_template("header.yaml.j2", "type: markdown\ncontent: Header\n")
    root = write_template("root.yaml.j2", "cards:\n  - !include header.yaml.j2\n")
    result = _render(hass, root)
    assert result == {"cards": [{"type": "markdown", "content": "Header"}]}


def test_include_mapping_form_with_vars_override(
    hass: HomeAssistant, write_template
) -> None:
    write_template("greeting.yaml.j2", "content: Hello {{ jjb.inc.area_id }}\n")
    root = write_template(
        "root.yaml.j2",
        "cards:\n  - !include {path: greeting.yaml.j2, vars: {area_id: kitchen}}\n",
    )
    result = _render(hass, root)
    assert result == {"cards": [{"content": "Hello kitchen"}]}


def test_include_inherits_parent_inc_vars_at_deeper_nesting(
    hass: HomeAssistant, write_template
) -> None:
    """A grandchild include with no `vars:` of its own still sees the
    `jjb.inc` vars its parent include was given."""
    write_template("greeting.yaml.j2", "content: Hello {{ jjb.inc.area_id }}\n")
    write_template("wrapper.yaml.j2", "value: !include greeting.yaml.j2\n")
    root = write_template(
        "root.yaml.j2",
        "cards:\n  - !include {path: wrapper.yaml.j2, vars: {area_id: kitchen}}\n",
    )
    result = _render(hass, root)
    assert result == {"cards": [{"value": {"content": "Hello kitchen"}}]}


def test_commented_out_jinja_is_not_rendered_inside_an_include(
    hass: HomeAssistant, write_template
) -> None:
    """Whole-line comment blanking (see template_engine.py) applies to every
    render in the tree, not just the root template — included files go
    through the same `_render_jinja_on_loop` choke point."""
    write_template(
        "card.yaml.j2",
        "type: markdown\n# {{ totally_undefined }}\ncontent: hi\n",
    )
    root = write_template("root.yaml.j2", "cards:\n  - !include card.yaml.j2\n")
    result = _render(hass, root)
    assert result == {"cards": [{"type": "markdown", "content": "hi"}]}


def test_include_inherits_dashboard_globals(
    hass: HomeAssistant, write_template
) -> None:
    write_template("greeting.yaml.j2", "content: Hello {{ jjb.globals.area_id }}\n")
    root = write_template("root.yaml.j2", "cards:\n  - !include greeting.yaml.j2\n")
    result = render_template(
        hass, root, root.read_text(), global_vars={"area_id": "living_room"}
    )
    assert result == {"cards": [{"content": "Hello living_room"}]}


def test_include_paths_resolve_relative_to_including_file(
    hass: HomeAssistant, write_template
) -> None:
    write_template("sub/child.yaml.j2", "value: from_sub\n")
    root = write_template("sub/root.yaml.j2", "result: !include child.yaml.j2\n")
    assert _render(hass, root) == {"result": {"value": "from_sub"}}


def test_include_dir_list_is_recursive_and_sorted(
    hass: HomeAssistant, write_template
) -> None:
    write_template("cards/b.yaml.j2", "name: b\n")
    write_template("cards/a.yaml.j2", "name: a\n")
    write_template("cards/nested/c.yaml.j2", "name: c\n")
    root = write_template("root.yaml.j2", "cards: !include_dir_list cards\n")
    result = _render(hass, root)
    assert result == {"cards": [{"name": "a"}, {"name": "b"}, {"name": "c"}]}


def test_include_dir_list_skips_dotfiles_and_dot_dirs(
    hass: HomeAssistant, write_template
) -> None:
    write_template("cards/visible.yaml.j2", "name: visible\n")
    write_template("cards/.hidden.yaml.j2", "name: hidden\n")
    write_template("cards/.hidden_dir/inside.yaml.j2", "name: also_hidden\n")
    root = write_template("root.yaml.j2", "cards: !include_dir_list cards\n")
    result = _render(hass, root)
    assert result == {"cards": [{"name": "visible"}]}


def test_include_dir_named_strips_full_template_extension(
    hass: HomeAssistant, write_template
) -> None:
    write_template("cards/kitchen.yaml.j2", "entity: light.kitchen\n")
    root = write_template("root.yaml.j2", "result: !include_dir_named cards\n")
    result = _render(hass, root)
    assert result == {"result": {"kitchen": {"entity": "light.kitchen"}}}


def test_include_dir_named_empty_file_becomes_empty_dict(
    hass: HomeAssistant, write_template
) -> None:
    write_template("cards/empty.yaml.j2", "")
    root = write_template("root.yaml.j2", "result: !include_dir_named cards\n")
    result = _render(hass, root)
    assert result == {"result": {"empty": {}}}


def test_include_dir_merge_list_skips_non_list_files(
    hass: HomeAssistant, write_template
) -> None:
    write_template("cards/a.yaml.j2", "- name: a\n")
    write_template("cards/b.yaml.j2", "not_a_list: true\n")
    root = write_template("root.yaml.j2", "cards: !include_dir_merge_list cards\n")
    result = _render(hass, root)
    assert result == {"cards": [{"name": "a"}]}


def test_include_dir_merge_named_skips_non_dict_files(
    hass: HomeAssistant, write_template
) -> None:
    write_template("cards/a.yaml.j2", "alpha: 1\n")
    write_template("cards/b.yaml.j2", "- not_a_dict\n")
    root = write_template("root.yaml.j2", "vars: !include_dir_merge_named cards\n")
    result = _render(hass, root)
    assert result == {"vars": {"alpha": 1}}


def test_include_cycle_is_detected(hass: HomeAssistant, write_template) -> None:
    write_template("a.yaml.j2", "a: !include b.yaml.j2\n")
    root = write_template("b.yaml.j2", "b: !include a.yaml.j2\n")
    with pytest.raises(JinjaboardTemplateError) as excinfo:
        _render(hass, root)
    assert "Include cycle detected" in str(excinfo.value)


def test_include_depth_cap_is_enforced(hass: HomeAssistant, write_template) -> None:
    # A straight (non-cyclic) chain longer than MAX_INCLUDE_DEPTH must still
    # fail cleanly rather than recursing indefinitely.
    write_template(f"level_{MAX_INCLUDE_DEPTH + 2}.yaml.j2", "leaf: true\n")
    root_path = None
    for i in range(MAX_INCLUDE_DEPTH + 2, 0, -1):
        path = write_template(
            f"level_{i - 1}.yaml.j2", f"next: !include level_{i}.yaml.j2\n"
        )
        if i == 1:
            root_path = path
    with pytest.raises(JinjaboardTemplateError) as excinfo:
        _render(hass, root_path)
    assert "Maximum include depth" in str(excinfo.value)


def test_missing_include_raises_include_not_found(
    hass: HomeAssistant, write_template
) -> None:
    root = write_template("root.yaml.j2", "cards: !include does_not_exist.yaml.j2\n")
    with pytest.raises(JinjaboardIncludeNotFoundError):
        _render(hass, root)


def test_include_traversal_is_rejected(hass: HomeAssistant, write_template) -> None:
    root = write_template(
        "root.yaml.j2", "cards: !include ../../../../../../etc/hostname\n"
    )
    with pytest.raises(JinjaboardPathError):
        _render(hass, root)


def test_nested_include_error_names_file_and_line(
    hass: HomeAssistant, write_template
) -> None:
    write_template("child.yaml.j2", "content: \"{{ totally_undefined }}\"\n")
    root = write_template(
        "root.yaml.j2", "cards:\n  - foo\n  - !include child.yaml.j2\n"
    )
    with pytest.raises(JinjaboardTemplateError) as excinfo:
        _render(hass, root)
    message = str(excinfo.value)
    assert "child.yaml.j2" in message
    assert "included at line 3" in message


def test_unrecognized_tag_becomes_yaml_error(
    hass: HomeAssistant, write_template
) -> None:
    root = write_template("root.yaml.j2", "views: !secret some_secret\n")
    with pytest.raises(JinjaboardYamlError):
        _render(hass, root)
