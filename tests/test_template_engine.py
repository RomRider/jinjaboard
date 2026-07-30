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


def test_globals_are_passed_through(hass: HomeAssistant, write_template) -> None:
    path = write_template("greet.yaml.j2", "value: {{ jjb.globals.name }}\n")
    result = render_template(hass, path, path.read_text(), global_vars={"name": "kitchen"})
    assert result == {"value": "kitchen"}


def test_globals_are_not_exposed_as_bare_names(
    hass: HomeAssistant, write_template
) -> None:
    """`globals` must only be reachable via `jjb.globals.<name>` — a bare
    top-level name would risk silently shadowing one of HA's own template
    globals, which is exactly what namespacing under `jjb` avoids."""
    path = write_template("greet.yaml.j2", "value: \"{{ name }}\"\n")
    with pytest.raises(JinjaboardTemplateError) as excinfo:
        render_template(hass, path, path.read_text(), global_vars={"name": "kitchen"})
    assert "name" in str(excinfo.value)


def test_variable_named_like_a_dict_method_is_not_shadowed(
    hass: HomeAssistant, write_template
) -> None:
    """A variable named e.g. `items` must resolve to its own value, not to
    `dict.items` — the reason `jjb.globals`/`jjb.inc` are `Namespace`s, not
    plain dicts."""
    path = write_template("greet.yaml.j2", "value: {{ jjb.globals.items }}\n")
    result = render_template(hass, path, path.read_text(), global_vars={"items": "not a method"})
    assert result == {"value": "not a method"}


def test_undefined_jjb_variable_supports_default_and_is_defined(
    hass: HomeAssistant, write_template
) -> None:
    """`jjb.globals.<name> | default(...)` / `jjb.globals.<name> is defined`
    must keep working for a name that was never declared in `globals`, the
    same guard idioms authors already rely on for plain undefined names."""
    path = write_template(
        "defaults.yaml.j2",
        "value: \"{{ jjb.globals.maybe_unset | default('fallback') }}\"\n"
        "flag: {{ jjb.globals.maybe_unset is defined }}\n",
    )
    result = render_template(hass, path, path.read_text(), global_vars={"name": "kitchen"})
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


def test_commented_out_jinja_is_not_rendered(
    hass: HomeAssistant, write_template
) -> None:
    """A whole-line YAML comment (`#...`) is meaningless to Jinja, so
    `{{ totally_undefined }}` inside one used to still raise even though the
    author's intent was to disable that line entirely."""
    path = write_template(
        "commented.yaml.j2",
        "# - !include does_not_exist.yaml.j2\n"
        "# {{ totally_undefined }}\n"
        "value: 1\n",
    )
    result = render_template(hass, path, path.read_text())
    assert result == {"value": 1}


def test_commented_out_jinja_preserves_line_numbers(
    hass: HomeAssistant, write_template
) -> None:
    """Comment lines are blanked, not deleted, so a real error further down
    the file still reports its original line number."""
    path = write_template(
        "commented.yaml.j2",
        "views:\n"
        "  - title: fine\n"
        "# a disabled line\n"
        "  - title: \"{{ totally_undefined }}\"\n",
    )
    with pytest.raises(JinjaboardTemplateError) as excinfo:
        render_template(hass, path, path.read_text())
    assert excinfo.value.line == 4


def test_indented_comment_line_is_blanked(
    hass: HomeAssistant, write_template
) -> None:
    path = write_template(
        "commented.yaml.j2",
        "cards:\n"
        "  - type: markdown\n"
        "    # {{ totally_undefined }}\n"
        "    content: hi\n",
    )
    result = render_template(hass, path, path.read_text())
    assert result == {"cards": [{"type": "markdown", "content": "hi"}]}


def test_hash_inside_literal_block_scalar_is_not_treated_as_comment(
    hass: HomeAssistant, write_template
) -> None:
    """Markdown cards routinely use `content: |` with a literal `#`
    heading — that must survive untouched, not get blanked out as if it
    were a YAML comment."""
    path = write_template(
        "markdown.yaml.j2",
        "content: |\n"
        "  # Heading\n"
        "  Some text\n",
    )
    result = render_template(hass, path, path.read_text())
    assert result == {"content": "# Heading\nSome text"}


def test_hash_inside_sequence_entry_block_scalar_is_not_treated_as_comment(
    hass: HomeAssistant, write_template
) -> None:
    path = write_template(
        "markdown.yaml.j2",
        "cards:\n"
        "  - |\n"
        "    # Heading\n"
        "    Some text\n",
    )
    result = render_template(hass, path, path.read_text())
    assert result == {"cards": ["# Heading\nSome text"]}


