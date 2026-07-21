"""Render JinjaBoard templates through Home Assistant's own Jinja2 engine."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, TemplateError
from homeassistant.helpers.template import Template
from homeassistant.util.yaml.loader import parse_yaml


class JinjaboardError(Exception):
    """Base error for JinjaBoard template rendering."""


class JinjaboardTemplateError(JinjaboardError):
    """Raised when Jinja2 rendering itself fails (bad syntax, runtime error)."""

    def __init__(self, message: str, line: int | None = None) -> None:
        super().__init__(message)
        self.line = line


class JinjaboardYamlError(JinjaboardError):
    """Raised when the rendered output is not valid YAML."""

    def __init__(self, raw_output: str) -> None:
        super().__init__("Rendered template output was not valid YAML")
        self.raw_output = raw_output


def _extract_lineno(err: TemplateError) -> int | None:
    """Recover the template source line number from a wrapped Jinja error.

    `homeassistant.exceptions.TemplateError.__init__` only keeps a string
    message — it discards the original Jinja/Python exception except as
    `__cause__` (`raise TemplateError(err) from err` in
    `Template.async_render`). That original exception is still where the
    line number lives:
    - `jinja2.exceptions.TemplateSyntaxError` (bad `{% %}`/`{{ }}` syntax)
      carries `.lineno` directly, set by the parser.
    - Runtime errors (e.g. `UndefinedError`) don't have `.lineno`, but
      Jinja's `environment.handle_exception()` rewrites the traceback
      before re-raising so that frames from compiled template bytecode are
      replaced with fake frames pointing at the *template source* line
      (`debug.py:rewrite_traceback_stack`, using
      `template.get_corresponding_lineno`) — those frames are tagged with
      the filename `"<template>"` since we don't pass a real one into
      `env.compile()`. Walking the traceback for that filename recovers
      the line.
    """
    original = err.__cause__
    if original is None:
        return None
    if (lineno := getattr(original, "lineno", None)) is not None:
        return lineno
    line: int | None = None
    tb = original.__traceback__
    while tb is not None:
        if tb.tb_frame.f_code.co_filename == "<template>":
            line = tb.tb_lineno
        tb = tb.tb_next
    return line


def render_template(
    hass: HomeAssistant, source: str, variables: dict[str, Any] | None = None
) -> Any:
    """Render `source` as an HA Jinja2 template and parse the result as YAML.

    `source` is authored as YAML with embedded Jinja (`{{ }}` / `{% %}`) —
    the same convention lovelace_gen used — not a template whose Jinja body
    directly constructs the output structure. We render it to a plain string
    first (with `parse_result=False`, since `Template.async_render`'s own
    result parsing uses `ast.literal_eval` and isn't what we want here
    either), then parse that string as YAML.

    `strict=True` is required: HA's default undefined-variable behavior
    (`LoggingUndefined`) just logs "Template variable warning" and renders
    the undefined value as empty, so a typo'd variable name would silently
    produce a broken/blank dashboard instead of surfacing an error. Strict
    mode swaps in `jinja2.StrictUndefined`, which raises on any undefined
    access — caught below and turned into the same `template_error` path
    as a syntax error, so it reaches the dashboard's error card instead of
    only the HA log.
    """
    template = Template(source, hass)
    try:
        raw = template.async_render(variables, parse_result=False, strict=True)
    except TemplateError as err:
        raise JinjaboardTemplateError(str(err), line=_extract_lineno(err)) from err

    try:
        return parse_yaml(raw)
    except HomeAssistantError as err:
        raise JinjaboardYamlError(raw) from err
