"""WebSocket API for JinjaBoard: render a template to a Lovelace-config JSON structure."""

from __future__ import annotations

import time
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .errors import JinjaboardIncludeNotFoundError, JinjaboardNotAuthorizedError
from .path_guard import JinjaboardPathError, resolve_config_path
from .template_allowlist import is_path_authorized
from .template_engine import (
    JinjaboardGlobalsError,
    JinjaboardTemplateError,
    JinjaboardYamlError,
    render_template,
)

# Truncate raw output shown in yaml_parse_error messages so a large malformed
# render doesn't flood the frontend error panel.
_RAW_OUTPUT_PREVIEW_CHARS = 500


def _walk_origins(
    node: Any, dot_path: str, origin_by_id: dict[int, str], out: dict[str, str]
) -> None:
    """Flatten `debug_trace["origin_by_id"]` (a Python-object-identity map
    built while parsing, in `includes.py::_render_included_file`) into a
    dot-path -> origin-file map over the *final* parsed `result` — this can
    only happen here, after `render_template` returns but before the result
    is JSON-serialized for `send_result`, since object identity doesn't
    survive serialization. Recurses into every node regardless of whether
    it matched, so a deeper nested include produces its own, more specific
    entry alongside its ancestor's — `strategy-common.ts`'s `resolveOrigin`
    picks the most specific one for a given output path."""
    if id(node) in origin_by_id:
        out[dot_path] = origin_by_id[id(node)]
    if isinstance(node, dict):
        for key, value in node.items():
            _walk_origins(
                value, f"{dot_path}.{key}" if dot_path else str(key), origin_by_id, out
            )
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _walk_origins(
                value,
                f"{dot_path}.{index}" if dot_path else str(index),
                origin_by_id,
                out,
            )


