"""Tests for the jinjaboard/render WebSocket command."""

from __future__ import annotations

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.core import HomeAssistant

from custom_components.jinjaboard.const import CONF_ALLOWED_TEMPLATES, DOMAIN


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


async def test_render_passes_globals(
    hass: HomeAssistant, config_entry, hass_ws_client, write_template
) -> None:
    write_template("greet.yaml.j2", "value: {{ jjb.globals.name }}\n")
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "jinjaboard/render",
            "template": "greet.yaml.j2",
            "globals": {"name": "kitchen"},
        }
    )
    response = await client.receive_json()
    assert response["success"] is True
    assert response["result"] == {"value": "kitchen"}


async def test_render_passes_globals_as_file_path(
    hass: HomeAssistant, config_entry, hass_ws_client, write_template
) -> None:
    write_template("globals.yaml", "name: kitchen\n")
    write_template("greet.yaml.j2", "value: {{ jjb.globals.name }}\n")
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "jinjaboard/render",
            "template": "greet.yaml.j2",
            "globals": "globals.yaml",
        }
    )
    response = await client.receive_json()
    assert response["success"] is True
    assert response["result"] == {"value": "kitchen"}


async def test_render_globals_file_invalid_yaml(
    hass: HomeAssistant, config_entry, hass_ws_client, write_template
) -> None:
    write_template("globals.yaml", "- a\n- b\n")
    write_template("greet.yaml.j2", "value: {{ jjb.globals.name }}\n")
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "jinjaboard/render",
            "template": "greet.yaml.j2",
            "globals": "globals.yaml",
        }
    )
    response = await client.receive_json()
    assert response["success"] is False
    assert response["error"]["code"] == "globals_error"


async def test_render_passes_macros(
    hass: HomeAssistant, config_entry, hass_ws_client, write_template
) -> None:
    write_template("macros/greet.yaml.j2", "{% macro hi(name) %}Hi {{ name }}{% endmacro %}\n")
    write_template("root.yaml.j2", "value: \"{{ jjb.macros.hi('kitchen') }}\"\n")
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "jinjaboard/render",
            "template": "root.yaml.j2",
            "macros": ["macros/greet.yaml.j2"],
        }
    )
    response = await client.receive_json()
    assert response["success"] is True
    assert response["result"] == {"value": "Hi kitchen"}


async def test_render_macro_not_found(
    hass: HomeAssistant, config_entry, hass_ws_client, write_template
) -> None:
    write_template("root.yaml.j2", "ok: true\n")
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "jinjaboard/render",
            "template": "root.yaml.j2",
            "macros": ["macros/missing.yaml.j2"],
        }
    )
    response = await client.receive_json()
    assert response["success"] is False
    assert response["error"]["code"] == "include_not_found"


async def test_render_exposes_jjb_user_from_authenticated_connection(
    hass: HomeAssistant, config_entry, hass_ws_client, write_template
) -> None:
    """`jjb.user` is derived from the WS connection's own authenticated
    user — not sent by the frontend, so there's no request field for it."""
    write_template(
        "whoami.yaml.j2",
        "name: {{ jjb.user.name }}\nis_admin: {{ jjb.user.is_admin }}\n"
        "is_owner: {{ jjb.user.is_owner }}\n",
    )
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "jinjaboard/render", "template": "whoami.yaml.j2"}
    )
    response = await client.receive_json()
    assert response["success"] is True
    assert response["result"] == {
        "name": "Mock User",
        "is_admin": True,
        "is_owner": False,
    }


async def test_render_jjb_user_reflects_read_only_user(
    hass: HomeAssistant,
    config_entry,
    hass_ws_client,
    hass_read_only_access_token,
    write_template,
) -> None:
    write_template("whoami.yaml.j2", "is_admin: {{ jjb.user.is_admin }}\n")
    client = await hass_ws_client(hass, access_token=hass_read_only_access_token)
    await client.send_json_auto_id(
        {"type": "jinjaboard/render", "template": "whoami.yaml.j2"}
    )
    response = await client.receive_json()
    assert response["success"] is True
    assert response["result"] == {"is_admin": False}


async def test_render_passes_client_context(
    hass: HomeAssistant, config_entry, hass_ws_client, write_template
) -> None:
    write_template(
        "device.yaml.j2",
        "ua: {{ jjb.client.user_agent }}\n"
        "width: {{ jjb.client.viewport.width }}\n"
        "browser_mod_id: {{ jjb.client.browser_mod_id }}\n"
        "language: {{ jjb.client.language }}\n"
        "is_dark_theme: {{ jjb.client.is_dark_theme }}\n",
    )
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "jinjaboard/render",
            "template": "device.yaml.j2",
            "client": {
                "user_agent": "Mozilla/5.0",
                "viewport": {"width": 1024, "height": 768},
                "browser_mod_id": "kitchen-tablet",
                "language": "en",
                "is_dark_theme": True,
            },
        }
    )
    response = await client.receive_json()
    assert response["success"] is True
    assert response["result"] == {
        "ua": "Mozilla/5.0",
        "width": 1024,
        "browser_mod_id": "kitchen-tablet",
        "language": "en",
        "is_dark_theme": True,
    }


