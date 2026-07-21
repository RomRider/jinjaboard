"""Tests for `macros:` resolution (macros.py) and `jjb.macros` exposure."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from custom_components.jinjaboard.errors import (
    JinjaboardIncludeNotFoundError,
    JinjaboardTemplateError,
)
from custom_components.jinjaboard.path_guard import JinjaboardPathError
from custom_components.jinjaboard.template_engine import render_template

import pytest


def _render(hass: HomeAssistant, path, **kwargs):
    return render_template(hass, path, path.read_text(), **kwargs)


def test_single_macro_file(hass: HomeAssistant, write_template) -> None:
    write_template(
        "macros/common.yaml.j2",
        "{% macro shout(x) %}{{ x | upper }}{% endmacro %}\n",
    )
    root = write_template("root.yaml.j2", "value: \"{{ jjb.macros.shout('hi') }}\"\n")
    result = _render(hass, root, macro_paths=["macros/common.yaml.j2"])
    assert result == {"value": "HI"}


def test_macro_directory_flattens_across_files(
    hass: HomeAssistant, write_template
) -> None:
    """Macros from different files in a declared directory all land in the
    same flat `jjb.macros` — the filename they came from doesn't matter."""
    write_template(
        "macros/common.yaml.j2",
        "{% macro shout(x) %}{{ x | upper }}{% endmacro %}\n",
    )
    write_template(
        "macros/nested/other.yaml.j2",
        "{% macro whisper(x) %}{{ x | lower }}{% endmacro %}\n",
    )
    root = write_template(
        "root.yaml.j2",
        "a: \"{{ jjb.macros.shout('hi') }}\"\n"
        "b: \"{{ jjb.macros.whisper('HI') }}\"\n",
    )
    result = _render(hass, root, macro_paths=["macros"])
    assert result == {"a": "HI", "b": "hi"}


def test_macro_can_use_dashboard_globals(hass: HomeAssistant, write_template) -> None:
    write_template(
        "macros/common.yaml.j2",
        "{% macro area() %}{{ jjb.globals.area_id }}{% endmacro %}\n",
    )
    root = write_template("root.yaml.j2", "value: \"{{ jjb.macros.area() }}\"\n")
    result = _render(
        hass, root, global_vars={"area_id": "kitchen"}, macro_paths=["macros/common.yaml.j2"]
    )
    assert result == {"value": "kitchen"}


def test_macro_can_call_ha_globals(hass: HomeAssistant, write_template) -> None:
    write_template(
        "macros/common.yaml.j2",
        "{% macro year() %}{{ now().year }}{% endmacro %}\n",
    )
    root = write_template("root.yaml.j2", "value: \"{{ jjb.macros.year() }}\"\n")
    result = _render(hass, root, macro_paths=["macros/common.yaml.j2"])
    assert result["value"].isdigit()


def test_macro_available_inside_include(hass: HomeAssistant, write_template) -> None:
    write_template(
        "macros/common.yaml.j2",
        "{% macro shout(x) %}{{ x | upper }}{% endmacro %}\n",
    )
    write_template("card.yaml.j2", "content: \"{{ jjb.macros.shout('hi') }}\"\n")
    root = write_template("root.yaml.j2", "cards:\n  - !include card.yaml.j2\n")
    result = _render(hass, root, macro_paths=["macros/common.yaml.j2"])
    assert result == {"cards": [{"content": "HI"}]}


def test_macro_cannot_see_inc_vars(hass: HomeAssistant, write_template) -> None:
    write_template(
        "macros/common.yaml.j2",
        "{% macro area() %}{{ jjb.inc.area_id }}{% endmacro %}\n",
    )
    root = write_template("root.yaml.j2", "value: \"{{ jjb.macros.area() }}\"\n")
    with pytest.raises(JinjaboardTemplateError):
        _render(hass, root, macro_paths=["macros/common.yaml.j2"])


def test_missing_macro_file(hass: HomeAssistant, write_template) -> None:
    root = write_template("root.yaml.j2", "ok: true\n")
    with pytest.raises(JinjaboardIncludeNotFoundError):
        _render(hass, root, macro_paths=["macros/missing.yaml.j2"])


def test_different_filenames_do_not_collide(hass: HomeAssistant, write_template) -> None:
    """Two files with the same filename in different directories used to
    collide when macros were keyed by filename — now filenames aren't part
    of `jjb.macros`'s namespace at all, only the macro names inside them."""
    write_template("macros/common.yaml.j2", "{% macro a() %}a{% endmacro %}\n")
    write_template("other_macros/common.yaml.j2", "{% macro b() %}b{% endmacro %}\n")
    root = write_template(
        "root.yaml.j2", "x: \"{{ jjb.macros.a() }}\"\ny: \"{{ jjb.macros.b() }}\"\n"
    )
    result = _render(
        hass,
        root,
        macro_paths=["macros/common.yaml.j2", "other_macros/common.yaml.j2"],
    )
    assert result == {"x": "a", "y": "b"}


def test_duplicate_macro_name_collision(hass: HomeAssistant, write_template) -> None:
    write_template("macros/a.yaml.j2", "{% macro dup() %}a{% endmacro %}\n")
    write_template("macros/b.yaml.j2", "{% macro dup() %}b{% endmacro %}\n")
    root = write_template("root.yaml.j2", "ok: true\n")
    with pytest.raises(JinjaboardTemplateError):
        _render(hass, root, macro_paths=["macros"])


def test_macro_path_traversal(hass: HomeAssistant, write_template) -> None:
    root = write_template("root.yaml.j2", "ok: true\n")
    with pytest.raises(JinjaboardPathError):
        _render(hass, root, macro_paths=["../../../../../../etc"])
