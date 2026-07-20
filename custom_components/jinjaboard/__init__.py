"""The JinjaBoard integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .frontend import async_register_frontend
from .websocket import async_setup_websocket_api


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up JinjaBoard from a config entry."""
    async_setup_websocket_api(hass)
    await async_register_frontend(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a JinjaBoard config entry."""
    return True