@callback
def async_setup_websocket_api(hass: HomeAssistant) -> None:
    """Register the jinjaboard/render WebSocket command."""
    websocket_api.async_register_command(hass, handle_render)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "jinjaboard/render",
        vol.Required("template"): str,
        vol.Optional("globals"): vol.Any(dict, str),
        vol.Optional("macros"): [str],
        vol.Optional("debug"): vol.Any(bool, str, [str]),
        vol.Optional("client"): {
            vol.Optional("user_agent"): str,
            vol.Optional("viewport"): {
                vol.Optional("width"): int,
                vol.Optional("height"): int,
            },
            vol.Optional("browser_mod_id"): str,
            vol.Optional("language"): str,
            vol.Optional("is_dark_theme"): bool,
        },
    }
)
@websocket_api.async_response
async def handle_render(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Handle jinjaboard/render: resolve, read, and render a template file."""
    relative_path = msg["template"]
    global_vars = msg.get("globals")
    macro_paths = msg.get("macros")
    client_vars = msg.get("client")
    # Not sourced from `msg` — the request schema has no `user` field at
    # all, so there's no way for the frontend to override this. `jjb.user`
    # is meant to be trustworthy (unlike `jjb.client`, entirely
    # frontend-supplied and unverifiable), so it's always derived from the
    # authenticated `connection.user` HA itself already resolved for this
    # WebSocket connection.
    user_vars = {
        "name": connection.user.name,
        "id": connection.user.id,
        "is_admin": connection.user.is_admin,
        "is_owner": connection.user.is_owner,
    }
    # `debug:` (a `debug` panel viewable from the browser console) is
    # backend-enforced to admins only — `connection.user.is_admin` is the
    # same field already used above for `jjb.user.is_admin`, checked
    # directly here rather than threaded through template rendering, since
    # this is a WS-handler authorization gate, not a template variable. A
    # non-admin's truthy `debug` is treated as if it were never sent: no
    # raw-text/timing/include collection happens at all (not just omitted
    # from the response), and the response comes back in the ordinary bare
    # shape — the frontend never assumes the wrapped shape just because it
    # asked for one.
    debug_requested = bool(msg.get("debug")) and connection.user.is_admin
    debug_trace: dict[str, Any] | None = {} if debug_requested else None
    render_started = time.monotonic() if debug_requested else None

    try:
        path = resolve_config_path(hass, relative_path)
    except JinjaboardPathError as err:
        connection.send_error(msg["id"], "path_traversal", str(err))
        return

    if not is_path_authorized(hass, path):
        connection.send_error(
            msg["id"],
            "template_not_authorized",
            f"Template '{relative_path}' is not on JinjaBoard's authorized "
            "files list. Add it in Settings → Devices & Services → "
            "JinjaBoard → Configure.",
        )
        return

    try:
        source = await hass.async_add_executor_job(path.read_text)
    except OSError as err:
        connection.send_error(
            msg["id"],
            "path_missing",
            f"Could not read template file '{relative_path}': {err}",
        )
        return

    try:
        # Off the loop: `!include`/`!include_dir_*` resolution does blocking
        # file reads/directory walks (see includes.py). `render_template`
        # stays a plain sync function — `_render_jinja` inside it detects
        # it's no longer on the loop thread and hops back via
        # `run_callback_threadsafe` for the one call that must stay there
        # (`Template.async_render`).
        result = await hass.async_add_executor_job(
            render_template,
            hass,
            path,
            source,
            global_vars,
            macro_paths,
            user_vars,
            client_vars,
            debug_trace,
        )
    except JinjaboardPathError as err:
        # Raised here (rather than only by the resolve_config_path call
        # above) when an `!include`/`!include_dir_*` target, or a `macros:`
        # entry, resolves outside config_dir.
        connection.send_error(msg["id"], "path_traversal", str(err))
        return
    except JinjaboardIncludeNotFoundError as err:
        # Also covers a missing/unreadable `macros:` file or directory, or a
        # missing `globals:` file — same "referenced file wasn't found"
        # shape as a missing `!include`.
        connection.send_error(msg["id"], "include_not_found", str(err))
        return
    except JinjaboardNotAuthorizedError as err:
        # A `globals:` file path or a `macros:` entry that resolves outside
        # the admin's allowlist — same code as the top-level `template:`
        # check above (`is_path_authorized`), since both mean "this path
        # isn't on JinjaBoard's authorized files list"; `str(err)` already
        # names which kind of path failed.
        connection.send_error(msg["id"], "template_not_authorized", str(err))
        return
    except JinjaboardGlobalsError as err:
        # A `globals:` file that was found and authorized but isn't valid
        # YAML, or whose top-level value isn't a mapping.
        connection.send_error(msg["id"], "globals_error", str(err))
        return
    except JinjaboardTemplateError as err:
        # `str(err)` already carries its own "Line N:" (see
        # JinjaboardTemplateError.__init__) and, for a nested `!include`
        # failure, the "in included file X (included at line N): " chain
        # `includes.py` built around it — no further formatting needed here.
        connection.send_error(msg["id"], "template_error", str(err))
        return
    except JinjaboardYamlError as err:
        # `str(err)` is either the generic default message, or (for a nested
        # `!include` failure) that default prefixed with the same
        # "in included file X (included at line N): " chain used for
        # `template_error` above — without it, a YAML error inside an
        # included file would show the same generic sentence as one in the
        # root template, with no indication of which file actually failed.
        # The preview is appended as its own paragraph, starting on a fresh
        # line, and *not* through `!r` (which would escape its real
        # newlines to literal `\n` text, collapsing what's usually
        # multi-line rendered YAML into one unreadable line) — the raw
        # rendered output's own line breaks carry real information about
        # where the indentation went wrong, so they need to survive
        # into what the frontend renders as a fenced code block.
        preview = err.raw_output[:_RAW_OUTPUT_PREVIEW_CHARS]
        connection.send_error(
            msg["id"],
            "yaml_parse_error",
            f"{err}. Check indentation around any {{% for %}}/{{% if %}} "
            f"blocks. Raw output (truncated):\n{preview}",
        )
        return

    if debug_requested:
        duration_ms = round((time.monotonic() - render_started) * 1000, 1)
        origins: dict[str, str] = {}
        _walk_origins(result, "", debug_trace.get("origin_by_id", {}), origins)
        connection.send_result(
            msg["id"],
            {
                "config": result,
                "debug": {
                    "duration_ms": duration_ms,
                    "root_path": debug_trace.get("root_path", ""),
                    "raw_texts": debug_trace.get("raw_texts", {}),
                    "include_vars": debug_trace.get("include_vars", {}),
                    "origins": origins,
                },
            },
        )
    else:
        connection.send_result(msg["id"], result)
