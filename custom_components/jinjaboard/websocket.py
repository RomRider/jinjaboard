"""WebSocket API for JinjaBoard: render a template to a Lovelace-config JSON structure."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .errors import JinjaboardIncludeNotFoundError
from .path_guard import JinjaboardPathError, resolve_config_path
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
        vol.Optional("variables"): dict,
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
    variables = msg.get("variables")

    try:
        path = resolve_config_path(hass, relative_path)
    except JinjaboardPathError as err:
        connection.send_error(msg["id"], "path_traversal", str(err))
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
        result = render_template(hass, path, source, variables)
    except JinjaboardPathError as err:
        # Raised here (rather than only by the resolve_config_path call
        # above) when an `!include`/`!include_dir_*` target inside the
        # template resolves outside config_dir.
        connection.send_error(msg["id"], "path_traversal", str(err))
        return
    except JinjaboardIncludeNotFoundError as err:
        connection.send_error(msg["id"], "include_not_found", str(err))
        return
    except JinjaboardTemplateError as err:
        message = str(err)
        if err.line is not None:
            message = f"Line {err.line}: {message}"
        connection.send_error(msg["id"], "template_error", message)
        return
    except JinjaboardYamlError as err:
        preview = err.raw_output[:_RAW_OUTPUT_PREVIEW_CHARS]
        connection.send_error(
            msg["id"],
            "yaml_parse_error",
            "Rendered output was not valid YAML. Check indentation around any "
            f"{{% for %}}/{{% if %}} blocks. Raw output (truncated): {preview!r}",
        )
        return

    connection.send_result(msg["id"], result)
