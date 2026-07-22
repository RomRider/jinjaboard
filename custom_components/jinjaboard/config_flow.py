"""Config flow for the JinjaBoard integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import CONF_ALLOWED_TEMPLATES, CONF_IS_DIR, CONF_PATH, DOMAIN
from .frontend import STATIC_URL_PATH, is_yaml_mode_resources
from .path_guard import JinjaboardPathError, resolve_config_path

# Options-flow selector field, distinct from CONF_PATH: identifies *which*
# existing allowlist entry to remove (by index into the stored list), not a
# filesystem path itself.
CONF_ENTRY_INDEX = "entry_index"


class JinjaboardConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for JinjaBoard.

    There is nothing to configure per entry at *setup* time: the template
    path and globals for each dashboard live in the dashboard's own YAML
    (`strategy.options`), not in a config entry. This flow only exists to
    give the integration a standard, UI-discoverable way to be enabled.
    The admin-managed template allowlist (which files/directories are
    permitted as a `template`) lives in the entry's *options*, managed via
    `JinjaboardOptionsFlowHandler` below, after initial setup.
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

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> JinjaboardOptionsFlowHandler:
        """Get the options flow for this handler."""
        return JinjaboardOptionsFlowHandler()


class JinjaboardOptionsFlowHandler(OptionsFlow):
    """Manage the admin-curated allowlist of files permitted as a `template`.

    Every action step (add/remove) commits with `async_create_entry` and
    closes the dialog, matching the pattern used by other core integrations
    that add/remove list entries through options (e.g. purpleair's
    `OptionsFlowHandler.async_step_choose_sensor`) — reopening "Configure"
    re-enters `async_step_init` for the next action, so there's no need for
    an in-flow "back to menu" loop.
    """

    def _entries(self) -> list[dict[str, Any]]:
        return list(self.config_entry.options.get(CONF_ALLOWED_TEMPLATES, []))

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the manage menu."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["add_entry", "remove_entry", "view_entries"],
            description_placeholders={"count": str(len(self._entries()))},
        )

    async def async_step_add_entry(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add a file or directory to the allowlist."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                resolve_config_path(self.hass, user_input[CONF_PATH])
            except JinjaboardPathError:
                errors["base"] = "path_traversal"
            else:
                entries = self._entries()
                new_entry = {
                    CONF_PATH: user_input[CONF_PATH],
                    CONF_IS_DIR: user_input[CONF_IS_DIR],
                }
                if new_entry not in entries:
                    entries.append(new_entry)
                return self.async_create_entry(
                    data={
                        **self.config_entry.options,
                        CONF_ALLOWED_TEMPLATES: entries,
                    }
                )

        return self.async_show_form(
            step_id="add_entry",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PATH): str,
                    vol.Required(CONF_IS_DIR, default=False): bool,
                }
            ),
            errors=errors,
        )

    async def async_step_remove_entry(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Remove a file or directory from the allowlist."""
        entries = self._entries()
        if not entries:
            return self.async_abort(reason="no_entries")

        if user_input is not None:
            index = int(user_input[CONF_ENTRY_INDEX])
            remaining = [entry for i, entry in enumerate(entries) if i != index]
            return self.async_create_entry(
                data={
                    **self.config_entry.options,
                    CONF_ALLOWED_TEMPLATES: remaining,
                }
            )

        options = [
            SelectOptionDict(
                value=str(i),
                label=f"{entry[CONF_PATH]}" + (" (folder)" if entry[CONF_IS_DIR] else ""),
            )
            for i, entry in enumerate(entries)
        ]
        return self.async_show_form(
            step_id="remove_entry",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ENTRY_INDEX): SelectSelector(
                        SelectSelectorConfig(options=options, mode=SelectSelectorMode.DROPDOWN)
                    ),
                }
            ),
        )

    async def async_step_view_entries(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the current allowlist (read-only)."""
        entries = self._entries()

        if user_input is not None:
            # No-op: viewing doesn't mutate the entry, just closes the flow.
            return self.async_create_entry(data=self.config_entry.options)

        listing = "\n".join(
            f"- {entry[CONF_PATH]}" + (" (folder)" if entry[CONF_IS_DIR] else "")
            for entry in entries
        ) or "_No files authorized yet._"

        return self.async_show_form(
            step_id="view_entries",
            data_schema=vol.Schema({}),
            description_placeholders={"listing": listing},
        )
