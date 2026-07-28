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
    """Raised when Jinja2 rendering itself fails (bad syntax, runtime error).

    `line` is folded into the message eagerly (`Line N: ...`) rather than
    left for a caller to prepend later. This matters once `!include` is
    involved: `includes.py`'s `_render_included_file` builds a readable
    include chain by repeatedly prepending "in included file X (included at
    line N): " to `str(err)` as the error propagates out of each nested
    `!include`, so a deeper error's own `Line N:` must already be anchored
    next to *its* message before an outer hop's prefix lands in front of it
    — otherwise a single "Line N:" glued onto the very front of the whole
    chain (which is what `websocket.py` used to do) reads as if it belongs
    to the outermost file mentioned, when it actually belongs to the
    innermost one.
    """

    def __init__(self, message: str, line: int | None = None) -> None:
        if line is not None:
            message = f"Line {line}: {message}"
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


class JinjaboardGlobalsError(JinjaboardError):
    """Raised when a `globals:` file path resolves to invalid YAML or a
    non-mapping top-level value.

    Deliberately distinct from `JinjaboardYamlError`: that type's fixed
    message ("Rendered template output was not valid YAML") and
    `websocket.py`'s Jinja-specific follow-on hint are about the *rendered
    template* pipeline — a `globals:` file is never Jinja-rendered, so
    reusing that type/message here would be misleading.
    """


class JinjaboardNotAuthorizedError(JinjaboardError):
    """Raised when a `globals:` file path or a `macros:` entry resolves to a
    path that isn't on the admin's allowlist (see `template_allowlist.py`).

    `template:` itself is checked directly in `websocket.py::handle_render`
    (a boolean check with an early `connection.send_error`, not this
    exception) since that check happens before any executor-job hop. This
    exception exists because `globals:`/`macros:` resolution happens deeper
    in the render pipeline, off the event loop, where raising and letting
    `websocket.py` catch it is the only way back to the same
    `template_not_authorized` WS error code.
    """
