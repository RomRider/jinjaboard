"""Tests for the jinjaboard/render WebSocket command."""

from __future__ import annotations

from homeassistant.core import HomeAssistant


async def test_render_success(
    hass: HomeAssistant, config_entry, hass_ws_client, write_template
) -> None:
    write_template("home.yaml.j2", "views:\n  - title: \"{{ 'Jinja' + 'Board' }}\"\n")
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "jinjaboard/render", "template": "home.yaml.j2"}
    )
    response = await client.receive_json()
    assert response["success"] is True
    assert response["result"] == {"views": [{"title": "JinjaBoard"}]}


async def test_render_passes_variables(
    hass: HomeAssistant, config_entry, hass_ws_client, write_template
) -> None:
    write_template("greet.yaml.j2", "value: {{ jjb.name }}\n")
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "jinjaboard/render",
            "template": "greet.yaml.j2",
            "variables": {"name": "kitchen"},
        }
    )
    response = await client.receive_json()
    assert response["success"] is True
    assert response["result"] == {"value": "kitchen"}


async def test_render_available_to_non_admin_user(
    hass: HomeAssistant,
    config_entry,
    hass_ws_client,
    hass_read_only_access_token,
    write_template,
) -> None:
    """Any authenticated user can call this, not just admins — matches core's
    own render_template WS command precedent (see the project plan)."""
    write_template("home.yaml.j2", "ok: true\n")
    client = await hass_ws_client(hass, access_token=hass_read_only_access_token)
    await client.send_json_auto_id(
        {"type": "jinjaboard/render", "template": "home.yaml.j2"}
    )
    response = await client.receive_json()
    assert response["success"] is True


async def test_render_path_missing(
    hass: HomeAssistant, config_entry, hass_ws_client
) -> None:
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "jinjaboard/render", "template": "does_not_exist.yaml.j2"}
    )
    response = await client.receive_json()
    assert response["success"] is False
    assert response["error"]["code"] == "path_missing"


async def test_render_path_traversal_on_root_template(
    hass: HomeAssistant, config_entry, hass_ws_client
) -> None:
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "jinjaboard/render",
            "template": "../../../../../../etc/hostname",
        }
    )
    response = await client.receive_json()
    assert response["success"] is False
    assert response["error"]["code"] == "path_traversal"


async def test_render_path_traversal_via_include(
    hass: HomeAssistant, config_entry, hass_ws_client, write_template
) -> None:
    write_template(
        "root.yaml.j2", "cards: !include ../../../../../../etc/hostname\n"
    )
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "jinjaboard/render", "template": "root.yaml.j2"}
    )
    response = await client.receive_json()
    assert response["success"] is False
    assert response["error"]["code"] == "path_traversal"


async def test_render_include_not_found(
    hass: HomeAssistant, config_entry, hass_ws_client, write_template
) -> None:
    write_template("root.yaml.j2", "cards: !include missing.yaml.j2\n")
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "jinjaboard/render", "template": "root.yaml.j2"}
    )
    response = await client.receive_json()
    assert response["success"] is False
    assert response["error"]["code"] == "include_not_found"


async def test_render_template_error_includes_line_number(
    hass: HomeAssistant, config_entry, hass_ws_client, write_template
) -> None:
    write_template("broken.yaml.j2", "views:\n  - title: fine\n  - title: \"{{ nope }}\"\n")
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "jinjaboard/render", "template": "broken.yaml.j2"}
    )
    response = await client.receive_json()
    assert response["success"] is False
    assert response["error"]["code"] == "template_error"
    assert "Line 3" in response["error"]["message"]


async def test_render_yaml_parse_error_includes_raw_preview(
    hass: HomeAssistant, config_entry, hass_ws_client, write_template
) -> None:
    write_template(
        "bad_indent.yaml.j2",
        "views:\n  - title: Broken\n    cards:\n    - type: markdown\n        content: bad\n",
    )
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "jinjaboard/render", "template": "bad_indent.yaml.j2"}
    )
    response = await client.receive_json()
    assert response["success"] is False
    assert response["error"]["code"] == "yaml_parse_error"
    assert "title: Broken" in response["error"]["message"]
