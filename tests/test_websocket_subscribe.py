"""Tests for the jinjaboard/subscribe_render WebSocket command."""

from __future__ import annotations

import asyncio

import pytest

from homeassistant.core import HomeAssistant

from custom_components.jinjaboard.const import DOMAIN, RENDER_SIGNAL_KEY


@pytest.fixture(autouse=True)
def _fast_debounce(monkeypatch: pytest.MonkeyPatch) -> None:
    """Shrink the render-redo debounce so tests don't wait 0.5s per change.

    `Debouncer` schedules via `hass.loop.call_later` (real wall-clock time,
    not `homeassistant.util.dt`), so tests that trigger a re-render still
    need a real `asyncio.sleep` — this just keeps that sleep short.
    """
    monkeypatch.setattr(
        "custom_components.jinjaboard.websocket._RENDER_DEBOUNCE_SECONDS", 0.05
    )


async def _settle(hass: HomeAssistant) -> None:
    """Give the debounced re-render time to fire and complete."""
    await hass.async_block_till_done()
    await asyncio.sleep(0.2)
    await hass.async_block_till_done()


async def test_subscribe_render_ack_then_initial_event(
    hass: HomeAssistant, config_entry, hass_ws_client, write_template
) -> None:
    write_template("home.yaml.j2", "views:\n  - title: \"{{ 'Jinja' + 'Board' }}\"\n")
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "jinjaboard/subscribe_render", "template": "home.yaml.j2"}
    )

    ack = await client.receive_json()
    assert ack["success"] is True

    event = await client.receive_json()
    assert event["type"] == "event"
    assert event["event"]["result"] == {"views": [{"title": "JinjaBoard"}]}


async def test_subscribe_render_pushes_update_on_tracked_entity_change(
    hass: HomeAssistant, config_entry, hass_ws_client, write_template
) -> None:
    hass.states.async_set("light.kitchen", "off")
    write_template("home.yaml.j2", "value: \"{{ states('light.kitchen') }}\"\n")
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "jinjaboard/subscribe_render", "template": "home.yaml.j2"}
    )
    await client.receive_json()  # ack
    initial = await client.receive_json()
    assert initial["event"]["result"] == {"value": "off"}

    hass.states.async_set("light.kitchen", "on")
    await _settle(hass)

    updated = await client.receive_json()
    assert updated["event"]["result"] == {"value": "on"}


async def test_subscribe_render_bumps_render_signal_on_every_push(
    hass: HomeAssistant, config_entry, hass_ws_client, write_template
) -> None:
    """Regression test for the stale-content bug: a `subscribe_render` push
    must bump the shared render-signal entity so every connected client's
    `hass` ticks right when fresh data is available, instead of only being
    noticed on some later, unrelated entity change (see sensor.py)."""
    signal = hass.data[DOMAIN][RENDER_SIGNAL_KEY]
    signal_state = lambda: hass.states.get(signal.entity_id).state  # noqa: E731

    hass.states.async_set("light.kitchen", "off")
    write_template("home.yaml.j2", "value: \"{{ states('light.kitchen') }}\"\n")
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "jinjaboard/subscribe_render", "template": "home.yaml.j2"}
    )
    await client.receive_json()  # ack
    await client.receive_json()  # initial event
    after_initial = signal_state()

    hass.states.async_set("light.kitchen", "on")
    await _settle(hass)
    await client.receive_json()  # the pushed update
    after_update = signal_state()

    assert after_update != after_initial


async def test_subscribe_render_debounces_rapid_changes(
    hass: HomeAssistant, config_entry, hass_ws_client, write_template
) -> None:
    hass.states.async_set("light.kitchen", "off")
    write_template("home.yaml.j2", "value: \"{{ states('light.kitchen') }}\"\n")
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "jinjaboard/subscribe_render", "template": "home.yaml.j2"}
    )
    await client.receive_json()  # ack
    await client.receive_json()  # initial event

    for state in ("on", "off", "on", "off", "on"):
        hass.states.async_set("light.kitchen", state)
        await hass.async_block_till_done()
    await _settle(hass)

    updated = await client.receive_json()
    assert updated["event"]["result"] == {"value": "on"}

    with pytest.raises((asyncio.TimeoutError, TimeoutError)):
        await client.receive_json(timeout=0.2)


