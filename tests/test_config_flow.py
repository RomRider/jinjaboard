"""Tests for the JinjaBoard config flow."""

from __future__ import annotations

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.setup import async_setup_component

from custom_components.jinjaboard.const import CONF_ALLOWED_TEMPLATES, DOMAIN
from custom_components.jinjaboard.frontend import STATIC_URL_PATH


async def test_flow_completes_with_no_fields(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "JinjaBoard"
    assert result["data"] == {}


async def test_flow_shows_yaml_resources_instructions_in_yaml_mode(
    hass: HomeAssistant,
) -> None:
    # Set up lovelace ourselves first, in YAML resource mode, so it's already
    # in `hass.config.components` by the time the flow's own dependency
    # processing runs (which would otherwise set it up with defaults, i.e.
    # storage mode).
    assert await async_setup_component(
        hass, "lovelace", {"lovelace": {"resource_mode": "yaml"}}
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "yaml_resources"
    assert result["description_placeholders"] == {"resource_url": STATIC_URL_PATH}

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {}


async def test_second_instance_aborts_already_configured(
    hass: HomeAssistant, config_entry
) -> None:
    # single_config_entry: true (manifest.json) is enforced by core before
    # our own async_step_user even runs, so the abort happens at async_init.
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_options_init_shows_menu(hass: HomeAssistant, config_entry) -> None:
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "init"
    assert set(result["menu_options"]) == {"add_entry", "remove_entry", "view_entries"}


async def test_options_add_entry_persists_path(hass: HomeAssistant, config_entry) -> None:
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "add_entry"}
    )
    assert result["step_id"] == "add_entry"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"path": "dashboards/home.yaml.j2", "is_dir": False}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert {"path": "dashboards/home.yaml.j2", "is_dir": False} in result["data"][
        CONF_ALLOWED_TEMPLATES
    ]


async def test_options_add_entry_rejects_traversal(hass: HomeAssistant, config_entry) -> None:
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "add_entry"}
    )

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"path": "../../../../etc/hostname", "is_dir": False}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "add_entry"
    assert result["errors"] == {"base": "path_traversal"}


async def test_options_remove_entry_removes_selected(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        options={
            CONF_ALLOWED_TEMPLATES: [
                {"path": "home.yaml.j2", "is_dir": False},
                {"path": "dashboards", "is_dir": True},
            ]
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "remove_entry"}
    )
    assert result["step_id"] == "remove_entry"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"entry_index": "0"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_ALLOWED_TEMPLATES] == [{"path": "dashboards", "is_dir": True}]


async def test_options_remove_entry_aborts_when_empty(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, options={CONF_ALLOWED_TEMPLATES: []})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "remove_entry"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_entries"


async def test_options_view_entries_shows_listing_and_does_not_mutate(
    hass: HomeAssistant,
) -> None:
    entries = [{"path": "home.yaml.j2", "is_dir": False}]
    entry = MockConfigEntry(domain=DOMAIN, options={CONF_ALLOWED_TEMPLATES: entries})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "view_entries"}
    )
    assert result["step_id"] == "view_entries"
    assert "home.yaml.j2" in result["description_placeholders"]["listing"]

    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_ALLOWED_TEMPLATES] == entries