async def test_render_jjb_client_defaults_safely_when_absent(
    hass: HomeAssistant, config_entry, hass_ws_client, write_template
) -> None:
    """No `client` payload at all — `jjb.client.*` fields should be
    reachable (as undefined) without raising under `strict=True`, matching
    `jjb.globals`/`jjb.inc`'s existing behavior for an unset dashboard."""
    write_template(
        "device.yaml.j2", "ua: {{ jjb.client.user_agent | default('n/a') }}\n"
    )
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "jinjaboard/render", "template": "device.yaml.j2"}
    )
    response = await client.receive_json()
    assert response["success"] is True
    assert response["result"] == {"ua": "n/a"}


async def test_render_rejects_malformed_client_payload(
    hass: HomeAssistant, config_entry, hass_ws_client, write_template
) -> None:
    write_template("device.yaml.j2", "ok: true\n")
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "jinjaboard/render",
            "template": "device.yaml.j2",
            "client": {"viewport": {"width": "not-a-number"}},
        }
    )
    response = await client.receive_json()
    assert response["success"] is False
    assert response["error"]["code"] == "invalid_format"


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
    message = response["error"]["message"]
    assert "title: Broken" in message
    # The raw preview starts on its own line, after the explanatory
    # sentence, and keeps the rendered output's *real* line breaks rather
    # than a `repr()`-escaped `\\n` — otherwise a normally multi-line
    # rendered YAML preview collapses into one unreadable line.
    assert message.endswith(
        "Raw output (truncated):\n"
        "views:\n  - title: Broken\n    cards:\n    - type: markdown\n        content: bad"
    )
    assert "\\n" not in message


async def test_render_debug_true_wraps_result_with_trace(
    hass: HomeAssistant, config_entry, hass_ws_client, write_template
) -> None:
    write_template("included.yaml.j2", "value: from_include\n")
    write_template("root.yaml.j2", "cards: !include included.yaml.j2\n")
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "jinjaboard/render", "template": "root.yaml.j2", "debug": True}
    )
    response = await client.receive_json()
    assert response["success"] is True
    assert response["result"]["config"] == {"cards": {"value": "from_include"}}
    debug = response["result"]["debug"]
    assert isinstance(debug["duration_ms"], (int, float))
    assert debug["duration_ms"] >= 0
    # The root's raw text is pre-YAML-parse — the `!include` tag itself is
    # still literally present, not yet resolved to the included file's
    # contents.
    assert "!include included.yaml.j2" in debug["raw_root_text"]
    assert debug["include_paths"] == ["included.yaml.j2"]


async def test_render_debug_string_path_ignored_by_backend(
    hass: HomeAssistant, config_entry, hass_ws_client, write_template
) -> None:
    """The output-path filter (a string/list `debug` value) is applied
    client-side only — the backend only cares whether `debug` is truthy at
    all, and always returns the full, unfiltered config alongside the same
    debug trace."""
    write_template("root.yaml.j2", "views:\n  - title: one\n  - title: two\n")
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "jinjaboard/render", "template": "root.yaml.j2", "debug": "views.0"}
    )
    response = await client.receive_json()
    assert response["success"] is True
    assert response["result"]["config"] == {
        "views": [{"title": "one"}, {"title": "two"}]
    }
    assert "debug" in response["result"]


async def test_render_debug_absent_returns_bare_result_unchanged(
    hass: HomeAssistant, config_entry, hass_ws_client, write_template
) -> None:
    write_template("included.yaml.j2", "value: from_include\n")
    write_template("root.yaml.j2", "cards: !include included.yaml.j2\n")
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "jinjaboard/render", "template": "root.yaml.j2"}
    )
    response = await client.receive_json()
    assert response["success"] is True
    assert response["result"] == {"cards": {"value": "from_include"}}
    assert "config" not in response["result"]
    assert "debug" not in response["result"]


async def test_render_debug_true_by_non_admin_returns_bare_result(
    hass: HomeAssistant,
    config_entry,
    hass_ws_client,
    hass_read_only_access_token,
    write_template,
) -> None:
    write_template("root.yaml.j2", "ok: true\n")
    client = await hass_ws_client(hass, access_token=hass_read_only_access_token)
    await client.send_json_auto_id(
        {"type": "jinjaboard/render", "template": "root.yaml.j2", "debug": True}
    )
    response = await client.receive_json()
    assert response["success"] is True
    assert response["result"] == {"ok": True}
    assert "debug" not in response["result"]


