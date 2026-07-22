"""Tests for the admin-managed template allowlist."""

from __future__ import annotations

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.core import HomeAssistant

from custom_components.jinjaboard.const import CONF_ALLOWED_TEMPLATES, DOMAIN
from custom_components.jinjaboard.path_guard import resolve_config_path
from custom_components.jinjaboard.template_allowlist import is_template_authorized


async def _setup_entry(hass: HomeAssistant, entries: list[dict]) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, options={CONF_ALLOWED_TEMPLATES: entries})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_empty_allowlist_denies_everything(hass: HomeAssistant) -> None:
    await _setup_entry(hass, [])
    path = resolve_config_path(hass, "home.yaml.j2")
    assert is_template_authorized(hass, path) is False


async def test_exact_file_entry_matches_only_that_file(hass: HomeAssistant) -> None:
    await _setup_entry(hass, [{"path": "home.yaml.j2", "is_dir": False}])

    assert is_template_authorized(hass, resolve_config_path(hass, "home.yaml.j2")) is True
    assert is_template_authorized(hass, resolve_config_path(hass, "other.yaml.j2")) is False


async def test_directory_entry_matches_nested_files(hass: HomeAssistant) -> None:
    await _setup_entry(hass, [{"path": "dashboards", "is_dir": True}])

    assert (
        is_template_authorized(hass, resolve_config_path(hass, "dashboards/home.yaml.j2"))
        is True
    )
    assert (
        is_template_authorized(
            hass, resolve_config_path(hass, "dashboards/nested/kitchen.yaml.j2")
        )
        is True
    )
    assert is_template_authorized(hass, resolve_config_path(hass, "other/home.yaml.j2")) is False


async def test_directory_entry_does_not_match_sibling_with_shared_prefix(
    hass: HomeAssistant,
) -> None:
    """`dashboards` must not authorize `dashboards-backup/...` via a naive string prefix check."""
    await _setup_entry(hass, [{"path": "dashboards", "is_dir": True}])

    assert (
        is_template_authorized(hass, resolve_config_path(hass, "dashboards-backup/home.yaml.j2"))
        is False
    )


async def test_stale_entry_outside_config_dir_is_ignored(hass: HomeAssistant) -> None:
    """An allowlist entry that no longer confines to config_dir never matches, doesn't raise."""
    await _setup_entry(hass, [{"path": "../../../etc", "is_dir": True}])

    assert is_template_authorized(hass, resolve_config_path(hass, "home.yaml.j2")) is False
