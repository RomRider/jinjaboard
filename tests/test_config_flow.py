"""Tests for the JinjaBoard config flow."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.setup import async_setup_component

from custom_components.jinjaboard.const import DOMAIN
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
