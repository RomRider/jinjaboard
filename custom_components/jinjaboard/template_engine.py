"""Render JinjaBoard templates through Home Assistant's own Jinja2 engine."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import yaml
from jinja2.utils import Namespace

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import TemplateError
from homeassistant.helpers.template import Template
from homeassistant.util.async_ import run_callback_threadsafe

from .errors import JinjaboardTemplateError, JinjaboardYamlError
from .includes import parse_with_includes

# Re-exported for websocket.py / callers that only need the exception types,
# so most of the codebase can import them from here rather than .errors.
__all__ = [
    "JinjaboardTemplateError",
    "JinjaboardYamlError",
    "render_template",
]


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


def _render_jinja(
    hass: HomeAssistant, source: str, variables: dict[str, Any] | None
) -> str:
    """Render `source` through Jinja, safe to call from any thread.

    `render_template` (below) is invoked via `hass.async_add_executor_job`
    from `websocket.py` so that the blocking file I/O `!include`/
    `!include_dir_*` resolution does (see `includes.py`) doesn't run on the
    event loop. But `_render_jinja_on_loop`'s `Template.async_render` call
    must run on the loop regardless (its own docstring: "This method must
    be run in the event loop"). So this checks which thread it's on —
    the same idiom `homeassistant/core.py` itself uses in several places
    (e.g. `StateMachine.entity_ids`/`async_entity_ids`) — and hops back via
    `run_callback_threadsafe` only when actually off the loop. Tests call
    `render_template` directly on the loop thread (no executor job), so
    they take the direct branch, unchanged.
    """
    if threading.get_ident() == hass.loop_thread_id:
        return _render_jinja_on_loop(hass, source, variables)
    return run_callback_threadsafe(
        hass.loop, _render_jinja_on_loop, hass, source, variables
    ).result()


def _render_jinja_on_loop(
    hass: HomeAssistant, source: str, variables: dict[str, Any] | None
) -> str:
    """Render `source` through Jinja only, returning the raw rendered string.

    This method must be run in the event loop (see `_render_jinja` above) —
    it calls `Template.async_render`, which requires it.

    `strict=True` is required: HA's default undefined-variable behavior
    (`LoggingUndefined`) just logs "Template variable warning" and renders
    the undefined value as empty, so a typo'd variable name would silently
    produce a broken/blank dashboard instead of surfacing an error. Strict
    mode swaps in `jinja2.StrictUndefined`, which raises on any undefined
    access — caught below and turned into the same `template_error` path
    as a syntax error, so it reaches the dashboard's error card instead of
    only the HA log.

    Dashboard-declared `variables` are exposed as `jjb.<name>`, not as bare
    top-level names — HA's template environment already defines a large set
    of its own globals (`states`, `now`, `area_id`, ...), and a `variables:`
    entry that happened to reuse one of those names would silently shadow it
    instead of erroring. `jinja2.utils.Namespace` (the same object `{% set ns
    = namespace() %}` produces) is used rather than a plain dict so that a
    variable named e.g. `items` or `get` can't be shadowed by dict's own
    built-in methods of the same name — attribute access on a Namespace
    always resolves to the stored value, and correctly raises under
    `strict=True` for a genuinely undefined/misspelled one.
    """
    template = Template(source, hass)
    try:
        return template.async_render(
            {"jjb": Namespace(variables or {})}, parse_result=False, strict=True
        )
    except TemplateError as err:
        raise JinjaboardTemplateError(str(err), line=_extract_lineno(err)) from err


def _render_and_parse(
    hass: HomeAssistant,
    path: Path,
    source: str,
    variables: dict[str, Any] | None,
    include_stack: list[Path],
) -> Any:
    """Render `source` (already read from `path`) and parse it as YAML.

    Shared by the root template and, recursively, every `!include`d file —
    `includes.py`'s tag constructors call back into this function for each
    included path (passed in as `render_and_parse`, not imported directly,
    to avoid a circular import between this module and `includes.py`).
    """
    raw = _render_jinja(hass, source, variables)
    try:
        return parse_with_includes(
            hass, raw, path.parent, variables, include_stack, _render_and_parse
        )
    except yaml.YAMLError as err:
        raise JinjaboardYamlError(raw) from err


def render_template(
    hass: HomeAssistant,
    path: Path,
    source: str,
    variables: dict[str, Any] | None = None,
) -> Any:
    """Render `source` (the file at `path`) as YAML with embedded Jinja.

    `source` is authored as YAML with embedded Jinja (`{{ }}` / `{% %}`) —
    the same convention lovelace_gen used — not a template whose Jinja body
    directly constructs the output structure. It's rendered to a plain
    string first (with `parse_result=False`, since `Template.async_render`'s
    own result parsing uses `ast.literal_eval` and isn't what we want here
    either), then that string is parsed as YAML — resolving any
    `!include`/`!include_dir_*` tags it contains along the way (see
    `includes.py`).

    `path` anchors relative `!include` targets to this file's own directory
    (matching real Home Assistant's `!include`) and seeds the cycle-detection
    stack.
    """
    return _render_and_parse(hass, path, source, variables, include_stack=[path.resolve()])
