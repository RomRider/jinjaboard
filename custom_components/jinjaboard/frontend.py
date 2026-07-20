"""Register JinjaBoard's frontend bundle and its Lovelace resource entry."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

_WWW_DIR = Path(__file__).parent / "www"
_STATIC_URL_PATH = f"/{DOMAIN}_static/jinjaboard-strategy.js"

_MANUAL_RESOURCE_INSTRUCTIONS = (
    "Add it manually instead: Settings > Dashboards > the ⋮ menu > "
    f"Resources > Add Resource > URL: {_STATIC_URL_PATH}, "
    "Resource type: JavaScript Module."
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
                _STATIC_URL_PATH, str(_WWW_DIR / "jinjaboard-strategy.js"), False
            )
        ]
    )
    await _async_ensure_lovelace_resource(hass)


async def _async_ensure_lovelace_resource(hass: HomeAssistant) -> None:
    """Best-effort auto-registration of our JS as a Lovelace resource.

    This reaches into `lovelace`'s internal storage collection, which is not
    a published third-party integration API. If its shape ever changes on a
    core upgrade, fail loudly with actionable instructions instead of
    crashing setup — the WS render command still works either way.
    """
    try:
        from homeassistant.components.lovelace.const import LOVELACE_DATA
        from homeassistant.components.lovelace.resources import (
            ResourceStorageCollection,
        )

        lovelace_data = hass.data.get(LOVELACE_DATA)
        if lovelace_data is None:
            _LOGGER.warning(
                "Lovelace isn't set up yet; couldn't auto-register the "
                "JinjaBoard frontend resource. %s",
                _MANUAL_RESOURCE_INSTRUCTIONS,
            )
            return

        resources = lovelace_data.resources
        if not isinstance(resources, ResourceStorageCollection):
            _LOGGER.warning(
                "Lovelace is running in YAML resource mode; JinjaBoard can't "
                "auto-register its frontend resource. %s",
                _MANUAL_RESOURCE_INSTRUCTIONS,
            )
            return

        if any(item["url"] == _STATIC_URL_PATH for item in resources.async_items()):
            return  # Already registered.

        await resources.async_create_item(
            {"res_type": "module", "url": _STATIC_URL_PATH}
        )
    except Exception:  # noqa: BLE001
        _LOGGER.exception(
            "Failed to auto-register the JinjaBoard frontend resource. %s",
            _MANUAL_RESOURCE_INSTRUCTIONS,
        )
