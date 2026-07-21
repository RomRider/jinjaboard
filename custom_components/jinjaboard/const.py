"""Constants for the JinjaBoard integration."""

DOMAIN = "jinjaboard"

# hass.data[DOMAIN][RENDER_SIGNAL_KEY] holds the single JinjaboardRenderSignal
# sensor entity (see sensor.py) — a fixed key, not per-config-entry, since
# manifest.json's single_config_entry guarantees there's only ever one.
RENDER_SIGNAL_KEY = "render_signal"
