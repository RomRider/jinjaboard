"""Tests for async_setup_entry/async_unload_entry wiring.

Asserted end-to-end (does the WS command actually work after setup) rather
than by inspecting internals — that's what these functions are for.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from custom_components.jinjaboard.const import DOMAIN, RENDER_SIGNAL_KEY


async def test_setup_entry_creates_render_signal_entity(
    hass: HomeAssistant, config_entry
) -> None:
    """`jinjaboard/subscribe_render` (see websocket.py) needs this entity to
    exist and be enabled — see sensor.py's module docstring for why."""
    signal = hass.data[DOMAIN][RENDER_SIGNAL_KEY]
    state = hass.states.get(signal.entity_id)
    assert state is not None

    before = state.state
    signal.bump()
    after = hass.states.get(signal.entity_id).state
    assert after != before


async def test_setup_entry_registers_working_ws_command(
    hass: HomeAssistant, config_entry, hass_ws_client, write_template
) -> None:
    assert config_entry.state is ConfigEntryState.LOADED

    write_template("home.yaml.j2", "ok: true\n")
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "jinjaboard/render", "template": "home.yaml.j2"}
    )
    response = await client.receive_json()
    assert response["success"] is True
    assert response["result"] == {"ok": True}


async def test_unload_entry_succeeds(hass: HomeAssistant, config_entry) -> None:
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.NOT_LOADED