def test_standalone_multiline_macro_call_is_reindented(
    hass: HomeAssistant, write_template
) -> None:
    """A `{% macro %}` body is always written starting at column 0 (it has
    no call site of its own) — calling it from a standalone
    `{{ macro(...) }}` line further down the same file used to splice that
    column-0 text in unmodified past the first line, breaking the YAML
    structure it was meant to nest under. This is the exact shape of the
    bug reported against `.devcontainer/test/jinjaboard/hello.yaml.j2`."""
    path = write_template(
        "hello.yaml.j2",
        "{% macro card(title) %}\n"
        "- type: markdown\n"
        "  content: |\n"
        "    # {{ title }}\n"
        "    second line\n"
        "{% endmacro %}\n"
        "views:\n"
        "  - title: Home\n"
        "    cards:\n"
        "      - type: markdown\n"
        "        content: existing\n"
        "      {{ card('Macro Test') }}\n",
    )
    result = render_template(hass, path, path.read_text())
    assert result == {
        "views": [
            {
                "title": "Home",
                "cards": [
                    {"type": "markdown", "content": "existing"},
                    {
                        "type": "markdown",
                        "content": "# Macro Test\nsecond line",
                    },
                ],
            }
        ]
    }


def test_standalone_macro_call_as_sequence_marker_is_reindented(
    hass: HomeAssistant, write_template
) -> None:
    """`{{ macro(...) }}` used directly as the `- ` sequence marker itself
    (rather than after an existing `- `) must reindent continuation lines
    to the column right after `- `, not to the column of the dash."""
    path = write_template(
        "hello.yaml.j2",
        "{% macro card(title) %}\n"
        "- type: markdown\n"
        "  content: |\n"
        "    {{ title }}\n"
        "{% endmacro %}\n"
        "cards:\n"
        "  {{ card('hi') }}\n",
    )
    result = render_template(hass, path, path.read_text())
    assert result == {"cards": [{"type": "markdown", "content": "hi"}]}


def test_standalone_non_string_expression_still_renders(
    hass: HomeAssistant, write_template
) -> None:
    """A standalone `{{ expr }}` line whose value isn't already a `str`
    (e.g. a bare `bool`) must keep working — `indent`'s own implementation
    requires a `str` input, so the reindent rewrite must coerce to string
    first rather than newly breaking non-string standalone expressions."""
    path = write_template(
        "flags.yaml.j2",
        "flag:\n"
        "  {{ jjb.globals.enabled }}\n",
    )
    result = render_template(hass, path, path.read_text(), global_vars={"enabled": True})
    assert result == {"flag": True}


def test_multiple_expressions_on_one_line_are_left_untouched(
    hass: HomeAssistant, write_template
) -> None:
    """A line mixing literal text with more than one expression isn't
    shaped like a macro call site at all, and must render exactly as
    before this feature existed."""
    path = write_template(
        "room.yaml.j2",
        "content: \"Room: {{ jjb.globals.name }}, Temp: {{ jjb.globals.temp }}\"\n",
    )
    result = render_template(
        hass, path, path.read_text(), global_vars={"name": "Kitchen", "temp": 21}
    )
    assert result == {"content": "Room: Kitchen, Temp: 21"}


def test_raw_block_expression_is_not_reindented(
    hass: HomeAssistant, write_template
) -> None:
    """`{% raw %}...{% endraw %}` is Jinja's own escape hatch for literal
    `{{ }}` text — e.g. documentation showing Jinja syntax itself — and
    must render completely unevaluated, not get rewritten into an
    `| indent(...)` call by the standalone-expression reindent pass before
    Jinja even sees it."""
    path = write_template(
        "docs.yaml.j2",
        "content: |\n"
        "  Example:\n"
        "  {% raw %}\n"
        "  {{ jjb.globals.name }}\n"
        "  {% endraw %}\n",
    )
    result = render_template(hass, path, path.read_text(), global_vars={"name": "kitchen"})
    assert result == {"content": "Example:\n\n{{ jjb.globals.name }}"}


def test_raw_block_containing_dash_expression_is_not_reindented(
    hass: HomeAssistant, write_template
) -> None:
    """Same as above but for the `- {{ ... }}` sequence-marker shape, to
    make sure the raw-block guard applies regardless of what the
    (unevaluated) literal text on that line looks like."""
    path = write_template(
        "docs.yaml.j2",
        "content: |\n"
        "  {% raw %}\n"
        "  - {{ macro_call() }}\n"
        "  {% endraw %}\n",
    )
    result = render_template(hass, path, path.read_text())
    assert result == {"content": "\n- {{ macro_call() }}"}


def test_trailing_inline_comment_is_left_untouched(
    hass: HomeAssistant, write_template
) -> None:
    """Only whole-line comments are recognized — a trailing `# comment`
    after real content is out of scope (distinguishing it from a `#`
    inside a quoted scalar needs real YAML parsing), so it's simply
    rendered as part of the line like any other text, same as before this
    feature existed."""
    path = write_template(
        "trailing.yaml.j2",
        "value: 1 # not stripped, left for the YAML parser\n",
    )
    result = render_template(hass, path, path.read_text())
    assert result == {"value": 1}