async def test_render_rejects_malformed_debug_payload(
    hass: HomeAssistant, config_entry, hass_ws_client, write_template
) -> None:
    write_template("root.yaml.j2", "ok: true\n")
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "jinjaboard/render", "template": "root.yaml.j2", "debug": 123}
    )
    response = await client.receive_json()
    assert response["success"] is False
    assert response["error"]["code"] == "invalid_format"


async def _setup_narrow_entry(hass: HomeAssistant, entries: list[dict]) -> MockConfigEntry:
    """A JinjaBoard config entry with a specific allowlist, not the permissive
    `config_entry` fixture — used by the tests below that exercise the
    allowlist itself."""
    entry = MockConfigEntry(domain=DOMAIN, options={CONF_ALLOWED_TEMPLATES: entries})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_render_rejects_template_not_on_allowlist(
    hass: HomeAssistant, hass_ws_client, write_template
) -> None:
    write_template("home.yaml.j2", "ok: true\n")
    await _setup_narrow_entry(hass, [])

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "jinjaboard/render", "template": "home.yaml.j2"}
    )
    response = await client.receive_json()
    assert response["success"] is False
    assert response["error"]["code"] == "template_not_authorized"


async def test_render_succeeds_for_exact_allowlisted_file(
    hass: HomeAssistant, hass_ws_client, write_template
) -> None:
    write_template("home.yaml.j2", "ok: true\n")
    await _setup_narrow_entry(hass, [{"path": "home.yaml.j2", "is_dir": False}])

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "jinjaboard/render", "template": "home.yaml.j2"}
    )
    response = await client.receive_json()
    assert response["success"] is True
    assert response["result"] == {"ok": True}


async def test_render_succeeds_for_file_under_allowlisted_directory(
    hass: HomeAssistant, hass_ws_client, write_template
) -> None:
    write_template("dashboards/kitchen.yaml.j2", "ok: true\n")
    await _setup_narrow_entry(hass, [{"path": "dashboards", "is_dir": True}])

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "jinjaboard/render", "template": "dashboards/kitchen.yaml.j2"}
    )
    response = await client.receive_json()
    assert response["success"] is True
    assert response["result"] == {"ok": True}


async def test_render_rejects_globals_file_not_on_allowlist(
    hass: HomeAssistant, hass_ws_client, write_template
) -> None:
    """`globals:` as a file path is a dashboard-author-controlled top-level
    field, same trust boundary as `template:` — authorizing the template
    alone must not implicitly authorize a `globals:` file it names."""
    write_template("globals.yaml", "name: kitchen\n")
    write_template("greet.yaml.j2", "value: {{ jjb.globals.name }}\n")
    await _setup_narrow_entry(hass, [{"path": "greet.yaml.j2", "is_dir": False}])

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "jinjaboard/render",
            "template": "greet.yaml.j2",
            "globals": "globals.yaml",
        }
    )
    response = await client.receive_json()
    assert response["success"] is False
    assert response["error"]["code"] == "template_not_authorized"


async def test_render_rejects_macro_not_on_allowlist(
    hass: HomeAssistant, hass_ws_client, write_template
) -> None:
    """`macros:` entries are checked the same way `globals:` file paths
    are — authorizing the template alone doesn't authorize a `macros:`
    entry it declares."""
    write_template("macros/greet.yaml.j2", "{% macro hi() %}hi{% endmacro %}\n")
    write_template("root.yaml.j2", "value: \"{{ jjb.macros.hi() }}\"\n")
    await _setup_narrow_entry(hass, [{"path": "root.yaml.j2", "is_dir": False}])

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "jinjaboard/render",
            "template": "root.yaml.j2",
            "macros": ["macros/greet.yaml.j2"],
        }
    )
    response = await client.receive_json()
    assert response["success"] is False
    assert response["error"]["code"] == "template_not_authorized"


async def test_render_include_not_checked_against_allowlist(
    hass: HomeAssistant, hass_ws_client, write_template
) -> None:
    """Only the top-level `template` is checked; an `!include`d file that
    isn't itself on the allowlist is still reachable from an authorized
    template — matches the documented "!include etc. are not filtered"
    design, distinct from the path_traversal guard which still applies."""
    write_template("included.yaml.j2", "title: included\n")
    write_template("root.yaml.j2", "views:\n  - !include included.yaml.j2\n")
    await _setup_narrow_entry(hass, [{"path": "root.yaml.j2", "is_dir": False}])

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "jinjaboard/render", "template": "root.yaml.j2"}
    )
    response = await client.receive_json()
    assert response["success"] is True
    assert response["result"] == {"views": [{"title": "included"}]}
