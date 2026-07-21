"""Resolve `!include`/`!include_dir_*` YAML tags in JinjaBoard templates.

Mirrors Home Assistant's own `!include` family (see
https://www.home-assistant.io/docs/configuration/splitting_configuration/),
but each included file is its own Jinja template, not static YAML: it gets
rendered (with `strict=True` undefined-variable checking, same as the root
template) before being parsed, and the tags in *its* rendered output are
resolved recursively.

Security note — why this is a private loader, not `homeassistant.util.yaml.
loader.parse_yaml`: that function delegates to `annotatedyaml`, whose real
`!include`/`!include_dir_*`/`!secret`/`!env_var` constructors are registered
**globally** on the `FastSafeLoader`/`PythonSafeLoader` classes it also uses
internally for loading HA's own `configuration.yaml`. Parsing our *rendered*
template output with that function would let a bare `!include ../../../etc/
hostname` in a template's output silently read arbitrary files relative to
the process's CWD (confirmed live) — `path_guard`, `strict` Jinja, none of it
would ever run. `_JinjaboardYamlLoader` below is a standalone `yaml.SafeLoader`
subclass with its own five constructors registered only on itself, so parsing
our own rendered output can never trigger HA's real (unguarded,
non-Jinja-aware) include machinery, and any *other* stray tag (e.g. a `!secret`
pasted from a real HA config) falls through to PyYAML's normal
"could not determine a constructor" error instead of doing something silently
wrong.
"""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path
from typing import Any, Callable

import yaml

from homeassistant.core import HomeAssistant

from .errors import (
    JinjaboardIncludeNotFoundError,
    JinjaboardIncludeError,
    JinjaboardTemplateError,
    JinjaboardYamlError,
)
from .path_guard import resolve_config_path

# Coarse backstop against runaway/cyclic includes. Not a resource-limit story
# (there's no render-timeout guard yet either — see template_engine.py) —
# just enough to turn an infinite loop into a legible error.
MAX_INCLUDE_DEPTH = 20

# Real HA's directory includes match only "*.yaml". JinjaBoard adds the
# double-extension Jinja-template convention alongside it; every matched file
# is rendered through Jinja uniformly regardless of which pattern matched it
# (a file with no `{{ }}`/`{% %}` just renders unchanged).
_DIR_INCLUDE_PATTERNS = ("*.yaml", "*.yml", "*.yaml.j2", "*.yml.j2")

# Longest-first so `!include_dir_named` strips the *whole* recognized
# extension (`foo.yaml.j2` -> `foo`), not just the last dot-segment like real
# HA's single `os.path.splitext` (which would leave `foo.yaml`).
_TEMPLATE_EXTENSIONS = (".yaml.j2", ".yml.j2", ".yaml", ".yml", ".j2")

# (hass, path, source, global_vars, inc_vars, macro_vars, include_stack) ->
# parsed result. Injected rather than imported from template_engine.py to
# avoid a circular import: template_engine.py imports parse_with_includes()
# from this module.
RenderAndParse = Callable[
    [
        HomeAssistant,
        Path,
        str,
        "dict[str, Any] | None",
        "dict[str, Any] | None",
        "dict[str, Any] | None",
        "list[Path]",
    ],
    Any,
]


def _is_visible(name: str) -> bool:
    return not name.startswith(".")


def find_template_files(directory: Path) -> list[Path]:
    """Recursively list matching files under `directory`.

    Mirrors `annotatedyaml.loader._find_files`: recursive `os.walk`,
    dotfiles/dot-directories skipped, files sorted alphabetically within each
    directory level (subdirectory traversal order is `os.walk`'s own, not
    additionally sorted — same as real HA).

    Shared with `macros.py`'s directory-of-macro-files resolution, not just
    `!include_dir_*` — same file-discovery rules apply to both.
    """
    found: list[Path] = []
    for root, dirs, files in os.walk(directory, topdown=True):
        dirs[:] = [d for d in dirs if _is_visible(d)]
        for basename in sorted(files):
            if _is_visible(basename) and any(
                fnmatch.fnmatch(basename, pattern) for pattern in _DIR_INCLUDE_PATTERNS
            ):
                found.append(Path(root) / basename)
    return found


def template_file_key(path: Path) -> str:
    """Derive the `!include_dir_named` dict key for a matched file.

    Shared with `macros.py`'s directory-of-macro-files resolution, not just
    `!include_dir_named`.
    """
    name = path.name
    for ext in _TEMPLATE_EXTENSIONS:
        if name.endswith(ext):
            return name[: -len(ext)]
    return path.stem


