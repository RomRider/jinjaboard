"""Render JinjaBoard templates through Home Assistant's own Jinja2 engine."""

from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Any

import jinja2.exceptions
import yaml
from jinja2.utils import Namespace

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import TemplateError
from homeassistant.helpers.template import Template
from homeassistant.util.async_ import run_callback_threadsafe

from .errors import JinjaboardTemplateError, JinjaboardYamlError
from .includes import parse_with_includes
from .macros import build_macro_namespace

# Re-exported for websocket.py / callers that only need the exception types,
# so most of the codebase can import them from here rather than .errors.
__all__ = [
    "JinjaboardTemplateError",
    "JinjaboardYamlError",
    "render_template",
]


def _lineno_from_jinja_error(original: BaseException) -> int | None:
    """Recover the template source line number from a raw Jinja exception.

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
    if (lineno := getattr(original, "lineno", None)) is not None:
        return lineno
    line: int | None = None
    tb = original.__traceback__
    while tb is not None:
        if tb.tb_frame.f_code.co_filename == "<template>":
            line = tb.tb_lineno
        tb = tb.tb_next
    return line


def _extract_lineno(err: TemplateError) -> int | None:
    """Recover the template source line number from a wrapped Jinja error.

    `homeassistant.exceptions.TemplateError.__init__` only keeps a string
    message — it discards the original Jinja/Python exception except as
    `__cause__` (`raise TemplateError(err) from err` in
    `Template.async_render`). That original exception is still where the
    line number lives — see `_lineno_from_jinja_error` for how it's dug out.
    """
    original = err.__cause__
    if original is None:
        return None
    return _lineno_from_jinja_error(original)


# Matches a line that *starts* a YAML block scalar: `key: |`, `- >`,
# `- key: |2-`, etc. — a `|`/`>` indicator, with optional chomping
# (`+`/`-`) and explicit indentation digit in either order, as the last
# thing on the line after an optional `- ` sequence marker and/or `key:`.
_BLOCK_SCALAR_START_RE = re.compile(
    r"^[ \t]*(?:-\s*)?(?:[^:\n]*:\s*)?[|>][+\-0-9]*[ \t]*$"
)


def _blank_out_comment_lines(source: str) -> str:
    """Replace whole-line YAML comments with a blank line, before Jinja
    ever sees `source`.

    Motivation: `#` means nothing to Jinja, only to YAML — a line commented
    out to disable it (`# - !include foo.yaml.j2`, `# {{ maybe_undefined
    }}`) still gets its `{{ }}`/`{% %}` evaluated, so "dead" code could
    still raise `UndefinedError`/`TemplateError`, which is surprising: the
    author's intent was to remove that line from consideration entirely.

    Comments are blanked, not deleted — the line count of `source` is
    preserved exactly, so `_extract_lineno` and YAML-parse-error line
    numbers still point at the right line in the original file with zero
    extra bookkeeping.

    This is a line-based heuristic, not a real YAML parse: this project's
    own `{% for %}`-generated list/dict entries mean the pre-render source
    is routinely not valid, tokenizable YAML at all, so a real
    comment-aware scan isn't available before Jinja has already run. The
    one YAML construct this still needs to respect is block scalars
    (`content: |`, `content: >`, and their `- |`/`- >` sequence-entry
    form) — markdown cards' `content: |` blocks routinely contain literal
    `#` headings, and blanking those out would corrupt real card content,
    not just suppress a comment. Only whole-line comments are recognized
    (a line whose first non-whitespace character is `#`); a trailing
    `key: value  # comment` is left untouched, since telling that `#` apart
    from one inside a quoted scalar (`key: "a # b"`) needs real YAML
    parsing this function deliberately doesn't do.
    """
    lines = source.splitlines(keepends=True)
    out: list[str] = []
    block_scalar_indent: int | None = None
    for line in lines:
        body = line.rstrip("\r\n")
        indent = len(body) - len(body.lstrip(" \t"))
        content = body.strip()

        if block_scalar_indent is not None:
            if content == "" or indent > block_scalar_indent:
                out.append(line)
                continue
            block_scalar_indent = None  # scalar ended; re-check this line below

        if content.startswith("#"):
            out.append(line[len(body):])  # keep only the original line ending
            continue

        if _BLOCK_SCALAR_START_RE.match(body):
            block_scalar_indent = indent

        out.append(line)
    return "".join(out)


def _render_jinja(
    hass: HomeAssistant,
    source: str,
    global_vars: dict[str, Any] | None,
    inc_vars: dict[str, Any] | None,
    macro_vars: dict[str, Any] | None,
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
        return _render_jinja_on_loop(hass, source, global_vars, inc_vars, macro_vars)
    return run_callback_threadsafe(
        hass.loop,
        _render_jinja_on_loop,
        hass,
        source,
        global_vars,
        inc_vars,
        macro_vars,
    ).result()


def _render_jinja_on_loop(
    hass: HomeAssistant,
    source: str,
    global_vars: dict[str, Any] | None,
    inc_vars: dict[str, Any] | None,
    macro_vars: dict[str, Any] | None,
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

    Dashboard-declared `globals` (`global_vars`) and `!include ... vars:`
    (`inc_vars`) are exposed as `jjb.globals.<name>` / `jjb.inc.<name>`, not
    as bare top-level names — HA's template environment already defines a
    large set of its own globals (`states`, `now`, `area_id`, ...), and a
    `globals:`/`vars:` entry that happened to reuse one of those names
    would silently shadow it instead of erroring. They're also kept in two
    separate sub-namespaces rather than one merged `jjb.<name>`: an
    `!include`'s `vars:` used to be merged straight into the same dict as
    the dashboard's own `globals`, which meant a per-include override
    could silently shadow a dashboard-level variable of the same name.
    `jinja2.utils.Namespace` (the same object `{% set ns = namespace() %}`
    produces) is used for `jjb`, `jjb.globals`, and `jjb.inc` rather than a
    plain dict so that a variable named e.g. `items` or `get` can't be
    shadowed by dict's own built-in methods of the same name — attribute
    access on a Namespace always resolves to the stored value, and correctly
    raises under `strict=True` for a genuinely undefined/misspelled one.

    `macro_vars` (dashboard-declared `macros:`, see `macros.py`) is exposed
    the same way, as `jjb.macros.<macro_name>(...)` — flattened across every
    declared file by `macros.build_macro_namespace`, so which file a macro
    was defined in doesn't matter to how it's called. Wrapping the flat
    `{name: Macro}` dict in a `Namespace` is enough to get `jjb.macros.<name>`
    working the same as `jjb.globals`/`jjb.inc`.

    `source` has whole-line YAML comments blanked out first (see
    `_blank_out_comment_lines`) so a commented-out line's `{{ }}`/`{% %}`
    doesn't raise for code the author meant to disable.
    """
    template = Template(_blank_out_comment_lines(source), hass)
    try:
        return template.async_render(
            {
                "jjb": Namespace(
                    globals=Namespace(global_vars or {}),
                    inc=Namespace(inc_vars or {}),
                    macros=Namespace(macro_vars or {}),
                )
            },
            parse_result=False,
            strict=True,
        )
    except TemplateError as err:
        raise JinjaboardTemplateError(str(err), line=_extract_lineno(err)) from err


