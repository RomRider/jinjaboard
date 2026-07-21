"""Register JinjaBoard's frontend bundle and its Lovelace resource entry."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

_WWW_DIR = Path(__file__).parent / "www"

# Public: also read by config_flow.py to show YAML-mode setup instructions.
STATIC_URL_PATH = f"/{DOMAIN}_static/jinjaboard-strategy.js"

_MANUAL_STORAGE_RESOURCE_INSTRUCTIONS = (
    "Add it manually instead: Settings > Dashboards > the ⋮ menu > "
    f"Resources > Add Resource > URL: {STATIC_URL_PATH}, "
    "Resource type: JavaScript Module."
)

_MANUAL_YAML_RESOURCE_INSTRUCTIONS = (
    "Add it manually instead by adding this to configuration.yaml's "
    "`lovelace:` block and restarting Home Assistant: resources: - url: "
    f"{STATIC_URL_PATH}, type: module."
)


async def async_register_frontend(hass: HomeAssistant) -> None:
    """Serve the strategy bundle and ensure it's registered as a Lovelace resource.

    We deliberately do NOT use `frontend.add_extra_js_url` here. It embeds a
    classic `<script>import(url)</script>` tag directly in server-rendered
    HTML, and that dynamic import is unreliable in Firefox: it sometimes
    never resolves (or throws `InvalidStateError` on re-navigation without
    recovering), which makes Lovelace's dashboard-strategy loader hit its
    hardcoded 5-second "Timeout waiting for strategy element ... to be
    registered" error. Registering as a Lovelace resource instead goes
    through home-assistant-frontend's own `loadModule()` (a real
    `<script type="module" src="...">` element inserted after load, not a
    wrapped dynamic import) — verified reliable in both Chrome and Firefox.
    """
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                STATIC_URL_PATH, str(_WWW_DIR / "jinjaboard-strategy.js"), False
            )
        ]
    )
    await _async_ensure_lovelace_resource(hass)


def _lovelace_resources(hass: HomeAssistant) -> Any | None:
    """Return the Lovelace resources collection, or None if lovelace isn't set up yet.

    Shared by `_async_ensure_lovelace_resource` and `is_yaml_mode_resources` so
    there's only one place reaching into this non-public `hass.data` shape.
    """
    from homeassistant.components.lovelace.const import LOVELACE_DATA

    lovelace_data = hass.data.get(LOVELACE_DATA)
    return None if lovelace_data is None else lovelace_data.resources


def is_yaml_mode_resources(hass: HomeAssistant) -> bool:
    """True if Lovelace resources are managed via YAML rather than storage/UI.

    Used by config_flow.py to decide whether to show manual
    `configuration.yaml` setup instructions, since auto-registration (below)
    can't reach YAML-mode resources at all. Returns False (not True) if
    lovelace isn't set up yet — there's nothing conclusive to tell the user
    in that case, and `single_config_entry`/manifest dependencies mean this
    shouldn't happen for a real flow anyway.
    """
    from homeassistant.components.lovelace.resources import ResourceStorageCollection

    resources = _lovelace_resources(hass)
    return resources is not None and not isinstance(resources, ResourceStorageCollection)


async def _async_ensure_lovelace_resource(hass: HomeAssistant) -> None:
    """Best-effort auto-registration of our JS as a Lovelace resource.

    This reaches into `lovelace`'s internal storage collection, which is not
    a published third-party integration API. If its shape ever changes on a
    core upgrade, fail loudly with actionable instructions instead of
    crashing setup — the WS render command still works either way.
    """
    try:
        from homeassistant.components.lovelace.resources import (
            ResourceStorageCollection,
        )

        resources = _lovelace_resources(hass)
        if resources is None:
            _LOGGER.warning(
                "Lovelace isn't set up yet; couldn't auto-register the "
                "JinjaBoard frontend resource. %s",
                _MANUAL_STORAGE_RESOURCE_INSTRUCTIONS,
            )
            return

        if not isinstance(resources, ResourceStorageCollection):
            _LOGGER.warning(
                "Lovelace is running in YAML resource mode; JinjaBoard can't "
                "auto-register its frontend resource. %s",
                _MANUAL_YAML_RESOURCE_INSTRUCTIONS,
            )
            return

        if any(item["url"] == STATIC_URL_PATH for item in resources.async_items()):
            return  # Already registered.

        await resources.async_create_item(
            {"res_type": "module", "url": STATIC_URL_PATH}
        )
    except Exception:  # noqa: BLE001
        _LOGGER.exception(
            "Failed to auto-register the JinjaBoard frontend resource. %s",
            _MANUAL_STORAGE_RESOURCE_INSTRUCTIONS,
        )
