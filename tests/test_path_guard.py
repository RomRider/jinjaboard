"""Tests for path_guard.resolve_config_path."""

from __future__ import annotations

from pathlib import Path

import pytest

from homeassistant.core import HomeAssistant

from custom_components.jinjaboard.path_guard import (
    JinjaboardPathError,
    resolve_config_path,
)


def test_resolves_relative_to_config_dir(hass: HomeAssistant) -> None:
    result = resolve_config_path(hass, "jinjaboard/home.yaml.j2")
    assert result == Path(hass.config.config_dir, "jinjaboard/home.yaml.j2").resolve()


def test_rejects_dotdot_traversal(hass: HomeAssistant) -> None:
    with pytest.raises(JinjaboardPathError):
        resolve_config_path(hass, "../../../../../../etc/hostname")


def test_rejects_absolute_path_escape(hass: HomeAssistant) -> None:
    # pathlib: Path(a) / "/etc/passwd" == Path("/etc/passwd") — the absolute
    # right-hand operand discards the base entirely. Must still be caught.
    with pytest.raises(JinjaboardPathError):
        resolve_config_path(hass, "/etc/passwd")


def test_base_dir_overrides_resolution_root(hass: HomeAssistant) -> None:
    base = Path(hass.config.config_dir) / "cards"
    result = resolve_config_path(hass, "kitchen.yaml.j2", base_dir=base)
    assert result == (base / "kitchen.yaml.j2").resolve()


def test_base_dir_still_confined_to_config_dir(hass: HomeAssistant) -> None:
    base = Path(hass.config.config_dir) / "cards"
    with pytest.raises(JinjaboardPathError):
        resolve_config_path(hass, "../../../../etc/hostname", base_dir=base)
