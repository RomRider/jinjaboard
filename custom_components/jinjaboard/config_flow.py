"""Config flow for the JinjaBoard integration."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN
from .frontend import STATIC_URL_PATH, is_yaml_mode_resources


class JinjaboardConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for JinjaBoard.

    There is nothing to configure per entry: the template path and globals
    for each dashboard live in the dashboard's own YAML (`strategy.options`),
    not in a config entry. This flow only exists to give the integration a
    standard, UI-discoverable way to be enabled.
    """

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the single confirmation step."""
        if user_input is not None:
            if is_yaml_mode_resources(self.hass):
                return await self.async_step_yaml_resources()
            return self.async_create_entry(title="JinjaBoard", data={})

        return self.async_show_form(step_id="user")

    async def async_step_yaml_resources(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show what to add to configuration.yaml when Lovelace resources are YAML-managed.

        `frontend.async_register_frontend`'s auto-registration (see
        frontend.py) can only add to Lovelace's *storage*-mode resources
        collection — there's no equivalent write path for YAML-mode
        resources, so the user has to hand-edit their config. `lovelace` is
        a hard dependency in manifest.json, so it's already set up by the
        time this flow runs and `is_yaml_mode_resources` reflects real state.
        """
        if user_input is not None:
            return self.async_create_entry(title="JinjaBoard", data={})

        return self.async_show_form(
            step_id="yaml_resources",
            description_placeholders={"resource_url": STATIC_URL_PATH},
        )