async def test_subscribe_render_include_tree_change_updates_tracked_entities(
    hass: HomeAssistant, config_entry, hass_ws_client, write_template
) -> None:
    """A render that conditionally `!include`s different files based on one
    entity's state must, after switching branches, start tracking whatever
    the *new* branch depends on — not just what the first render happened
    to touch."""
    hass.states.async_set("input_boolean.branch", "off")
    hass.states.async_set("sensor.a", "a1")
    hass.states.async_set("sensor.b", "b1")
    write_template(
        "root.yaml.j2",
        "{% if states('input_boolean.branch') == 'on' %}\n"
        "value: !include branch_a.yaml.j2\n"
        "{% else %}\n"
        "value: !include branch_b.yaml.j2\n"
        "{% endif %}\n",
    )
    write_template("branch_a.yaml.j2", "\"{{ states('sensor.a') }}\"\n")
    write_template("branch_b.yaml.j2", "\"{{ states('sensor.b') }}\"\n")

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "jinjaboard/subscribe_render", "template": "root.yaml.j2"}
    )
    await client.receive_json()  # ack
    initial = await client.receive_json()
    assert initial["event"]["result"] == {"value": "b1"}

    # Changing sensor.a shouldn't matter yet — only branch_b (sensor.b) is
    # currently included/tracked.
    hass.states.async_set("sensor.a", "a2")
    await _settle(hass)
    with pytest.raises((asyncio.TimeoutError, TimeoutError)):
        await client.receive_json(timeout=0.2)

    # Flip the branch itself — proves the branching condition is tracked.
    hass.states.async_set("input_boolean.branch", "on")
    await _settle(hass)
    switched = await client.receive_json()
    assert switched["event"]["result"] == {"value": "a2"}

    # Now sensor.b (old branch) shouldn't matter, but sensor.a (new branch)
    # should — proves the tracker was rebuilt around the new dependency set.
    hass.states.async_set("sensor.b", "b2")
    await _settle(hass)
    with pytest.raises((asyncio.TimeoutError, TimeoutError)):
        await client.receive_json(timeout=0.2)

    hass.states.async_set("sensor.a", "a3")
    await _settle(hass)
    final = await client.receive_json()
    assert final["event"]["result"] == {"value": "a3"}


async def test_subscribe_render_error_keeps_previous_tracker_alive(
    hass: HomeAssistant, config_entry, hass_ws_client, write_template
) -> None:
    hass.states.async_set("light.kitchen", "off")
    target = write_template(
        "root.yaml.j2", "value: !include included.yaml.j2\n"
    )
    write_template("included.yaml.j2", "\"{{ states('light.kitchen') }}\"\n")

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "jinjaboard/subscribe_render", "template": "root.yaml.j2"}
    )
    await client.receive_json()  # ack
    initial = await client.receive_json()
    assert initial["event"]["result"] == {"value": "off"}

    # Break the include, then trigger a re-render — expect an error push,
    # not a torn-down subscription.
    (target.parent / "included.yaml.j2").unlink()
    hass.states.async_set("light.kitchen", "on")
    await _settle(hass)
    errored = await client.receive_json()
    assert errored["event"]["error"]["code"] == "include_not_found"

    # The old tracker (from the last *successful* render) should still be
    # alive — a further change to the originally-tracked entity still fires.
    hass.states.async_set("light.kitchen", "off")
    await _settle(hass)
    recovered_attempt = await client.receive_json()
    assert recovered_attempt["event"]["error"]["code"] == "include_not_found"


async def test_subscribe_render_unsubscribe_stops_further_pushes(
    hass: HomeAssistant, config_entry, hass_ws_client, write_template
) -> None:
    hass.states.async_set("light.kitchen", "off")
    write_template("home.yaml.j2", "value: \"{{ states('light.kitchen') }}\"\n")
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "jinjaboard/subscribe_render", "template": "home.yaml.j2"}
    )
    ack = await client.receive_json()
    subscription_id = ack["id"]
    await client.receive_json()  # initial event

    await client.send_json_auto_id(
        {"type": "unsubscribe_events", "subscription": subscription_id}
    )
    await client.receive_json()  # ack for unsubscribe

    hass.states.async_set("light.kitchen", "on")
    await _settle(hass)

    with pytest.raises((asyncio.TimeoutError, TimeoutError)):
        await client.receive_json(timeout=0.2)


@pytest.mark.parametrize(
    ("template", "error_code"),
    [
        ("../../../../../../etc/hostname", "path_traversal"),
        ("does_not_exist.yaml.j2", "path_missing"),
    ],
)
async def test_subscribe_render_initial_failure_error_codes(
    hass: HomeAssistant,
    config_entry,
    hass_ws_client,
    template: str,
    error_code: str,
) -> None:
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "jinjaboard/subscribe_render", "template": template}
    )
    response = await client.receive_json()
    assert response["success"] is False
    assert response["error"]["code"] == error_code
