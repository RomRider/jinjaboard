"""Tests for frontend.py's static-path and Lovelace-resource registration."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.jinjaboard.frontend import (
    _STATIC_URL_PATH,
    _async_ensure_lovelace_resource,
    async_register_frontend,
)


async def test_registers_static_path(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, "http", {})

    with patch.object(
        hass.http, "async_register_static_paths"
    ) as mock_register, patch(
        "custom_components.jinjaboard.frontend._async_ensure_lovelace_resource"
    ):
        await async_register_frontend(hass)

    mock_register.assert_awaited_once()
    (configs,) = mock_register.await_args.args
    assert len(configs) == 1
    assert configs[0].url_path == _STATIC_URL_PATH


async def test_lovelace_resource_registered_once_on_entry_setup(
    hass: HomeAssistant, config_entry
) -> None:
    from homeassistant.components.lovelace.const import LOVELACE_DATA

    resources = hass.data[LOVELACE_DATA].resources
    matching = [item for item in resources.async_items() if item["url"] == _STATIC_URL_PATH]
    assert len(matching) == 1


async def test_lovelace_resource_registration_is_idempotent(
    hass: HomeAssistant, config_entry
) -> None:
    from homeassistant.components.lovelace.const import LOVELACE_DATA

    await _async_ensure_lovelace_resource(hass)
    await _async_ensure_lovelace_resource(hass)

    resources = hass.data[LOVELACE_DATA].resources
    matching = [item for item in resources.async_items() if item["url"] == _STATIC_URL_PATH]
    assert len(matching) == 1


async def test_missing_lovelace_data_logs_warning_without_raising(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    # No lovelace component set up on this bare `hass` — the fallback path
    # must log actionable instructions rather than crashing setup.
    await _async_ensure_lovelace_resource(hass)
    assert "couldn't auto-register" in caplog.text
