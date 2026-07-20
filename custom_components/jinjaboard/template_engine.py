"""Render JinjaBoard templates through Home Assistant's own Jinja2 engine."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, TemplateError
from homeassistant.helpers.template import Template
from homeassistant.util.yaml.loader import parse_yaml


class JinjaboardError(Exception):
    """Base error for JinjaBoard template rendering."""


class JinjaboardTemplateError(JinjaboardError):
    """Raised when Jinja2 rendering itself fails (bad syntax, runtime error)."""


class JinjaboardYamlError(JinjaboardError):
    """Raised when the rendered output is not valid YAML."""

    def __init__(self, raw_output: str) -> None:
        super().__init__("Rendered template output was not valid YAML")
        self.raw_output = raw_output


def render_template(
    hass: HomeAssistant, source: str, variables: dict[str, Any] | None = None
) -> Any:
    """Render `source` as an HA Jinja2 template and parse the result as YAML.

    `source` is authored as YAML with embedded Jinja (`{{ }}` / `{% %}`) —
    the same convention lovelace_gen used — not a template whose Jinja body
    directly constructs the output structure. We render it to a plain string
    first (with `parse_result=False`, since `Template.async_render`'s own
    result parsing uses `ast.literal_eval` and isn't what we want here
    either), then parse that string as YAML.
    """
    template = Template(source, hass)
    try:
        raw = template.async_render(variables, parse_result=False)
    except TemplateError as err:
        raise JinjaboardTemplateError(str(err)) from err

    try:
        return parse_yaml(raw)
    except HomeAssistantError as err:
        raise JinjaboardYamlError(raw) from err
