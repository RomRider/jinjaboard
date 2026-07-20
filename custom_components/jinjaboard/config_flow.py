"""Config flow for the JinjaBoard integration."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN


class JinjaboardConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for JinjaBoard.

    There is nothing to configure per entry: the template path and variables
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
            return self.async_create_entry(title="JinjaBoard", data={})

        return self.async_show_form(step_id="user")
