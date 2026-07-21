"""Tests for template_engine.render_template.

`_extract_lineno`'s two code paths (direct `.lineno` on a
`TemplateSyntaxError` vs. traceback-walking for a runtime `UndefinedError`)
are exercised indirectly through `render_template`, rather than by
hand-constructing fake exceptions — a real render produces a real traceback,
which is what the line-number recovery actually depends on.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from homeassistant.core import HomeAssistant

from custom_components.jinjaboard.errors import (
    JinjaboardTemplateError,
    JinjaboardYamlError,
)
from custom_components.jinjaboard.template_engine import render_template


def test_renders_plain_yaml_with_jinja(hass: HomeAssistant, write_template) -> None:
    path = write_template(
        "home.yaml.j2",
        "views:\n  - title: \"{{ 'Jinja' + 'Board' }}\"\n",
    )
    result = render_template(hass, path, path.read_text())
    assert result == {"views": [{"title": "JinjaBoard"}]}


def test_variables_are_passed_through(hass: HomeAssistant, write_template) -> None:
    path = write_template("greet.yaml.j2", "value: {{ jjb.name }}\n")
    result = render_template(hass, path, path.read_text(), variables={"name": "kitchen"})
    assert result == {"value": "kitchen"}


def test_variables_are_not_exposed_as_bare_names(
    hass: HomeAssistant, write_template
) -> None:
    """`variables` must only be reachable via `jjb.<name>` — a bare
    top-level name would risk silently shadowing one of HA's own template
    globals, which is exactly what namespacing under `jjb` avoids."""
    path = write_template("greet.yaml.j2", "value: \"{{ name }}\"\n")
    with pytest.raises(JinjaboardTemplateError) as excinfo:
        render_template(hass, path, path.read_text(), variables={"name": "kitchen"})
    assert "name" in str(excinfo.value)


def test_variable_named_like_a_dict_method_is_not_shadowed(
    hass: HomeAssistant, write_template
) -> None:
    """A variable named e.g. `items` must resolve to its own value, not to
    `dict.items` — the reason `jjb` is a `Namespace`, not a plain dict."""
    path = write_template("greet.yaml.j2", "value: {{ jjb.items }}\n")
    result = render_template(hass, path, path.read_text(), variables={"items": "not a method"})
    assert result == {"value": "not a method"}


def test_undefined_jjb_variable_supports_default_and_is_defined(
    hass: HomeAssistant, write_template
) -> None:
    """`jjb.<name> | default(...)` / `jjb.<name> is defined` must keep
    working for a name that was never declared in `variables`, the same
    guard idioms authors already rely on for plain undefined names."""
    path = write_template(
        "defaults.yaml.j2",
        "value: \"{{ jjb.maybe_unset | default('fallback') }}\"\n"
        "flag: {{ jjb.maybe_unset is defined }}\n",
    )
    result = render_template(hass, path, path.read_text(), variables={"name": "kitchen"})
    assert result == {"value": "fallback", "flag": False}


def test_undefined_variable_raises_with_correct_line(
    hass: HomeAssistant, write_template
) -> None:
    path = write_template(
        "broken.yaml.j2",
        "views:\n  - title: fine\n  - title: \"{{ totally_undefined }}\"\n",
    )
    with pytest.raises(JinjaboardTemplateError) as excinfo:
        render_template(hass, path, path.read_text())
    assert excinfo.value.line == 3
    assert "totally_undefined" in str(excinfo.value)


def test_jinja_syntax_error_raises_with_correct_line(
    hass: HomeAssistant, write_template
) -> None:
    path = write_template(
        "syntax_error.yaml.j2",
        "views:\n  - title: fine\n  {% for i in [1,2,3] %}\n  - title: unterminated\n",
    )
    with pytest.raises(JinjaboardTemplateError) as excinfo:
        render_template(hass, path, path.read_text())
    assert excinfo.value.line == 3


def test_invalid_yaml_output_raises_yaml_error(
    hass: HomeAssistant, write_template
) -> None:
    path = write_template(
        "bad_indent.yaml.j2",
        "views:\n  - title: Broken\n    cards:\n    - type: markdown\n        content: bad\n",
    )
    with pytest.raises(JinjaboardYamlError) as excinfo:
        render_template(hass, path, path.read_text())
    assert "title: Broken" in excinfo.value.raw_output


def test_strict_mode_does_not_break_default_filter(
    hass: HomeAssistant, write_template
) -> None:
    """`| default(...)` and `is defined` must keep working under strict=True —
    only genuinely undefined *access* should raise, not the defined-check
    idioms authors use to guard against it."""
    path = write_template(
        "defaults.yaml.j2",
        "value: \"{{ maybe_unset | default('fallback') }}\"\n"
        "flag: {{ maybe_unset is defined }}\n",
    )
    result = render_template(hass, path, path.read_text())
    assert result == {"value": "fallback", "flag": False}
