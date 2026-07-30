"""Tests for path_guard.resolve_config_path."""

from __future__ import annotations

from pathlib import Path

import pytest

from homeassistant.core import HomeAssistant

from custom_components.jinjaboard.path_guard import (
    JinjaboardPathError,
    normalize_path,
    resolve_config_path,
)


def test_resolves_relative_to_config_dir(hass: HomeAssistant) -> None:
    result = resolve_config_path(hass, "jinjaboard/home.yaml.j2")
    assert result == normalize_path(
        Path(hass.config.config_dir, "jinjaboard/home.yaml.j2")
    )


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
    assert result == normalize_path(base / "kitchen.yaml.j2")


def test_base_dir_still_confined_to_config_dir(hass: HomeAssistant) -> None:
    base = Path(hass.config.config_dir) / "cards"
    with pytest.raises(JinjaboardPathError):
        resolve_config_path(hass, "../../../../etc/hostname", base_dir=base)


def test_follows_symlink_pointing_outside_config_dir(
    hass: HomeAssistant, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """A symlink placed *inside* config_dir (e.g. this project's own
    devcontainer setup, which symlinks `/config/test` to a directory outside
    `/config`) must still resolve successfully — the guard's job is to
    reject a path/include argument that types its way outside config_dir via
    `..`/absolute segments, not to forbid symlinks an operator deliberately
    placed under config_dir."""
    external_dir = tmp_path_factory.mktemp("external")
    (external_dir / "kitchen.yaml.j2").write_text("kitchen: true\n")

    symlinked_dir = Path(hass.config.config_dir) / "linked"
    symlinked_dir.symlink_to(external_dir, target_is_directory=True)

    result = resolve_config_path(hass, "linked/kitchen.yaml.j2")
    assert result == normalize_path(symlinked_dir / "kitchen.yaml.j2")
    assert result.read_text() == "kitchen: true\n"


def test_rejects_dotdot_traversal_through_symlink(
    hass: HomeAssistant, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """`..` segments written into the relative path must still be rejected
    even when part of the path they're appended to passes through a
    symlinked directory."""
    external_dir = tmp_path_factory.mktemp("external")
    symlinked_dir = Path(hass.config.config_dir) / "linked2"
    symlinked_dir.symlink_to(external_dir, target_is_directory=True)

    with pytest.raises(JinjaboardPathError):
        resolve_config_path(hass, "linked2/../../../../etc/hostname")