class _JinjaboardYamlLoader(yaml.SafeLoader):
    """Private per-call YAML loader carrying include-resolution context.

    A fresh instance is created for every parse (root or included file) via
    `parse_with_includes`'s `Loader=` factory — see the module docstring for
    why this must never be HA's global `FastSafeLoader`/`PythonSafeLoader`.
    """

    def __init__(
        self,
        stream: Any,
        *,
        hass: HomeAssistant,
        current_dir: Path,
        global_vars: dict[str, Any] | None,
        inc_vars: dict[str, Any] | None,
        macro_vars: dict[str, Any] | None,
        include_stack: list[Path],
        render_and_parse: RenderAndParse,
    ) -> None:
        super().__init__(stream)
        self.hass = hass
        self.current_dir = current_dir
        self.global_vars = global_vars
        self.inc_vars = inc_vars
        self.macro_vars = macro_vars
        self.include_stack = include_stack
        self.render_and_parse = render_and_parse


def parse_with_includes(
    hass: HomeAssistant,
    text: str,
    current_dir: Path,
    global_vars: dict[str, Any] | None,
    inc_vars: dict[str, Any] | None,
    macro_vars: dict[str, Any] | None,
    include_stack: list[Path],
    render_and_parse: RenderAndParse,
) -> Any:
    """Parse `text` (already Jinja-rendered), resolving include tags.

    `current_dir` is the directory of the file `text` came from — `!include`
    targets inside it resolve relative to this directory, matching real HA.
    `global_vars` (the dashboard's `globals:`, exposed as `jjb.globals`) and
    `macro_vars` (the dashboard's `macros:`, exposed as `jjb.macros`) are
    carried through unchanged; `inc_vars` (exposed as `jjb.inc`) is what a
    nested `!include ... vars:` layers on top of, in `_render_included_file`
    below.
    """

    def _make_loader(stream: Any) -> _JinjaboardYamlLoader:
        return _JinjaboardYamlLoader(
            stream,
            hass=hass,
            current_dir=current_dir,
            global_vars=global_vars,
            inc_vars=inc_vars,
            macro_vars=macro_vars,
            include_stack=include_stack,
            render_and_parse=render_and_parse,
        )

    return yaml.load(text, Loader=_make_loader)


def _parse_include_args(
    loader: _JinjaboardYamlLoader, node: yaml.Node
) -> tuple[str, dict[str, Any] | None]:
    """Extract `(path, extra_vars)` from either tag form.

    `!include some/file.yaml.j2` (scalar) or
    `!include {path: some/file.yaml.j2, vars: {area_id: kitchen}}` (mapping).
    """
    if isinstance(node, yaml.ScalarNode):
        path = loader.construct_scalar(node)
        if not path:
            raise JinjaboardTemplateError(
                f"{node.tag} needs an argument", line=node.start_mark.line + 1
            )
        return path, None
    if isinstance(node, yaml.MappingNode):
        mapping = loader.construct_mapping(node, deep=True)
        path = mapping.get("path")
        if not path:
            raise JinjaboardTemplateError(
                f"{node.tag} mapping form requires a non-empty 'path' key "
                f"(got keys {sorted(mapping)!r})",
                line=node.start_mark.line + 1,
            )
        extra_vars = mapping.get("vars")
        if extra_vars is not None and not isinstance(extra_vars, dict):
            raise JinjaboardTemplateError(
                f"{node.tag}'s 'vars' key must be a mapping, got {type(extra_vars).__name__}",
                line=node.start_mark.line + 1,
            )
        return path, extra_vars
    raise JinjaboardTemplateError(
        f"{node.tag} needs a scalar path or a {{path, vars}} mapping",
        line=node.start_mark.line + 1,
    )


def _check_cycle_and_depth(
    target: Path, include_stack: list[Path], relative_path: str, node_line: int
) -> None:
    if target in include_stack:
        chain = " -> ".join(str(p) for p in (*include_stack, target))
        raise JinjaboardTemplateError(
            f"Include cycle detected: {chain}", line=node_line
        )
    if len(include_stack) >= MAX_INCLUDE_DEPTH:
        raise JinjaboardTemplateError(
            f"Maximum include depth ({MAX_INCLUDE_DEPTH}) exceeded while "
            f"including {relative_path!r}",
            line=node_line,
        )


