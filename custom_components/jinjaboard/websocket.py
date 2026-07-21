"""WebSocket API for JinjaBoard: render a template to a Lovelace-config JSON structure."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.event import TrackTemplate, async_track_template_result

from .const import DOMAIN, RENDER_SIGNAL_KEY
from .errors import (
    JinjaboardIncludeNotFoundError,
    JinjaboardTemplateError,
    JinjaboardYamlError,
)
from .path_guard import JinjaboardPathError, resolve_config_path
from .template_engine import render_template

_LOGGER = logging.getLogger(__name__)

# Truncate raw output shown in yaml_parse_error messages so a large malformed
# render doesn't flood the frontend error panel.
_RAW_OUTPUT_PREVIEW_CHARS = 500

# How long `jinjaboard/subscribe_render` waits for a burst of relevant state
# changes to settle before redoing a full render — larger than the
# frontend's own 200ms regenerate debounce (see get-strategy.ts /
# ha-panel-lovelace.ts) since a redo here is real file I/O plus re-rendering
# every file in the include tree, not a single string re-render.
_RENDER_DEBOUNCE_SECONDS = 0.5

_RENDER_SCHEMA = {
    vol.Required("template"): str,
    vol.Optional("globals"): dict,
    vol.Optional("macros"): [str],
}


@callback
def async_setup_websocket_api(hass: HomeAssistant) -> None:
    """Register the jinjaboard/render and jinjaboard/subscribe_render WS commands."""
    websocket_api.async_register_command(hass, handle_render)
    websocket_api.async_register_command(hass, handle_subscribe_render)


def _map_render_error(err: Exception) -> tuple[str, str]:
    """Map a `render_template` exception to a `(code, message)` WS error pair.

    Shared by `handle_render`'s `send_error` calls and
    `handle_subscribe_render`'s initial-failure `send_error` and
    later-failure `send_event({"error": ...})` calls, so both commands
    report the same codes/messages for the same underlying failure.
    """
    if isinstance(err, JinjaboardTemplateError):
        message = str(err)
        if err.line is not None:
            message = f"Line {err.line}: {message}"
        return "template_error", message
    if isinstance(err, JinjaboardYamlError):
        preview = err.raw_output[:_RAW_OUTPUT_PREVIEW_CHARS]
        return (
            "yaml_parse_error",
            "Rendered output was not valid YAML. Check indentation around any "
            f"{{% for %}}/{{% if %}} blocks. Raw output (truncated): {preview!r}",
        )
    if isinstance(err, JinjaboardIncludeNotFoundError):
        # Also covers a missing/unreadable `macros:` file or directory —
        # same "referenced file wasn't found" shape as a missing `!include`.
        return "include_not_found", str(err)
    if isinstance(err, JinjaboardPathError):
        # Raised here when an `!include`/`!include_dir_*` target, or a
        # `macros:` entry, resolves outside config_dir (the *root* template
        # path is validated earlier, before either command reaches this).
        return "path_traversal", str(err)
    raise TypeError(f"Unexpected render error type: {type(err)!r}")  # pragma: no cover


def _bump_render_signal(hass: HomeAssistant) -> None:
    """Nudge every connected client's `hass` object right after a push.

    See `sensor.py`'s module docstring: a `jinjaboard/subscribe_render`
    `event` message isn't itself a state change, so without this, nothing
    reliably makes home-assistant-frontend's `checkStrategyShouldRegenerate`
    recheck at the moment fresh data is actually available — it would only
    get picked up whenever some unrelated entity next happened to change,
    which can show stale-by-one-push content indefinitely on a quiet
    instance. Called after every push, success or error alike.
    """
    signal = hass.data.get(DOMAIN, {}).get(RENDER_SIGNAL_KEY)
    if signal is not None:
        signal.bump()


def _render_with_tracking(
    hass: HomeAssistant,
    path: Any,
    source: str,
    global_vars: dict[str, Any] | None,
    macro_paths: list[str] | None,
) -> tuple[Any, list[TrackTemplate]]:
    """Render `source`, also collecting a `TrackTemplate` per file involved.

    Used only by `handle_subscribe_render` — the plain `jinjaboard/render`
    command calls `render_template` directly, without a `track_templates`
    list, since it has no need to track anything afterwards.
    """
    track_templates: list[TrackTemplate] = []
    result = render_template(
        hass, path, source, global_vars, macro_paths, track_templates=track_templates
    )
    return result, track_templates


@websocket_api.websocket_command(
    {
        vol.Required("type"): "jinjaboard/render",
        **_RENDER_SCHEMA,
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
    except (
        JinjaboardPathError,
        JinjaboardIncludeNotFoundError,
        JinjaboardTemplateError,
        JinjaboardYamlError,
    ) as err:
        code, message = _map_render_error(err)
        connection.send_error(msg["id"], code, message)
        return

    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "jinjaboard/subscribe_render",
        **_RENDER_SCHEMA,
    }
)
@websocket_api.async_response
async def handle_subscribe_render(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Handle jinjaboard/subscribe_render: render once, then push a fresh
    render every time an entity/domain the render tree actually depends on
    changes.

    Modeled on Home Assistant core's own `render_template` WS command
    (`homeassistant.components.websocket_api.commands.handle_render_template`),
    but adapted for the fact that a jinjaboard render is a *tree* of
    independently-rendered files (root plus every recursively-resolved
    `!include`/`!include_dir_*`), not one template — `async_track_
    template_result` can watch a flat list of `(Template, variables)` pairs,
    but has no notion of redoing our custom YAML-parse-with-includes step.
    So each render pass collects that list itself (`_render_with_tracking`),
    and any tracked template firing is treated purely as a "redo the whole
    pipeline" signal — the tracker's own incremental per-template value is
    never used.

    Because the include tree can itself be state-dependent (a `{% if %}`
    choosing a different `!include` target, `!include_dir_named` matching a
    different file set), the tracked list is rebuilt from scratch after
    every successful re-render — a one-time tracker would silently miss
    entities newly pulled in by a later render. On a *failed* re-render, the
    previous (last-known-good) tracker is left running instead, so the
    dashboard can recover automatically once state changes back to
    something that renders successfully again.

    Per home-assistant-js-websocket's `Connection.subscribeMessage`: its
    callback fires only for `event`-typed messages — a bare `result` message
    only unblocks the subscribe call's own returned promise and is never
    forwarded to the callback. So the initial render is pushed via
    `send_event`, exactly like every later one, after a bare `send_result`
    ack — never as the ack's own payload.
    """
    relative_path = msg["template"]
    global_vars = msg.get("globals")
    macro_paths = msg.get("macros")

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
        result, track_templates = await hass.async_add_executor_job(
            _render_with_tracking, hass, path, source, global_vars, macro_paths
        )
    except (
        JinjaboardPathError,
        JinjaboardIncludeNotFoundError,
        JinjaboardTemplateError,
        JinjaboardYamlError,
    ) as err:
        code, message = _map_render_error(err)
        connection.send_error(msg["id"], code, message)
        return

    # `current_info` is rebound by `_rerender` (below) every time the render
    # tree's actual dependencies change over the life of the subscription —
    # a plain enclosing-scope variable is enough since every closure that
    # touches it lives inside this function. `_listener` is a plain
    # `@callback` (sync, runs inline in the tracker's own call stack) that
    # only schedules `_rerender` via the debouncer's sync entrypoint
    # (`async_schedule_call`, not `await async_call()`) — the real work
    # happens later, in `_rerender`'s own scheduled task, so there's no
    # reentrancy hazard with the listener's call stack.
    @callback
    def _listener(event: Any, updates: Any) -> None:
        debouncer.async_schedule_call()

    async def _rerender() -> None:
        nonlocal current_info
        try:
            new_result, new_track_templates = await hass.async_add_executor_job(
                _render_with_tracking, hass, path, source, global_vars, macro_paths
            )
        except (
            JinjaboardPathError,
            JinjaboardIncludeNotFoundError,
            JinjaboardTemplateError,
            JinjaboardYamlError,
        ) as err:
            # Keep the previous (last-known-good) tracker alive rather than
            # tearing it down, so the dashboard can recover automatically
            # once state changes back to something that renders again.
            code, message = _map_render_error(err)
            connection.send_event(msg["id"], {"error": {"code": code, "message": message}})
            _bump_render_signal(hass)
            return

        # Build the new tracker before removing the old one, so there's
        # never a window with zero active trackers — the include tree can
        # be state-dependent (a `{% if %}` choosing a different `!include`,
        # `!include_dir_named` matching a different file set), so the
        # tracked dependency set must be rebuilt from scratch every cycle;
        # a one-time tracker would silently miss entities newly pulled in.
        new_info = async_track_template_result(
            hass, new_track_templates, _listener, strict=True
        )
        current_info.async_remove()
        current_info = new_info
        connection.send_event(msg["id"], {"result": new_result})
        _bump_render_signal(hass)

    debouncer = Debouncer(
        hass,
        _LOGGER,
        cooldown=_RENDER_DEBOUNCE_SECONDS,
        immediate=False,
        function=_rerender,
    )

    current_info = async_track_template_result(hass, track_templates, _listener, strict=True)

    def _unsubscribe() -> None:
        current_info.async_remove()
        debouncer.async_shutdown()

    connection.subscriptions[msg["id"]] = _unsubscribe
    connection.send_result(msg["id"])
    connection.send_event(msg["id"], {"result": result})
    _bump_render_signal(hass)