def _compile_macro_module(
    hass: HomeAssistant, source: str, global_vars: dict[str, Any] | None
) -> Any:
    """Compile a macro file, safe to call from any thread.

    Injected into `macros.build_macro_namespace` as the `CompileMacroModule`
    callback (avoids a circular import between this module and `macros.py`,
    the same reason `render_and_parse` is injected into `includes.py`
    instead of imported there). Same on-loop/off-loop thread dispatch as
    `_render_jinja` — see its docstring for why.
    """
    if threading.get_ident() == hass.loop_thread_id:
        return _compile_macro_module_on_loop(hass, source, global_vars)
    return run_callback_threadsafe(
        hass.loop, _compile_macro_module_on_loop, hass, source, global_vars
    ).result()


def _compile_macro_module_on_loop(
    hass: HomeAssistant, source: str, global_vars: dict[str, Any] | None
) -> Any:
    """Compile a macro file and return its `jinja2.TemplateModule`.

    Called once per declared `macros:` entry (see `macros.py`) rather than
    per-render — the resulting module's macros are reused, unevaluated,
    across the whole render tree until the next `jinjaboard/render` call.

    Reaches into `Template._ensure_compiled` (underscore-private, same class
    of risk as `frontend.py`'s `hass.data[LOVELACE_DATA]` reach-in) because
    HA's `Template` class only exposes `async_render()` -> `str`, never the
    underlying `jinja2.Template` a macro file needs to be compiled to. Once
    compiled, `.make_module(vars)` is public `jinja2` API — confirmed
    (throwaway repro, since removed) to return a `TemplateModule` whose
    macros are callable attributes, bound to the same shared environment
    globals (`states`, `now`, `area_id`, ...) as every other render, since
    `_ensure_compiled` binds to `self._env` (the same per-`hass` cached
    `TemplateEnvironment` `Template.async_render` itself uses).

    Only `jjb.globals` is available inside a macro body, not `jjb.inc`: a
    macro module is compiled once, upfront, before any `!include` tree walk
    starts contributing `inc` vars, so there is no meaningful `inc` value to
    give it — see `macros.py`'s module docstring.

    Must run on the event loop for the same reason `_render_jinja_on_loop`
    must: `_ensure_compiled`/`make_module` execute compiled Jinja bytecode,
    which can call loop-bound HA globals like `now()`/`states()`.

    Two separate except clauses below, not one: `_ensure_compiled` (via
    `Template.ensure_valid`) catches raw `jinja2.TemplateError` itself and
    re-raises it as HA's own `homeassistant.exceptions.TemplateError` — but
    only for *syntax* errors caught at compile time. `make_module` executes
    the module's top-level code directly against raw jinja2 (there is no
    HA-level equivalent of `Template.async_render`'s own wrapping for this
    call), so a *runtime* error there — e.g. a stray top-level `{{ some_name
    }}` outside any `{% macro %}` block, which macro-body references
    themselves never trigger since a macro's body only runs when called —
    surfaces as a raw jinja2 exception instead. Without the second clause
    that raw exception would propagate all the way out of the executor job
    unhandled, instead of becoming a clean `template_error`.

    That second clause also has to explicitly re-run the exception through
    `Environment.handle_exception()` (confirmed live via a pure-jinja2
    repro, no HA involved) before `_lineno_from_jinja_error` can trust the
    traceback: the `<template>` frame `_lineno_from_jinja_error` looks for
    is only mapped back to the *template source* line by Jinja's own
    `debug.rewrite_traceback_stack`, which normally runs as part of
    `Template.render`/`generate`'s own exception handling — `make_module`
    bypasses that entirely, so its raw traceback's `<template>` frame is
    actually a line number into Jinja's *generated Python* for the compiled
    template (imports, the `root()` function wrapper, macro defs, ...),
    which has no 1:1 relationship to the original source. Without this,
    the reported line number is silently wrong rather than merely absent —
    worse than not showing one at all.
    """
    template = Template(_blank_out_comment_lines(source), hass)
    try:
        compiled = template._ensure_compiled(strict=True)  # noqa: SLF001
        return compiled.make_module(
            {"jjb": Namespace(globals=Namespace(global_vars or {}), inc=Namespace({}))}
        )
    except TemplateError as err:
        raise JinjaboardTemplateError(str(err), line=_extract_lineno(err)) from err
    except jinja2.exceptions.TemplateError:
        try:
            template._env.handle_exception()  # noqa: SLF001
        except jinja2.exceptions.TemplateError as rewritten:
            raise JinjaboardTemplateError(
                str(rewritten), line=_lineno_from_jinja_error(rewritten)
            ) from rewritten


