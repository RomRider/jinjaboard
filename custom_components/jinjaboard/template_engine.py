"""Render JinjaBoard templates through Home Assistant's own Jinja2 engine."""

from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Any, cast

import jinja2.exceptions
import yaml
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import TemplateError
from homeassistant.helpers.template import Template
from homeassistant.util.async_ import run_callback_threadsafe
from jinja2.utils import Namespace

from .errors import JinjaboardGlobalsError, JinjaboardTemplateError, JinjaboardYamlError
from .globals_file import resolve_global_vars
from .includes import parse_with_includes
from .macros import build_macro_namespace
from .path_guard import config_relative_display_path

# Re-exported for websocket.py / callers that only need the exception types,
# so most of the codebase can import them from here rather than .errors.
__all__ = [
    "JinjaboardGlobalsError",
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


# Matches a line that is *only* a single `{{ expr }}` expression (with an
# arbitrary prefix before it, e.g. a YAML `- ` sequence marker, and nothing
# but trailing whitespace after) — the shape a macro call or an `!include`-
# style "whole value comes from this expression" line always has. The
# lookaround pair around each `{{`/`}}` bails out (leaves the line untouched)
# for Jinja's own `{{- -}}` whitespace-control markers, which this project's
# own fixtures/tests/README never use — rather than risk mangling one.
_STANDALONE_EXPR_RE = re.compile(
    r"^(?P<prefix>[^\n]*?)\{\{(?!-)(?P<expr>(?:(?!\}\}).)*?)(?<!-)\}\}"
    r"(?P<suffix>[ \t]*)$"
)

# `{% raw %}...{% endraw %}` is Jinja's own escape hatch for literal `{{ }}`/
# `{% %}` text that must NOT be evaluated at all (e.g. documentation showing
# Jinja syntax itself). These are matched with a plain substring search, not
# anchored to a whole line, since unlike a macro call site there's no reason
# to assume either tag sits alone on its own line.
_RAW_OPEN_RE = re.compile(r"\{%-?\s*raw\s*-?%\}")
_RAW_CLOSE_RE = re.compile(r"\{%-?\s*endraw\s*-?%\}")


def _reindent_standalone_expressions(source: str) -> str:
    """Rewrite a standalone `{{ expr }}` line so a multi-line `expr` result
    lands reindented to the column that expression starts at, before Jinja
    ever renders it.

    Jinja does not do this itself: only the *first* line of a multi-line
    expression result inherits the raw text already on that source line
    before `{{` (e.g. the call site's own leading whitespace) — every
    subsequent line keeps whatever literal indentation was written inside
    the expression's own source (e.g. a `{% macro %}` body, always written
    starting at column 0 since it has no "call site" of its own). Splicing
    that unmodified into an indented YAML structure produces lines that no
    longer nest under their intended parent — this was reproduced literally
    breaking YAML parsing (`hello.yaml.j2`'s `test('Macro Test')` macro) and,
    less obviously, silently producing a *wrong but still parseable* result
    (this project's own README `light_tile` example, which turned out to
    already suffer from exactly this before this function existed).

    The fix is Jinja's own built-in `indent` filter, applied automatically:
    `{{ expr }}` becomes `{{ (expr) | string | indent(N) }}`, where `N` is
    the number of characters before `{{` on the source line — the same
    column subsequent lines need to start at to nest correctly, whether
    that prefix is plain whitespace or e.g. a `- ` sequence marker. The
    `| string` is required, not cosmetic: `indent`'s own implementation
    does `s += "\n"` internally, which raises `TypeError` for anything that
    isn't already a `str` — but an ordinary `{{ expr }}` (with no `indent`
    involved) never required `expr` to be a string, since Jinja's own
    output writer stringifies whatever it gets. Without this, a standalone
    `{{ jjb.user.is_admin }}` (a `bool`) or any other non-`str` expression
    on its own line would newly break. `indent`'s own defaults (`first=False`,
    i.e. don't touch the first line — it already gets that same prefix for
    free, literally, from the surrounding template text; `blank=False`,
    i.e. don't pad already-blank lines) are exactly what's wanted here.
    This whole rewrite is a no-op for a single-line `expr` result (nothing
    for `indent` to do past a lone first line, and `| string` matches
    Jinja's own implicit stringification), so it's safe to apply
    unconditionally to every matching line, not just ones that are known in
    advance to be macro calls.

    Only lines that are *entirely* one `{{ expr }}` (see `_STANDALONE_EXPR_RE`)
    are rewritten — a line like `content: "Room: {{ a }}, {{ b }}°C"` isn't
    shaped like a call site at all (multiple expressions, literal text
    around them) and is left untouched, same as it always would be.

    Lines inside a `{% raw %}...{% endraw %}` block are never rewritten,
    tracked the same line-scanning way `_blank_out_comment_lines` tracks
    block-scalar state: `{{ x }}` in there is literal output text Jinja
    itself never evaluates as an expression at all, since that's the whole
    point of `raw` — rewriting it here, before Jinja ever sees `source`,
    would corrupt exactly the text `raw` exists to protect.
    """
    lines = source.splitlines(keepends=True)
    out: list[str] = []
    in_raw = False
    for line in lines:
        body = line.rstrip("\r\n")
        ending = line[len(body):]

        if in_raw:
            out.append(line)
            if _RAW_CLOSE_RE.search(body):
                in_raw = False
            continue

        if _RAW_OPEN_RE.search(body) and not _RAW_CLOSE_RE.search(body):
            out.append(line)
            in_raw = True
            continue

        match = _STANDALONE_EXPR_RE.match(body)
        if match is None:
            out.append(line)
            continue
        width = len(match["prefix"])
        out.append(
            f"{match['prefix']}{{{{ ({match['expr']}) | string | indent({width}) }}}}"
            f"{match['suffix']}{ending}"
        )
    return "".join(out)


def _render_jinja(
    hass: HomeAssistant,
    source: str,
    global_vars: dict[str, Any] | None,
    inc_vars: dict[str, Any] | None,
    macro_vars: dict[str, Any] | None,
    user_vars: dict[str, Any] | None,
    client_vars: dict[str, Any] | None,
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
        return _render_jinja_on_loop(
            hass, source, global_vars, inc_vars, macro_vars, user_vars, client_vars
        )
    return run_callback_threadsafe(
        hass.loop,
        _render_jinja_on_loop,
        hass,
        source,
        global_vars,
        inc_vars,
        macro_vars,
        user_vars,
        client_vars,
    ).result()


def _render_jinja_on_loop(
    hass: HomeAssistant,
    source: str,
    global_vars: dict[str, Any] | None,
    inc_vars: dict[str, Any] | None,
    macro_vars: dict[str, Any] | None,
    user_vars: dict[str, Any] | None,
    client_vars: dict[str, Any] | None,
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

    `user_vars` (`jjb.user`: `name`/`id`/`is_admin`/`is_owner`) is derived
    by `websocket.py` from the WebSocket connection's authenticated
    `connection.user` — trustworthy, and never influenced by the request
    payload. `client_vars` (`jjb.client`: `user_agent`/`viewport`/
    `browser_mod_id`/`language`/`is_dark_theme`) is the opposite: entirely
    frontend-supplied and unverifiable, useful for cosmetic/conditional
    layout but not for anything security-sensitive. Both are constant for
    the whole render tree, like `jjb.globals`/`jjb.macros` — never per-include
    like `jjb.inc`.

    `source` has whole-line YAML comments blanked out first (see
    `_blank_out_comment_lines`) so a commented-out line's `{{ }}`/`{% %}`
    doesn't raise for code the author meant to disable, and a standalone
    `{{ macro_call(...) }}`-shaped line has its expression wrapped in
    `| indent(N)` (see `_reindent_standalone_expressions`) so multi-line
    macro output nests under its call site instead of falling back to
    column 0.
    """
    template = Template(
        _reindent_standalone_expressions(_blank_out_comment_lines(source)), hass
    )
    try:
        return template.async_render(
            {
                "jjb": Namespace(
                    globals=Namespace(global_vars or {}),
                    inc=Namespace(inc_vars or {}),
                    macros=Namespace(macro_vars or {}),
                    user=Namespace(user_vars or {}),
                    client=Namespace(client_vars or {}),
                )
            },
            parse_result=False,
            strict=True,
        )
    except TemplateError as err:
        raise JinjaboardTemplateError(str(err), line=_extract_lineno(err)) from err


def _compile_macro_module(
    hass: HomeAssistant,
    source: str,
    global_vars: dict[str, Any] | None,
    user_vars: dict[str, Any] | None,
    client_vars: dict[str, Any] | None,
) -> Any:
    """Compile a macro file, safe to call from any thread.

    Injected into `macros.build_macro_namespace` as the `CompileMacroModule`
    callback (avoids a circular import between this module and `macros.py`,
    the same reason `render_and_parse` is injected into `includes.py`
    instead of imported there). Same on-loop/off-loop thread dispatch as
    `_render_jinja` — see its docstring for why.
    """
    if threading.get_ident() == hass.loop_thread_id:
        return _compile_macro_module_on_loop(
            hass, source, global_vars, user_vars, client_vars
        )
    return run_callback_threadsafe(
        hass.loop,
        _compile_macro_module_on_loop,
        hass,
        source,
        global_vars,
        user_vars,
        client_vars,
    ).result()


def _compile_macro_module_on_loop(
    hass: HomeAssistant,
    source: str,
    global_vars: dict[str, Any] | None,
    user_vars: dict[str, Any] | None,
    client_vars: dict[str, Any] | None,
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

    `jjb.globals`, `jjb.user`, and `jjb.client` are all available inside a
    macro body — none of them vary by position in the include tree. Only
    `jjb.inc` isn't: a macro module is compiled once, upfront, before any
    `!include` tree walk starts contributing `inc` vars, so there is no
    meaningful `inc` value to give it — see `macros.py`'s module docstring.

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

    Also goes through `_reindent_standalone_expressions`, same as
    `_render_jinja_on_loop` — a macro body can itself call another declared
    macro on a standalone line (e.g. a `card_row` macro looping over items
    and calling a per-item macro), and that inner call site needs the same
    treatment so the whole macro's output is internally consistent no
    matter what column it's eventually spliced in at by an outer call.
    """
    template = Template(
        _reindent_standalone_expressions(_blank_out_comment_lines(source)), hass
    )
    try:
        compiled = template._ensure_compiled(strict=True)  # noqa: SLF001
        return compiled.make_module(
            {
                "jjb": Namespace(
                    globals=Namespace(global_vars or {}),
                    inc=Namespace({}),
                    user=Namespace(user_vars or {}),
                    client=Namespace(client_vars or {}),
                )
            }
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
    user_vars: dict[str, Any] | None,
    client_vars: dict[str, Any] | None,
    include_stack: list[Path],
    debug_trace: dict[str, Any] | None = None,
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
    `macros.py`), `user_vars` (`jjb.user`), and `client_vars` (`jjb.client`)
    are likewise constant for the whole tree, built once by `render_template`
    before any include is walked.

    `debug_trace`, when not `None`, is mutated in place to collect data for
    the `debug:` WS response envelope (see `websocket.py::handle_render`):
    `"root_path"` (the root file's own display path, set exactly once),
    `"raw_texts"` (every touched file's post-Jinja/pre-YAML text, root
    included, keyed by display path), and `"include_vars"` (the effective
    `inc_vars` — i.e. exactly what `jjb.inc` resolves to inside that file,
    inherited vars from an ancestor `!include ... vars:` included — for
    every file whose `inc_vars` is non-empty, keyed the same way; root is
    never present here since it never has `inc_vars`). A file `!include`d
    more than once (with different `vars:`, say) only keeps its last
    occurrence's entry in either map. Whether *this* call is the root or a
    nested include is told apart by whether `"root_path"` is already
    present at entry — the root's own call always sets it (right below)
    before any nested include is parsed, since that only happens inside
    `parse_with_includes`, called after.
    """
    display_path = config_relative_display_path(hass, path)
    if debug_trace is not None and "root_path" not in debug_trace:
        debug_trace["root_path"] = display_path

    raw = _render_jinja(
        hass, source, global_vars, inc_vars, macro_vars, user_vars, client_vars
    )
    if debug_trace is not None:
        debug_trace.setdefault("raw_texts", {})[display_path] = raw
        if inc_vars:
            debug_trace.setdefault("include_vars", {})[display_path] = inc_vars

    try:
        return parse_with_includes(
            hass,
            raw,
            path.parent,
            global_vars,
            inc_vars,
            macro_vars,
            user_vars,
            client_vars,
            include_stack,
            _render_and_parse,
            debug_trace,
        )
    except yaml.YAMLError as err:
        raise JinjaboardYamlError(raw) from err


def _render_global_values(
    hass: HomeAssistant,
    value: Any,
    user_vars: dict[str, Any] | None,
    client_vars: dict[str, Any] | None,
) -> Any:
    """Recursively Jinja-render every string leaf of a resolved `globals:`
    mapping (`str` values only — dict keys, and non-`str` leaves like `int`/
    `float`/`bool`/`None`, are returned unchanged).

    Applies uniformly to whatever `globals_file.resolve_global_vars`
    returned, whether the dashboard's `globals:` was written inline or
    loaded from a separate file — this function doesn't know or care which.
    Values are only ever YAML/JSON-shaped (`dict`/`list`/`str`/`int`/
    `float`/`bool`/`None`, no tuples), so recursing through `dict`/`list` and
    rendering `str` is exhaustive.

    Each leaf is rendered via `_render_jinja` with `global_vars`/`inc_vars`/
    `macro_vars` all `None`, so `jjb.globals`/`jjb.inc`/`jjb.macros` come out
    as empty `Namespace({})` in `_render_jinja_on_loop` — deliberately: a
    global's value referencing `jjb.globals` would be a self-reference into
    the very dict being built here (genuinely circular, unlike `jjb.inc`/
    `jjb.macros`, which simply don't exist yet at this point in the render
    pipeline, the same reasoning `macros.py` uses for omitting `jjb.inc`
    from macro compilation). Referencing any of the three hits attribute
    access on an empty `Namespace`, raising `JinjaboardTemplateError` under
    `strict=True` — a clear error rather than silently resolving wrong.
    `jjb.user`/`jjb.client` and HA's own built-in template globals (`states()`,
    `now()`, `area_id()`, ...) remain available, since they come from
    `user_vars`/`client_vars` (passed through) and the `Template` environment
    itself, neither of which is circular.

    Each leaf independently goes through `_render_jinja`'s existing on-loop/
    off-loop thread dispatch and `JinjaboardTemplateError` wrapping — no
    separate handling needed here. Calling it once per string leaf (rather
    than once per file) means more loop round-trips when off-loop for a
    globals mapping with many string values, but no correctness risk: every
    `_render_jinja` call is fully self-contained, mutating no shared state.
    """
    if isinstance(value, str):
        return _render_jinja(hass, value, None, None, None, user_vars, client_vars)
    if isinstance(value, dict):
        return {
            key: _render_global_values(hass, val, user_vars, client_vars)
            for key, val in value.items()
        }
    if isinstance(value, list):
        return [
            _render_global_values(hass, item, user_vars, client_vars)
            for item in value
        ]
    return value


def render_template(
    hass: HomeAssistant,
    path: Path,
    source: str,
    global_vars: dict[str, Any] | str | None = None,
    macro_paths: list[str] | None = None,
    user_vars: dict[str, Any] | None = None,
    client_vars: dict[str, Any] | None = None,
    debug_trace: dict[str, Any] | None = None,
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
    `global_vars` may be a `str` (a `globals:` file path) instead of an
    already-resolved `dict` — resolved once, up front, via
    `globals_file.resolve_global_vars`, before it's used to build the macro
    namespace below (a macro body sees `jjb.globals` too, so it must see the
    resolved dict, not a raw path string). Every string leaf of that
    resolved dict (recursively, through nested `dict`/`list` values — never
    dict keys) is then itself rendered through Jinja by
    `_render_global_values`, again before `macro_vars` is built, so a macro
    body sees final values rather than literal `{{ }}` text. Inside a global
    value's Jinja, `jjb.user`/`jjb.client` and HA's own built-in template
    globals (`states()`, `now()`, `area_id()`, ...) are available, but
    `jjb.globals`/`jjb.inc`/`jjb.macros` are deliberately empty — see
    `_render_global_values`'s own docstring for why. `macro_paths` (the dashboard's
    own `macros:`) is resolved once, up front, into `jjb.macros` (see
    `macros.build_macro_namespace`) — unlike `jjb.inc`, it never changes as
    the include tree is walked. `user_vars` (`jjb.user`, derived by
    `websocket.py` from the authenticated WebSocket connection) and
    `client_vars` (`jjb.client`, frontend-supplied and unverifiable) are
    likewise constant for the whole tree.

    `debug_trace`, when not `None`, is mutated to carry `"root_path"` and
    `"raw_texts"` for the `debug:` WS response envelope — see
    `_render_and_parse`'s docstring. Existing callers that don't pass it
    are unaffected (default `None`, nothing collected).
    """
    global_vars = resolve_global_vars(hass, global_vars)
    # _render_global_values is generically `Any` (it recurses through
    # arbitrary dict/list/scalar leaves), but for a dict-or-None input it
    # always returns a same-shaped dict-or-None.
    global_vars = cast(
        "dict[str, Any] | None",
        _render_global_values(hass, global_vars, user_vars, client_vars),
    )
    macro_vars = build_macro_namespace(
        hass, macro_paths, global_vars, user_vars, client_vars, _compile_macro_module
    )
    return _render_and_parse(
        hass,
        path,
        source,
        global_vars,
        None,
        macro_vars,
        user_vars,
        client_vars,
        include_stack=[path.resolve()],
        debug_trace=debug_trace,
    )
