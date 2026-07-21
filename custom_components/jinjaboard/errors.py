"""Shared exception types for JinjaBoard template/include rendering.

Split out from `template_engine.py` so both it and `includes.py` can raise
and catch these without a circular import: `template_engine.py` calls into
`includes.py` to resolve `!include`/`!include_dir_*` tags, and `includes.py`
needs to raise/catch the same template-rendering error types when a nested
included file fails to render.
"""

from __future__ import annotations


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


class JinjaboardIncludeError(JinjaboardError):
    """Base error for `!include`/`!include_dir_*` resolution failures."""


class JinjaboardIncludeNotFoundError(JinjaboardIncludeError):
    """Raised when an `!include`/`!include_dir_*` target doesn't exist."""