def _render_and_parse(
    hass: HomeAssistant,
    path: Path,
    source: str,
    global_vars: dict[str, Any] | None,
    inc_vars: dict[str, Any] | None,
    macro_vars: dict[str, Any] | None,
    include_stack: list[Path],
) -> Any:
    """Render `source` (already read from `path`) and parse it as YAML.

    Shared by the root template and, recursively, every `!include`d file —
    `includes.py`'s tag constructors call back into this function for each
    included path (passed in as `render_and_parse`, not imported directly,
    to avoid a circular import between this module and `includes.py`).

    `global_vars` is the dashboard's own `globals:`, constant for the
    whole render tree. `inc_vars` accumulates `!include ... vars:` as the
    tree is walked — see `includes.py`'s `_render_included_file` for how
    it's layered. `macro_vars` (the dashboard's own `macros:`, see
    `macros.py`) is likewise constant for the whole tree, built once by
    `render_template` before any include is walked.
    """
    raw = _render_jinja(hass, source, global_vars, inc_vars, macro_vars)
    try:
        return parse_with_includes(
            hass,
            raw,
            path.parent,
            global_vars,
            inc_vars,
            macro_vars,
            include_stack,
            _render_and_parse,
        )
    except yaml.YAMLError as err:
        raise JinjaboardYamlError(raw) from err


def render_template(
    hass: HomeAssistant,
    path: Path,
    source: str,
    global_vars: dict[str, Any] | None = None,
    macro_paths: list[str] | None = None,
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
    stack. `global_vars` becomes the render tree's `jjb.globals` — no
    `!include` has contributed `jjb.inc` vars yet, so that starts at `None`.
    `macro_paths` (the dashboard's own `macros:`) is resolved once, up front,
    into `jjb.macros` (see `macros.build_macro_namespace`) — unlike
    `jjb.inc`, it never changes as the include tree is walked.
    """
    macro_vars = build_macro_namespace(hass, macro_paths, global_vars, _compile_macro_module)
    return _render_and_parse(
        hass, path, source, global_vars, None, macro_vars, include_stack=[path.resolve()]
    )
