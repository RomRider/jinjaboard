"""The JinjaBoard integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .frontend import async_register_frontend
from .websocket import async_setup_websocket_api

_PLATFORMS = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up JinjaBoard from a config entry."""
    async_setup_websocket_api(hass)
    await async_register_frontend(hass)
    # The single hidden sensor entity `sensor.py` sets up — see its module
    # docstring for why `jinjaboard/subscribe_render` needs it.
    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a JinjaBoard config entry."""
    return await hass.config_entries.async_unload_platforms(entry, _PLATFORMS)
