"""Resolve a dashboard's `macros:` config into `jjb.macros`.

Lets a template call a macro defined in a *different* file — Jinja's own
`{% import %}`/`{% from ... import %}` can't do this here (see
`template_engine._compile_macro_module`'s docstring): HA's shared, cached
`jinja2.Environment` has a `loader`, but it only resolves names from
`<config>/custom_templates/*.jinja`, a separate HA mechanism JinjaBoard's own
file resolution never populates, and mutating that shared environment's
`.loader` to point it at JinjaBoard's own files would affect every other
strict-mode template render in HA, not just this integration's — the same
class of mistake `includes.py`'s module docstring already documents and
avoids for `!include` itself.

Instead, `macros:` is resolved up front, once per `jinjaboard/render` call:
each declared file is compiled independently via
`template_engine._compile_macro_module` (injected as `compile_macro_module`
below, avoiding a circular import between this module and
`template_engine.py`, the same reason `includes.py` takes a `render_and_parse`
callback instead of importing `template_engine` directly), giving a
`jinja2.TemplateModule` per file. Every macro *from every file* is then
flattened into a single `{macro_name: Macro}` mapping — `jjb.macros.<name>`
is reachable regardless of which declared file defined it, so which file a
macro lives in is purely an authoring detail, not part of the calling
convention. Only `jinja2.runtime.Macro` values are kept (a stray top-level
`{% set %}` in a macro file is not a macro and is silently excluded, rather
than polluting `jjb.macros` with something uncallable).

A macro file only ever sees `jjb.globals`, never `jjb.inc` — it's compiled
once here, before any `!include` tree walk has contributed `inc` vars, so
there's no meaningful, tree-position-specific `inc` value to give it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import jinja2.runtime
from homeassistant.core import HomeAssistant

from .errors import JinjaboardIncludeNotFoundError, JinjaboardTemplateError
from .includes import find_template_files
from .path_guard import resolve_config_path

# (hass, source, global_vars) -> jinja2.TemplateModule. Injected rather than
# imported from template_engine.py to avoid a circular import:
# template_engine.py imports build_macro_namespace() from this module.
CompileMacroModule = Callable[[HomeAssistant, str, "dict[str, Any] | None"], Any]


def _compile_one(
    hass: HomeAssistant,
    file_path: Path,
    global_vars: dict[str, Any] | None,
    compile_macro_module: CompileMacroModule,
    relative_to: str,
) -> Any:
    try:
        source = file_path.read_text()
    except OSError as err:
        raise JinjaboardIncludeNotFoundError(
            f"Macro file {relative_to!r} not found"
        ) from err
    return compile_macro_module(hass, source, global_vars)


def build_macro_namespace(
    hass: HomeAssistant,
    macro_paths: list[str] | None,
    global_vars: dict[str, Any] | None,
    compile_macro_module: CompileMacroModule,
) -> dict[str, Any]:
    """Resolve a dashboard's `macros:` entries into `{macro_name: Macro}`.

    Each entry in `macro_paths` is resolved relative to `config_dir` (like
    `template` itself — there is no "current file" at the dashboard-config
    level the way there is for `!include`), and confined to stay under it
    via `path_guard.resolve_config_path`. A directory entry is walked
    recursively exactly like `!include_dir_named`
    (`includes.find_template_files`).

    Every macro defined in every resolved file is merged into one flat
    mapping, keyed by macro name — not by filename, so which file a macro
    happens to live in doesn't affect how it's called. Two files defining a
    macro of the same name raise `JinjaboardTemplateError` rather than
    letting the second silently shadow the first, matching this project's
    `jjb.globals`/`jjb.inc` shadowing philosophy.
    """
    if not macro_paths:
        return {}

    namespace: dict[str, Any] = {}
    for relative_path in macro_paths:
        target = resolve_config_path(hass, relative_path)
        if target.is_dir():
            for file_path in find_template_files(target):
                relative_to = str(file_path.relative_to(target))
                module = _compile_one(
                    hass, file_path, global_vars, compile_macro_module, relative_to
                )
                _merge_macros(namespace, module, relative_to)
        elif target.is_file():
            module = _compile_one(
                hass, target, global_vars, compile_macro_module, relative_path
            )
            _merge_macros(namespace, module, relative_path)
        else:
            raise JinjaboardIncludeNotFoundError(
                f"Macro path {relative_path!r} not found"
            )
    return namespace


def _merge_macros(namespace: dict[str, Any], module: Any, source_path: str) -> None:
    for name, value in vars(module).items():
        if not isinstance(value, jinja2.runtime.Macro):
            continue
        if name in namespace:
            raise JinjaboardTemplateError(
                f"macros: {source_path!r} defines {name!r}, which another "
                "macros: file already defines — rename one of them so they "
                "don't collide"
            )
        namespace[name] = value
