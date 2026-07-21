"""Shared pytest fixtures for the JinjaBoard test suite."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.core import HomeAssistant

from custom_components.jinjaboard.const import DOMAIN

pytest_plugins = ["pytest_homeassistant_custom_component"]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Make `hass.loader` discover `custom_components/jinjaboard` for every test."""


@pytest.fixture
def hass_config_dir(hass_tmp_config_dir: str) -> str:
    """Give each test its own throwaway config dir instead of the shared
    `pytest_homeassistant_custom_component` package directory, since tests
    write their own template fixture files into it."""
    return hass_tmp_config_dir


@pytest.fixture
def write_template(hass: HomeAssistant) -> Callable[[str, str], Path]:
    """Write `content` to `relative_path` under `hass.config.config_dir`.

    Returns the resolved absolute `Path`; the caller passes `relative_path`
    to the code under test (e.g. `render_template`, the `jinjaboard/render`
    WS command), matching how a real template file is referenced.
    """

    def _write(relative_path: str, content: str) -> Path:
        target = Path(hass.config.config_dir) / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        return target

    return _write


@pytest.fixture
async def config_entry(hass: HomeAssistant) -> MockConfigEntry:
    """A field-less JinjaBoard config entry, set up and ready."""
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry
