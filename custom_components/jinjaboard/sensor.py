"""Internal diagnostic sensor used to nudge Home Assistant's frontend.

Not meant to be looked at by users directly — see `websocket.py`'s
`handle_subscribe_render` docstring for why this exists: home-assistant-
frontend's `checkStrategyShouldRegenerate()` only ever runs from a
dashboard/view/section's own `hass`-changed lifecycle hook (see `strategies/
get-strategy.ts`, `ha-panel-lovelace.ts`, `hui-view.ts`, `hui-section.ts`) —
and a `jinjaboard/subscribe_render` WS `event` message isn't itself a state
change, so it doesn't make `hass` tick. Without something else forcing a
recheck at the right moment, a dashboard only picks up a pushed render on
whatever *unrelated* entity state change happens to occur next — which can
easily be a *later* change than the one that produced the render being
displayed, showing stale-by-one-push content indefinitely on a quiet
instance (confirmed manually: turning a light on produced no visible
update; turning it back off then displayed the "on" render instead of the
fresh "off" one).

Bumping this entity's state immediately after every `subscribe_render` push
produces a real `state_changed` event — the one thing every connected
client's `hass` object reliably reacts to, via Home Assistant's own
`subscribeEntities` WS subscription (always active for any connected
frontend) — so the recheck happens right when the fresh data is actually
available, not whenever something unrelated next happens to change.
"""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, RENDER_SIGNAL_KEY


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the render-signal sensor for this config entry.

    Stored under a fixed `hass.data[DOMAIN][RENDER_SIGNAL_KEY]` key, not
    keyed by `entry.entry_id` — `manifest.json`'s `single_config_entry:
    true` guarantees there is ever only one, and `websocket.py`'s WS command
    handlers only have `hass` to work with, not the config entry.
    """
    entity = JinjaboardRenderSignal(entry)
    hass.data.setdefault(DOMAIN, {})[RENDER_SIGNAL_KEY] = entity
    async_add_entities([entity])


class JinjaboardRenderSignal(SensorEntity):
    """A hidden diagnostic counter, bumped after every subscribe_render push.

    The counter value itself is meaningless — only the act of it changing
    (a real `state_changed` event) matters. Diagnostic category + hidden by
    default keeps it out of the way of normal dashboards/entity lists, but
    it must stay enabled (not `entity_registry_enabled_default=False`) since
    a disabled entity never reaches the state machine and couldn't produce
    the state changes this whole mechanism depends on.
    """

    # `has_entity_name` + `translation_key` (rather than a plain `_attr_name`
    # string) is the modern, correct pattern — but for a device-less entity
    # it also means the *translated name itself* is what determines the
    # entity_id slug: `Entity.suggested_object_id` only ever feeds
    # `object_id_base`, which loses to the translated name in HA's own
    # entity-id-generation priority order (`name` override > `suggested_
    # object_id` — reserved for `internal_integration_suggested_object_id`,
    # not settable by third-party components — > `object_id_base`). So the
    # translation string (translations/en.json) is deliberately "Jinjaboard
    # render signal", not just "Render signal", to get `sensor.jinjaboard_
    # render_signal` rather than a bare `sensor.render_signal`.
    _attr_has_entity_name = True
    _attr_translation_key = "render_signal"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_visible_default = False
    _attr_should_poll = False
    _attr_native_value = 0

    def __init__(self, entry: ConfigEntry) -> None:
        self._attr_unique_id = f"{entry.entry_id}_render_signal"

    @callback
    def bump(self) -> None:
        """Increment the counter and push the new state immediately.

        Safe to call before this entity has finished being added (`self.
        hass` is only set once `async_added_to_hass` runs) — a bump that
        arrives too early is simply a no-op rather than raising, since the
        very first `subscribe_render` call for a freshly-started Home
        Assistant could plausibly race the sensor platform's own setup.
        """
        self._attr_native_value += 1
        if self.hass is not None:
            self.async_write_ha_state()