def _render_included_file(
    loader: _JinjaboardYamlLoader,
    node: yaml.Node,
    target: Path,
    relative_path: str,
    extra_vars: dict[str, Any] | None,
) -> Any:
    """Read, render, and recursively parse `target`, wrapping errors with
    the file and line that referenced it so a deeply nested failure still
    reads as a legible chain rather than an anonymous line number."""
    node_line = node.start_mark.line + 1
    _check_cycle_and_depth(target, loader.include_stack, relative_path, node_line)

    try:
        source = target.read_text()
    except OSError as err:
        raise JinjaboardIncludeNotFoundError(
            f"Included file {relative_path!r} not found"
        ) from err

    inc_vars = loader.inc_vars
    if extra_vars:
        inc_vars = {**(inc_vars or {}), **extra_vars}

    try:
        return loader.render_and_parse(
            loader.hass,
            target,
            source,
            loader.global_vars,
            inc_vars,
            loader.macro_vars,
            [*loader.include_stack, target],
        )
    except (JinjaboardTemplateError, JinjaboardYamlError, JinjaboardIncludeError) as err:
        err.args = (
            f"in included file {relative_path!r} (included at line {node_line}): {err}",
        ) + err.args[1:]
        raise


def _resolve_dir(
    loader: _JinjaboardYamlLoader, node: yaml.Node
) -> tuple[Path, dict[str, Any] | None]:
    relative_path, extra_vars = _parse_include_args(loader, node)
    target_dir = resolve_config_path(
        loader.hass, relative_path, base_dir=loader.current_dir
    )
    return target_dir, extra_vars


def _include_dir_files(
    loader: _JinjaboardYamlLoader, node: yaml.Node, target_dir: Path, extra_vars: dict[str, Any] | None
) -> list[Any]:
    """Render+parse every matched file under `target_dir`, in walk order."""
    return [
        _render_included_file(
            loader, node, file_path, str(file_path.relative_to(target_dir)), extra_vars
        )
        for file_path in find_template_files(target_dir)
    ]


def _construct_include(loader: _JinjaboardYamlLoader, node: yaml.Node) -> Any:
    relative_path, extra_vars = _parse_include_args(loader, node)
    target = resolve_config_path(loader.hass, relative_path, base_dir=loader.current_dir)
    return _render_included_file(loader, node, target, relative_path, extra_vars)


def _construct_include_dir_list(loader: _JinjaboardYamlLoader, node: yaml.Node) -> list[Any]:
    target_dir, extra_vars = _resolve_dir(loader, node)
    return [
        value
        for value in _include_dir_files(loader, node, target_dir, extra_vars)
        if value is not None
    ]


def _construct_include_dir_named(
    loader: _JinjaboardYamlLoader, node: yaml.Node
) -> dict[str, Any]:
    target_dir, extra_vars = _resolve_dir(loader, node)
    mapping: dict[str, Any] = {}
    for file_path in find_template_files(target_dir):
        value = _render_included_file(
            loader, node, file_path, str(file_path.relative_to(target_dir)), extra_vars
        )
        mapping[template_file_key(file_path)] = {} if value is None else value
    return mapping


def _construct_include_dir_merge_list(
    loader: _JinjaboardYamlLoader, node: yaml.Node
) -> list[Any]:
    target_dir, extra_vars = _resolve_dir(loader, node)
    merged: list[Any] = []
    for value in _include_dir_files(loader, node, target_dir, extra_vars):
        if isinstance(value, list):
            merged.extend(value)
    return merged


def _construct_include_dir_merge_named(
    loader: _JinjaboardYamlLoader, node: yaml.Node
) -> dict[str, Any]:
    target_dir, extra_vars = _resolve_dir(loader, node)
    merged: dict[str, Any] = {}
    for value in _include_dir_files(loader, node, target_dir, extra_vars):
        if isinstance(value, dict):
            merged.update(value)
    return merged


_JinjaboardYamlLoader.add_constructor("!include", _construct_include)
_JinjaboardYamlLoader.add_constructor("!include_dir_list", _construct_include_dir_list)
_JinjaboardYamlLoader.add_constructor("!include_dir_named", _construct_include_dir_named)
_JinjaboardYamlLoader.add_constructor(
    "!include_dir_merge_list", _construct_include_dir_merge_list
)
_JinjaboardYamlLoader.add_constructor(
    "!include_dir_merge_named", _construct_include_dir_merge_named
)
