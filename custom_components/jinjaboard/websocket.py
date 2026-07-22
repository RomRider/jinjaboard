"""WebSocket API for JinjaBoard: render a template to a Lovelace-config JSON structure."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .errors import JinjaboardIncludeNotFoundError
from .path_guard import JinjaboardPathError, resolve_config_path
from .template_allowlist import is_template_authorized
from .template_engine import (
    JinjaboardTemplateError,
    JinjaboardYamlError,
    render_template,
)

# Truncate raw output shown in yaml_parse_error messages so a large malformed
# render doesn't flood the frontend error panel.
_RAW_OUTPUT_PREVIEW_CHARS = 500


@callback
def async_setup_websocket_api(hass: HomeAssistant) -> None:
    """Register the jinjaboard/render WebSocket command."""
    websocket_api.async_register_command(hass, handle_render)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "jinjaboard/render",
        vol.Required("template"): str,
        vol.Optional("globals"): dict,
        vol.Optional("macros"): [str],
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

    try:
        path = resolve_config_path(hass, relative_path)
    except JinjaboardPathError as err:
        connection.send_error(msg["id"], "path_traversal", str(err))
        return

    if not is_template_authorized(hass, path):
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
            render_template, hass, path, source, global_vars, macro_paths
        )
    except JinjaboardPathError as err:
        # Raised here (rather than only by the resolve_config_path call
        # above) when an `!include`/`!include_dir_*` target, or a `macros:`
        # entry, resolves outside config_dir.
        connection.send_error(msg["id"], "path_traversal", str(err))
        return
    except JinjaboardIncludeNotFoundError as err:
        # Also covers a missing/unreadable `macros:` file or directory —
        # same "referenced file wasn't found" shape as a missing `!include`.
        connection.send_error(msg["id"], "include_not_found", str(err))
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

    connection.send_result(msg["id"], result)
